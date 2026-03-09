"""
MappingConfigManager - Target-First Approach

This module provides an interactive UI for configuring metadata field mappings
using a "target field first" approach: define target fields once, then configure
how each project maps to them.

Following the iDesign architecture pattern, managers orchestrate business logic
and coordinate between accessors, engines, and the presentation layer.
"""
import json
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

import ipywidgets as widgets
from ipywidgets import (
    VBox, HBox, Layout, Dropdown, Text, Button, Output, 
    Accordion, HTML, ToggleButtons, Textarea, Checkbox, Tab
)
from IPython.display import display, clear_output

from Accessors.MetalogAccessor.metalog_accessor import MetalogAccessor, MetalogField


class MappingConfigManager:
    """
    Manager for interactive mapping configuration in Jupyter notebooks.
    
    Uses a "target field first" approach:
    1. Add target fields (e.g., 'sex', 'environment_material')
    2. For each target field, configure per-project mapping
    3. Save generates individual JSON configs per project
    """
    
    def __init__(self, config_dir: Path = Path('mapping_configs')):
        """
        Initialize the manager.
        
        Args:
            config_dir: Directory containing mapping config templates and outputs.
        """
        self.config_dir = config_dir
        self.metalog_accessor = MetalogAccessor()
        self._metalog_fields: List[MetalogField] = []
        self._metalog_docs: Dict[str, str] = {}
        
        # Project data loaded from templates
        self._projects: Dict[str, dict] = {}  # project_id -> template data
        self._project_source_keys: Dict[str, List[str]] = {}  # project_id -> source keys
        self._project_key_values: Dict[str, Dict[str, List[str]]] = {}  # project_id -> key -> values
        self._project_key_values_with_counts: Dict[str, Dict[str, List[dict]]] = {}  # project_id -> key -> [{value, count}]
        self._existing_configs: Dict[str, dict] = {}  # project_id -> existing config
        
        # Target fields state
        self._target_fields: List[str] = []
        
        # UI components
        self._output: Optional[Output] = None
        self._target_fields_container: Optional[VBox] = None
    
    def _load_schema(self) -> bool:
        """Load the Metalog schema. Returns True if successful."""
        try:
            self.metalog_accessor.load()
            self._metalog_fields = self.metalog_accessor.fields
            self._metalog_docs = self.metalog_accessor.documentation_urls
            print(f"✅ Loaded {len(self._metalog_fields)} fields from Metalog schema")
            return True
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return False
    
    def _load_projects(self) -> bool:
        """Load all project templates and existing configs."""
        template_files = list(self.config_dir.glob('*.json.template'))
        
        if not template_files:
            print("✅ No project templates found. Run the processing cell first to discover projects.")
            return False
        
        for template_path in template_files:
            project_id = template_path.stem.split('.')[0]
            
            # Load template
            with open(template_path, 'r') as f:
                template_data = json.load(f)
            self._projects[project_id] = template_data
            
            # Build source keys and key-values map (with counts if available)
            jattr_keys = template_data['discovered_keys'].get('from_jattr', [])
            attr_keys = template_data['discovered_keys'].get('from_attributes', [])
            
            key_values_map: Dict[str, List[str]] = {}  # key -> list of values
            key_values_with_counts: Dict[str, List[dict]] = {}  # key -> [{value, count}, ...]
            
            for key_info in jattr_keys + attr_keys:
                key_name = key_info['key_name']
                
                # Use values_with_counts if available (new format)
                if 'values_with_counts' in key_info:
                    values_with_counts = key_info['values_with_counts']
                    if key_name in key_values_with_counts:
                        existing = {vc['value']: vc['count'] for vc in key_values_with_counts[key_name]}
                        for vc in values_with_counts:
                            if vc['value'] in existing:
                                existing[vc['value']] += vc['count']
                            else:
                                existing[vc['value']] = vc['count']
                        key_values_with_counts[key_name] = [{'value': v, 'count': c} for v, c in sorted(existing.items(), key=lambda x: -x[1])]
                    else:
                        key_values_with_counts[key_name] = values_with_counts
                    # Also populate key_values_map for backwards compatibility
                    key_values_map[key_name] = [vc['value'] for vc in key_values_with_counts[key_name]]
                else:
                    # Fallback to old format without counts
                    top_values = key_info.get('top_values', [])
                    if key_name in key_values_map:
                        existing = set(key_values_map[key_name])
                        key_values_map[key_name] = list(existing.union(top_values))
                    else:
                        key_values_map[key_name] = top_values
            
            self._project_source_keys[project_id] = sorted(set(k['key_name'] for k in jattr_keys + attr_keys))
            self._project_key_values[project_id] = key_values_map
            self._project_key_values_with_counts[project_id] = key_values_with_counts
            
            # Load existing config if present
            config_path = self.config_dir / f"{project_id}.json"
            if config_path.exists():
                try:
                    with open(config_path, 'r') as f:
                        self._existing_configs[project_id] = json.load(f)
                except (json.JSONDecodeError, IOError):
                    pass
        
        # Extract existing target fields from all configs
        existing_targets: Set[str] = set()
        for config in self._existing_configs.values():
            mappings = config.get('mappings', {})
            existing_targets.update(mappings.keys())
        self._target_fields = sorted(existing_targets)
        
        print(f"📋 Loaded {len(self._projects)} project(s)")
        if self._target_fields:
            print(f"📝 Found {len(self._target_fields)} existing target field(s): {self._target_fields}")
        
        return True
    
    def _get_all_source_keys(self) -> List[str]:
        """Get union of all source keys across all projects."""
        all_keys: Set[str] = set()
        for keys in self._project_source_keys.values():
            all_keys.update(keys)
        return sorted(all_keys)
    
    def _create_project_mapping_row(
        self, 
        project_id: str, 
        target_field: str,
        on_change_callback: callable
    ) -> VBox:
        """Create a mapping configuration row for a single project within a target field."""
        
        source_keys = self._project_source_keys.get(project_id, [])
        key_values_map = self._project_key_values.get(project_id, {})
        
        # Get existing mapping for this target field in this project
        existing_config = self._existing_configs.get(project_id, {})
        existing_mapping = existing_config.get('mappings', {}).get(target_field, {})
        
        # Determine initial values
        if 'static_value' in existing_mapping:
            init_mode = 'static'
            init_source = ''
            init_static = existing_mapping['static_value']
            init_value_mappings = {}
        elif 'key_name' in existing_mapping:
            init_mode = 'source'
            init_source = existing_mapping['key_name']
            init_static = ''
            init_value_mappings = existing_mapping.get('value_mappings', {})
        else:
            init_mode = 'source'
            init_source = ''
            init_static = ''
            init_value_mappings = {}
        
        # Project label with status indicator
        status_icon = "✓" if existing_mapping else "○"
        status_color = "#4CAF50" if existing_mapping else "#999"
        project_label = HTML(
            f"<span style='font-weight: bold; color: {status_color}; width: 120px; display: inline-block;'>"
            f"{status_icon} {project_id}</span>",
            layout=Layout(width='140px')
        )
        
        # Mode toggle
        mode_toggle = ToggleButtons(
            options=[('🔑 Source', 'source'), ('📌 Static', 'static'), ('⏭️ Skip', 'skip')],
            value='skip' if not existing_mapping and not init_source else init_mode,
            layout=Layout(width='200px'),
            style={'button_width': '200px'}
        )
        
        # Source key dropdown
        source_dropdown = Dropdown(
            options=[('Select source key...', '')] + [(k, k) for k in source_keys],
            value=init_source if init_source in source_keys else '',
            layout=Layout(width='200px', display='block' if mode_toggle.value == 'source' else 'none'),
            style={'description_width': '0px'}
        )
        
        # Static value input (Textarea with rows=1 for paste support)
        static_input = Textarea(
            value=init_static,
            placeholder='Static value',
            rows=1,
            layout=Layout(width='200px', height='32px', display='block' if mode_toggle.value == 'static' else 'none')
        )
        
        # Value mappings button and panel
        value_map_button = Button(
            description='📝 Values',
            button_style='',
            tooltip='Define value transformations',
            layout=Layout(width='80px', display='block' if init_source else 'none')
        )
        
        value_mappings_container = VBox([], layout=Layout(
            display='none',
            padding='8px',
            margin='5px 0 5px 140px',
            border='1px dashed #ccc',
            border_radius='5px',
            background_color='#fafafa'
        ))
        
        # Store value mapping inputs
        value_mapping_inputs: Dict[str, Text] = {}
        
        def build_value_mapping_panel(source_key: str):
            """Build the value mapping panel for the selected source key."""
            value_mappings_container.children = []
            value_mapping_inputs.clear()
            
            sample_values = key_values_map.get(source_key, [])
            if not sample_values:
                value_mappings_container.children = [
                    HTML("<span style='color: #666; font-size: 12px;'>No sample values found</span>")
                ]
                return
            
            rows = [HTML("<span style='color: #666; font-size: 11px;'><b>Value Mappings</b> — Leave blank to keep original</span>")]
            
            for val in sample_values[:10]:  # Limit to 10 values
                # Check if we have an existing mapping
                existing_target = init_value_mappings.get(val, '')
                
                source_label = HTML(
                    f"<code style='background: #e8e8e8; padding: 2px 6px; border-radius: 3px; font-size: 11px;'>"
                    f"{val[:30]}{'...' if len(str(val)) > 30 else ''}</code>",
                    layout=Layout(width='160px')
                )
                arrow = HTML("→", layout=Layout(width='20px'))
                map_input = Text(
                    value=existing_target,
                    placeholder='Target value',
                    layout=Layout(width='120px')
                )
                map_input.observe(lambda c: on_change_callback(), names='value')
                value_mapping_inputs[val] = map_input
                rows.append(HBox([source_label, arrow, map_input], layout=Layout(margin='2px 0', align_items='center')))
            
            value_mappings_container.children = rows
        
        def toggle_value_mappings(b):
            if value_mappings_container.layout.display == 'none':
                value_mappings_container.layout.display = 'block'
                value_map_button.button_style = 'info'
                source_key = source_dropdown.value
                if source_key:
                    build_value_mapping_panel(source_key)
            else:
                value_mappings_container.layout.display = 'none'
                value_map_button.button_style = ''
        
        value_map_button.on_click(toggle_value_mappings)
        
        def on_mode_change(change):
            if change.new == 'source':
                source_dropdown.layout.display = 'block'
                static_input.layout.display = 'none'
                if source_dropdown.value:
                    value_map_button.layout.display = 'block'
            elif change.new == 'static':
                source_dropdown.layout.display = 'none'
                static_input.layout.display = 'block'
                value_map_button.layout.display = 'none'
                value_mappings_container.layout.display = 'none'
            else:  # skip
                source_dropdown.layout.display = 'none'
                static_input.layout.display = 'none'
                value_map_button.layout.display = 'none'
                value_mappings_container.layout.display = 'none'
            on_change_callback()
        
        mode_toggle.observe(on_mode_change, names='value')
        
        def on_source_change(change):
            if change.new:
                value_map_button.layout.display = 'block'
                if value_mappings_container.layout.display == 'block':
                    build_value_mapping_panel(change.new)
            else:
                value_map_button.layout.display = 'none'
                value_mappings_container.layout.display = 'none'
            on_change_callback()
        
        source_dropdown.observe(on_source_change, names='value')
        static_input.observe(lambda c: on_change_callback(), names='value')
        
        # Main row (without Values button to avoid dropdown overlap)
        main_row = HBox(
            [project_label, mode_toggle, source_dropdown, static_input],
            layout=Layout(align_items='center', gap='8px', margin='4px 0')
        )
        
        # Values button row (below dropdown to avoid overlap)
        values_row = HBox(
            [value_map_button],
            layout=Layout(margin='0 0 0 350px')  # Align under the dropdown
        )
        
        row_container = VBox([main_row, values_row, value_mappings_container])
        
        # Store references for data extraction
        row_container._mapping_data = {
            'project_id': project_id,
            'mode_toggle': mode_toggle,
            'source_dropdown': source_dropdown,
            'static_input': static_input,
            'value_mapping_inputs': value_mapping_inputs
        }
        
        return row_container
    
    def _create_target_field_panel(self, target_field: str, on_delete: callable) -> VBox:
        """Create a panel for configuring a single target field across all projects."""
        
        # Track unsaved changes
        has_changes = [False]
        
        def mark_changed():
            has_changes[0] = True
            save_btn.button_style = 'warning'
            save_btn.description = '💾 Save*'
        
        # Header with target field name and doc link
        doc_url = self._metalog_docs.get(target_field, '')
        doc_link = ""
        if doc_url:
            doc_link = f" <a href='{doc_url}' target='_blank' style='font-size: 12px;'>📖 docs</a>"
        
        header = HTML(
            f"<div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); "
            f"color: white; padding: 10px 15px; border-radius: 6px; margin-bottom: 8px;'>"
            f"<span style='font-size: 16px; font-weight: bold;'>🎯 {target_field}</span>{doc_link}"
            f"</div>"
        )
        
        # Create per-project rows
        project_rows = VBox([])
        for project_id in sorted(self._projects.keys()):
            row = self._create_project_mapping_row(project_id, target_field, mark_changed)
            project_rows.children += (row,)
        
        # Save button for this target field
        save_btn = Button(
            description='💾 Save',
            button_style='success',
            layout=Layout(width='100px')
        )
        
        # Delete target field button
        delete_btn = Button(
            description='🗑️ Remove',
            button_style='danger',
            layout=Layout(width='100px')
        )
        
        save_output = Output()
        
        def on_save(b):
            with save_output:
                clear_output()
                
                saved_count = 0
                
                for row in project_rows.children:
                    data = row._mapping_data
                    project_id = data['project_id']
                    mode = data['mode_toggle'].value
                    
                    # Load or create config for this project
                    config_path = self.config_dir / f"{project_id}.json"
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            config = json.load(f)
                    else:
                        config = {
                            "project_id": project_id,
                            "filters": {"exclude_project": False, "sample_filters": []},
                            "mappings": {}
                        }
                    
                    if mode == 'skip':
                        # Remove this target field from mappings if it exists
                        if target_field in config.get('mappings', {}):
                            del config['mappings'][target_field]
                    elif mode == 'source':
                        source_key = data['source_dropdown'].value
                        if source_key:
                            value_mappings = {}
                            for source_val, text_input in data['value_mapping_inputs'].items():
                                target_val = text_input.value.strip()
                                if target_val:
                                    value_mappings[source_val] = target_val
                            
                            config['mappings'][target_field] = {
                                "key_name": source_key,
                                "value_mappings": value_mappings
                            }
                            saved_count += 1
                    elif mode == 'static':
                        static_val = data['static_input'].value.strip()
                        if static_val:
                            config['mappings'][target_field] = {
                                "static_value": static_val
                            }
                            saved_count += 1
                    
                    # Save config
                    with open(config_path, 'w') as f:
                        json.dump(config, f, indent=4)
                    
                    # Update cached config
                    self._existing_configs[project_id] = config
                
                print(f"✅ Saved '{target_field}' mapping to {saved_count} project(s)")
                has_changes[0] = False
                save_btn.button_style = 'success'
                save_btn.description = '💾 Save'
        
        save_btn.on_click(on_save)
        delete_btn.on_click(lambda b: on_delete(target_field))
        
        # Layout
        buttons_row = HBox([save_btn, delete_btn], layout=Layout(margin='10px 0', gap='10px'))
        
        panel = VBox([
            header,
            project_rows,
            buttons_row,
            save_output
        ], layout=Layout(
            border='1px solid #ddd',
            border_radius='8px',
            padding='10px',
            margin='10px 0',
            background_color='#fafafa'
        ))
        
        panel._target_field = target_field
        
        return panel
    
    def _create_add_target_ui(self) -> VBox:
        """Create the UI for adding a new target field."""
        
        metalog_options = [('Select Metalog field...', '')] + [(f.field_name, f.field_name) for f in self._metalog_fields]
        
        field_dropdown = Dropdown(
            options=metalog_options,
            layout=Layout(width='250px'),
            style={'description_width': '0px'}
        )
        
        custom_input = Text(
            placeholder='Or enter custom field name',
            layout=Layout(width='200px')
        )
        
        add_btn = Button(
            description='+ Add Target Field',
            button_style='primary',
            layout=Layout(width='150px')
        )
        
        add_output = Output()
        
        def on_add(b):
            with add_output:
                clear_output()
                
                # Get field name from dropdown or custom input
                field_name = field_dropdown.value or custom_input.value.strip()
                
                if not field_name:
                    print("❌ Please select or enter a target field name")
                    return
                
                if field_name in self._target_fields:
                    print(f"⚠️ '{field_name}' is already added")
                    return
                
                # Add to target fields
                self._target_fields.append(field_name)
                
                # Create and add panel
                def on_delete(target):
                    self._remove_target_field(target)
                
                panel = self._create_target_field_panel(field_name, on_delete)
                self._target_fields_container.children += (panel,)
                
                # Reset inputs
                field_dropdown.value = ''
                custom_input.value = ''
                
                print(f"✅ Added target field: {field_name}")
        
        add_btn.on_click(on_add)
        
        return VBox([
            HTML("<h4 style='margin: 5px 0;'>➕ Add New Target Field</h4>"),
            HBox([field_dropdown, HTML("<span style='margin: 0 10px;'>or</span>"), custom_input, add_btn],
                 layout=Layout(align_items='center', gap='5px')),
            add_output
        ], layout=Layout(
            border='2px dashed #667eea',
            border_radius='8px',
            padding='15px',
            margin='15px 0',
            background_color='#f8f9ff'
        ))
    
    def _remove_target_field(self, target_field: str):
        """Remove a target field and its panel."""
        if target_field in self._target_fields:
            self._target_fields.remove(target_field)
        
        # Remove panel from container
        self._target_fields_container.children = tuple(
            c for c in self._target_fields_container.children 
            if getattr(c, '_target_field', None) != target_field
        )
        
        # Note: This doesn't remove from saved configs - user should save to persist
        print(f"🗑️ Removed target field: {target_field}")
        print("   Note: To remove from project configs, save each project or manually edit JSON files.")
    
    def _create_discovered_keys_summary(self) -> Accordion:
        """Create summary of discovered keys across all projects with project filter buttons."""
        
        # Build key -> projects mapping
        all_keys: Dict[str, Set[str]] = {}  # key_name -> set of projects that have it
        
        for project_id, keys in self._project_source_keys.items():
            for key in keys:
                if key not in all_keys:
                    all_keys[key] = set()
                all_keys[key].add(project_id)
        
        # Create project filter buttons
        project_buttons: Dict[str, Button] = {}
        for project_id in sorted(self._projects.keys()):
            btn = Button(
                description=project_id,
                button_style='',  # Not pressed initially
                layout=Layout(width='auto', margin='2px')
            )
            project_buttons[project_id] = btn
        
        buttons_row = HBox(
            list(project_buttons.values()),
            layout=Layout(margin='0 0 10px 0', flex_wrap='wrap')
        )
        
        # Keys container (will be updated dynamically)
        keys_container = VBox([], layout=Layout(max_height='250px', overflow_y='auto', padding='5px'))
        
        # Track selected projects
        selected_projects: Set[str] = set()
        
        def build_keys_display():
            """Rebuild the keys display based on selected projects."""
            # Determine which keys to show
            if not selected_projects:
                # No filter - show all keys
                filtered_keys = all_keys
                filter_mode = "all"
            else:
                # Show keys that appear in ANY of the selected projects
                filtered_keys = {
                    k: v for k, v in all_keys.items() 
                    if v.intersection(selected_projects)
                }
                filter_mode = "filtered"
            
            # Sort by commonality
            sorted_keys = sorted(filtered_keys.items(), key=lambda x: -len(x[1]))
            
            rows = []
            for key_name, projects in sorted_keys[:40]:  # Show up to 40 keys
                project_count = len(projects)
                total_projects = len(self._projects)
                
                # If filtering, show count relative to selected projects
                if selected_projects:
                    in_selected = len(projects.intersection(selected_projects))
                    coverage_text = f"{in_selected}/{len(selected_projects)} selected"
                    coverage_color = 'green' if in_selected == len(selected_projects) else '#666'
                else:
                    coverage_text = f"{project_count}/{total_projects} projects"
                    coverage_color = 'green' if project_count == total_projects else '#666'
                
                # Get values with counts from projects (prefer selected ones if filtering)
                values_display = []
                search_order = list(selected_projects) if selected_projects else list(projects)
                for pid in search_order:
                    if pid in projects:
                        # Try to get values with counts first
                        vals_with_counts = self._project_key_values_with_counts.get(pid, {}).get(key_name, [])
                        if vals_with_counts:
                            for vc in vals_with_counts:
                                val = str(vc['value'])
                                count = vc['count']
                                truncated = val[:20] + '...' if len(val) > 20 else val
                                values_display.append(f"<code>{truncated}</code> <span style='color:#888;font-size:0.8em;'>({count})</span>")
                            break
                        else:
                            # Fallback to old format without counts
                            vals = self._project_key_values.get(pid, {}).get(key_name, [])
                            if vals:
                                for v in vals:
                                    truncated = str(v)[:20] + '...' if len(str(v)) > 20 else str(v)
                                    values_display.append(f"<code>{truncated}</code>")
                                break
                
                vals_str = ', '.join(values_display) if values_display else "<i>no examples</i>"
                
                rows.append(HTML(
                    f"<div style='margin: 3px 0; padding: 4px 8px; background: #f5f5f5; border-radius: 4px;'>"
                    f"<b>{key_name}</b> — <span style='color: {coverage_color};'>{coverage_text}</span><br/>"
                    f"<span style='color: #666; font-size: 12px;'>Values: {vals_str}</span>"
                    f"</div>"
                ))
            
            if not rows:
                rows.append(HTML("<span style='color: #666;'>No keys found for selected projects</span>"))
            
            keys_container.children = rows
        
        def on_button_click(project_id: str):
            def handler(b):
                if project_id in selected_projects:
                    selected_projects.remove(project_id)
                    b.button_style = ''
                else:
                    selected_projects.add(project_id)
                    b.button_style = 'info'
                build_keys_display()
            return handler
        
        # Attach click handlers
        for project_id, btn in project_buttons.items():
            btn.on_click(on_button_click(project_id))
        
        # Initial build
        build_keys_display()
        
        # Filter hint
        hint = HTML(
            "<span style='color: #888; font-size: 11px;'>"
            "💡 Click project buttons to filter keys. No selection = show all.</span>"
        )
        
        content = VBox([hint, buttons_row, keys_container], layout=Layout(padding='10px'))
        accordion = Accordion(children=[content], selected_index=None)
        accordion.set_title(0, f'🔍 Discovered Source Keys ({len(all_keys)} unique keys across {len(self._projects)} projects)')
        
        return accordion
    
    def run(self) -> None:
        """
        Run the interactive mapping configuration UI.
        
        Displays a target-field-first UI where:
        1. Users add target fields
        2. For each target, configure per-project mapping
        """
        # Load schema and projects
        if not self._load_schema():
            return
        
        if not self._load_projects():
            return
        
        print()
        
        # Main header
        header = HTML(
            f"<div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); "
            f"color: white; padding: 20px; border-radius: 8px; margin-bottom: 15px;'>"
            f"<h2 style='margin: 0;'>🗺️ Mapping Configuration</h2>"
            f"<p style='margin: 5px 0 0 0; opacity: 0.9;'>"
            f"Define target fields once, configure per-project mappings below</p>"
            f"</div>"
        )
        
        # Discovered keys summary
        keys_accordion = self._create_discovered_keys_summary()
        
        # Add target field UI
        add_target_ui = self._create_add_target_ui()
        
        # Target fields container
        self._target_fields_container = VBox([])
        
        # Populate existing target fields
        def on_delete(target):
            self._remove_target_field(target)
        
        for target_field in self._target_fields:
            panel = self._create_target_field_panel(target_field, on_delete)
            self._target_fields_container.children += (panel,)
        
        # Save all button
        save_all_btn = Button(
            description='💾 Save All Mappings',
            button_style='success',
            layout=Layout(width='180px', margin='20px 0')
        )
        save_all_output = Output()
        
        def on_save_all(b):
            with save_all_output:
                clear_output()
                print("💾 Saving all mappings...")
                
                # Click save on each target field panel
                for panel in self._target_fields_container.children:
                    # Find and click the save button
                    for child in panel.children:
                        if isinstance(child, HBox):
                            for btn in child.children:
                                if isinstance(btn, Button) and '💾' in btn.description:
                                    btn.click()
                                    break
                
                print("✅ All mappings saved!")
        
        save_all_btn.on_click(on_save_all)
        
        # Main UI
        main_ui = VBox([
            header,
            keys_accordion,
            add_target_ui,
            self._target_fields_container,
            HBox([save_all_btn]),
            save_all_output
        ])
        
        display(main_ui)
