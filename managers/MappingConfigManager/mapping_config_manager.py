"""
This module contains the MappingConfigManager, responsible for providing an
interactive UI for configuring metadata field mappings.

Following the iDesign architecture pattern, managers orchestrate business logic
and coordinate between accessors, engines, and the presentation layer.
This manager handles the user interaction for mapping source metadata keys
to standardized Metalog fields.
"""
import json
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import ipywidgets as widgets
from ipywidgets import VBox, HBox, Layout, Dropdown, Text, Button, Output, Accordion, HTML, ToggleButtons
from IPython.display import display

from Accessors.MetalogAccessor.metalog_accessor import MetalogAccessor, MetalogField


class MappingConfigManager:
    """
    Manager for interactive mapping configuration in Jupyter notebooks.
    
    Provides a widget-based UI for users to map source metadata keys
    (from jattr/attributes) to standardized Metalog target fields.
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
    
    def _create_mapping_row(self, source_keys: List[str], rows_container: VBox, 
                           key_values_map: Dict[str, List[str]]) -> VBox:
        """Creates a single row of widgets for mapping a target field to a source key.
        
        Args:
            source_keys: List of available source key names.
            rows_container: Parent container for deletion callback.
            key_values_map: Dict mapping source key names to their top sample values.
        """
        
        # Build metalog options for dropdown
        metalog_options = [(f.field_name, f.field_name) for f in self._metalog_fields]
        
        # Target field dropdown
        target_dropdown = Dropdown(
            options=[('— Select Target Field —', '')] + metalog_options + [('✏️ Custom...', '__CUSTOM__')],
            layout=Layout(width='220px'),
            style={'description_width': '0px'}
        )
        
        # Custom target input (hidden by default)
        target_custom = Text(
            placeholder='Enter or paste custom field',
            layout=Layout(width='180px', display='none')
        )
        
        # Documentation link button - initially hidden
        doc_button = Button(
            description='📖',
            button_style='',
            tooltip='Open Metalog documentation for this field',
            layout=Layout(width='40px', display='none')
        )
        
        # Store the current doc URL in a mutable container
        current_doc_url = {'url': ''}
        
        def open_documentation(b):
            if current_doc_url['url']:
                webbrowser.open(current_doc_url['url'])
        doc_button.on_click(open_documentation)
        
        # Mode toggle: Map from source OR Set static value
        mode_toggle = ToggleButtons(
            options=[('🔑 From Source', 'source'), ('📌 Static', 'static')],
            value='source',
            layout=Layout(width='auto'),
            button_style=''
        )
        
        # Source key dropdown
        source_dropdown = Dropdown(
            options=[('— Select Source Key —', '')] + [(k, k) for k in source_keys] + [('✏️ Custom...', '__CUSTOM__')],
            layout=Layout(width='220px'),
            style={'description_width': '0px'}
        )
        
        # Custom source input (hidden by default)
        source_custom = Text(
            placeholder='Enter or paste source key',
            layout=Layout(width='180px', display='none')
        )
        
        # Static value input (hidden by default)
        static_value_input = Text(
            placeholder='Value for all samples',
            layout=Layout(width='200px', display='none')
        )
        
        # Value mapping toggle button
        value_map_button = Button(
            description='📝 Values',
            button_style='',
            tooltip='Define value transformations',
            layout=Layout(width='90px', display='none')
        )
        
        delete_button = Button(
            description='✕',
            button_style='danger',
            layout=Layout(width='35px')
        )
        
        # Value mapping panel (initially hidden)
        value_mappings_container = VBox([], layout=Layout(
            display='none',
            padding='10px',
            margin='5px 0 10px 20px',
            border='1px dashed #ccc',
            border_radius='5px',
            background_color='#fafafa'
        ))
        
        # Store value mapping text inputs for later retrieval
        value_mapping_inputs: Dict[str, Text] = {}
        
        def get_target_value() -> str:
            """Get the effective target field value."""
            if target_dropdown.value == '__CUSTOM__':
                return target_custom.value.strip()
            return target_dropdown.value
        
        def get_source_value() -> str:
            """Get the effective source key value."""
            if source_dropdown.value == '__CUSTOM__':
                return source_custom.value.strip()
            return source_dropdown.value
        
        def build_value_mapping_panel(source_key: str):
            """Build the value mapping panel for the selected source key."""
            value_mappings_container.children = []
            value_mapping_inputs.clear()
            
            sample_values = key_values_map.get(source_key, [])
            if not sample_values:
                value_mappings_container.children = [
                    HTML("<p style='color: #666;'>No sample values found for this key.</p>")
                ]
                return
            
            rows = [HTML("<p style='margin: 0 0 8px; color: #666; font-size: 0.9em;'>"
                        "<b>Value Mappings</b> — Leave blank to keep original</p>")]
            
            for val in sample_values:
                source_label = HTML(
                    f"<code style='background: #e8e8e8; padding: 2px 6px; border-radius: 3px;'>{val[:35]}{'...' if len(val) > 35 else ''}</code>",
                    layout=Layout(width='180px')
                )
                arrow = HTML("→", layout=Layout(width='25px'))
                map_input = Text(
                    placeholder='Target value',
                    layout=Layout(width='150px')
                )
                value_mapping_inputs[val] = map_input
                rows.append(HBox([source_label, arrow, map_input], layout=Layout(margin='2px 0', align_items='center')))
            
            value_mappings_container.children = rows
        
        def toggle_value_mappings(b):
            if value_mappings_container.layout.display == 'none':
                value_mappings_container.layout.display = 'block'
                value_map_button.button_style = 'info'
                value_map_button.description = '📝 Hide'
                source_val = get_source_value()
                if source_val:
                    build_value_mapping_panel(source_val)
            else:
                value_mappings_container.layout.display = 'none'
                value_map_button.button_style = ''
                value_map_button.description = '📝 Values'
        
        value_map_button.on_click(toggle_value_mappings)
        
        def on_target_dropdown_change(change):
            if change.new == '__CUSTOM__':
                target_custom.layout.display = 'block'
                doc_button.layout.display = 'none'
                current_doc_url['url'] = ''
            else:
                target_custom.layout.display = 'none'
                if change.new and change.new in self._metalog_docs:
                    doc_button.layout.display = 'block'
                    current_doc_url['url'] = self._metalog_docs[change.new]
                else:
                    doc_button.layout.display = 'none'
                    current_doc_url['url'] = ''
                
        target_dropdown.observe(on_target_dropdown_change, names='value')
        
        def on_source_dropdown_change(change):
            if change.new == '__CUSTOM__':
                source_custom.layout.display = 'block'
            else:
                source_custom.layout.display = 'none'
            
            if change.new and change.new != '__CUSTOM__' and mode_toggle.value == 'source':
                value_map_button.layout.display = 'block'
                if value_mappings_container.layout.display == 'block':
                    build_value_mapping_panel(change.new)
            elif mode_toggle.value == 'source':
                value_map_button.layout.display = 'none'
                value_mappings_container.layout.display = 'none'
                
        source_dropdown.observe(on_source_dropdown_change, names='value')
        
        def on_mode_change(change):
            if change.new == 'static':
                source_dropdown.layout.display = 'none'
                source_custom.layout.display = 'none'
                static_value_input.layout.display = 'block'
                value_map_button.layout.display = 'none'
                value_mappings_container.layout.display = 'none'
            else:
                source_dropdown.layout.display = 'block'
                if source_dropdown.value == '__CUSTOM__':
                    source_custom.layout.display = 'block'
                static_value_input.layout.display = 'none'
                source_val = get_source_value()
                if source_val:
                    value_map_button.layout.display = 'block'
        
        mode_toggle.observe(on_mode_change, names='value')
        
        # Main row - clean horizontal layout
        main_row = HBox(
            [target_dropdown, target_custom, doc_button, HTML("→", layout=Layout(width='20px')), 
             mode_toggle, source_dropdown, source_custom, static_value_input, value_map_button, delete_button],
            layout=Layout(margin='8px 0', align_items='center', gap='6px', flex_wrap='wrap')
        )
        
        # Combined row container (main row + value mappings panel)
        row_container = VBox([main_row, value_mappings_container], layout=Layout(width='100%'))
        
        # Store references for retrieval - use getter functions
        row_container._mapping_widgets = {
            'get_target': get_target_value,
            'get_source': get_source_value,
            'mode_toggle': mode_toggle,
            'static_value_input': static_value_input,
            'value_mapping_inputs': value_mapping_inputs
        }
        
        def on_delete(b):
            rows_container.children = tuple(c for c in rows_container.children if c is not row_container)
        delete_button.on_click(on_delete)
        
        return row_container

    def _build_discovered_keys_display(self, template_data: dict) -> VBox:
        """Creates a nicely formatted display of discovered keys with sample values."""
        
        def format_key_item(key_info: dict, source_badge: str = "") -> HTML:
            key_name = key_info['key_name']
            top_vals = key_info.get('top_values', [])
            display_vals = [str(v)[:30] + '...' if len(str(v)) > 30 else str(v) for v in top_vals[:3]]
            vals_str = ', '.join(f"<code>{v}</code>" for v in display_vals)
            badge_html = f"<span style='background: #e0e0e0; padding: 2px 6px; border-radius: 3px; font-size: 0.8em; margin-left: 8px;'>{source_badge}</span>" if source_badge else ""
            # Copy button with JavaScript onclick handler
            copy_btn = (
                f"<button onclick=\"navigator.clipboard.writeText('{key_name}').then(() => "
                f"{{ this.textContent = '✓'; setTimeout(() => this.textContent = '📋', 1000); }})\" "
                f"style='border: none; background: transparent; cursor: pointer; padding: 2px 4px; "
                f"font-size: 0.9em; margin-left: 4px;' title='Copy field name'>📋</button>"
            )
            return HTML(
                f"<div style='margin: 4px 0; padding: 4px 8px; background: #f5f5f5; border-radius: 4px;'>"
                f"<b>{key_name}</b>{copy_btn}{badge_html}<br/>"
                f"<span style='color: #666; font-size: 0.9em;'>Examples: {vals_str}</span>"
                f"</div>"
            )
        
        jattr_keys = template_data['discovered_keys'].get('from_jattr', [])
        attr_keys = template_data['discovered_keys'].get('from_attributes', [])
        
        # Create lookup dicts
        jattr_dict = {k['key_name']: k for k in jattr_keys}
        attr_dict = {k['key_name']: k for k in attr_keys}
        
        # Find unique and shared keys
        jattr_names = set(jattr_dict.keys())
        attr_names = set(attr_dict.keys())
        shared_names = jattr_names & attr_names
        jattr_only = jattr_names - shared_names
        attr_only = attr_names - shared_names
        
        sections = []
        
        # Show shared keys
        if shared_names:
            shared_items = [format_key_item(jattr_dict[name], "jattr + attributes") for name in sorted(shared_names)]
            sections.append(VBox(
                [HTML(f"<h5 style='margin: 10px 0 5px;'>🔗 Available Keys ({len(shared_names)} fields)</h5>")] + shared_items,
                layout=Layout(width='100%', padding='10px')
            ))
        
        # Show jattr-only keys
        if jattr_only:
            jattr_items = [format_key_item(jattr_dict[name], "jattr only") for name in sorted(jattr_only)]
            sections.append(VBox(
                [HTML(f"<h5 style='margin: 10px 0 5px;'>📦 From 'jattr' only ({len(jattr_only)} fields)</h5>")] + jattr_items,
                layout=Layout(width='100%', padding='10px')
            ))
        
        # Show attr-only keys
        if attr_only:
            attr_items = [format_key_item(attr_dict[name], "attributes only") for name in sorted(attr_only)]
            sections.append(VBox(
                [HTML(f"<h5 style='margin: 10px 0 5px;'>📄 From 'attributes' only ({len(attr_only)} fields)</h5>")] + attr_items,
                layout=Layout(width='100%', padding='10px')
            ))
        
        if not sections:
            sections.append(HTML("<p style='color: #666;'>No metadata keys discovered.</p>"))
        
        return VBox(sections, layout=Layout(width='100%', max_height='400px', overflow_y='auto'))

    def _create_project_ui(self, template_path: Path) -> VBox:
        """Factory function to create UI for a single project."""
        
        with open(template_path, 'r') as f:
            template_data = json.load(f)
        
        project_id = template_path.stem.split('.')[0]
        
        # Collect all source keys and build key-to-values map
        jattr_keys = template_data['discovered_keys'].get('from_jattr', [])
        attr_keys = template_data['discovered_keys'].get('from_attributes', [])
        
        # Build key_values_map: key_name -> list of top values
        key_values_map: Dict[str, List[str]] = {}
        for key_info in jattr_keys + attr_keys:
            key_name = key_info['key_name']
            top_values = key_info.get('top_values', [])
            if key_name in key_values_map:
                # Merge values from both sources
                existing = set(key_values_map[key_name])
                key_values_map[key_name] = list(existing.union(top_values))
            else:
                key_values_map[key_name] = top_values
        
        all_source_keys = sorted(set(k['key_name'] for k in jattr_keys + attr_keys))
        
        # --- UI Components ---
        header = HTML(
            f"<div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); "
            f"color: white; padding: 15px; border-radius: 8px 8px 0 0; margin: -10px -10px 10px -10px;'>"
            f"<h3 style='margin: 0;'>🧬 Configure Mapping: {project_id}</h3>"
            f"</div>"
        )
        
        # Mapping rows container
        rows_container = VBox([], layout=Layout(margin='10px 0'))
        
        # Add row button
        add_button = Button(
            description='+ Add Mapping',
            button_style='info',
            icon='plus',
            layout=Layout(width='150px')
        )
        
        def add_row(b):
            rows_container.children += (self._create_mapping_row(all_source_keys, rows_container, key_values_map),)
        add_button.on_click(add_row)
        
        # Save button and output
        save_button = Button(
            description='💾 Save Configuration',
            button_style='success',
            layout=Layout(width='200px', margin='10px 0')
        )
        output = Output()
        
        # Reference to ui_container for closure
        ui_container_ref = {'widget': None}
        
        def on_save(b):
            with output:
                output.clear_output()
                mappings = {}
                
                for row_container in rows_container.children:
                    # Access stored widget references
                    widgets_ref = row_container._mapping_widgets
                    get_target = widgets_ref['get_target']
                    get_source = widgets_ref['get_source']
                    mode_toggle = widgets_ref['mode_toggle']
                    static_value_input = widgets_ref['static_value_input']
                    value_mapping_inputs = widgets_ref['value_mapping_inputs']
                    
                    target = get_target()
                    
                    if not target:
                        continue  # Skip rows without target field
                    
                    if mode_toggle.value == 'static':
                        # Static value mode
                        static_val = static_value_input.value.strip()
                        if static_val:
                            mappings[target] = {
                                "static_value": static_val
                            }
                    else:
                        # Map from source mode
                        source = get_source()
                        if source:
                            # Extract value mappings from inputs
                            value_mappings = {}
                            for source_val, text_input in value_mapping_inputs.items():
                                target_val = text_input.value.strip()
                                if target_val:  # Only add if user specified a target value
                                    value_mappings[source_val] = target_val
                            
                            mappings[target] = {
                                "key_name": source,
                                "value_mappings": value_mappings
                            }
                
                if not mappings:
                    print("❌ Please create at least one valid mapping")
                    return
                
                # Save config
                config = {"project_id": project_id, "mappings": mappings}
                output_path = self.config_dir / f"{project_id}.json"
                
                with open(output_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                print(f"✅ Saved {len(mappings)} mappings to: {output_path}")
                
                # Hide UI (keep template for reference)
                if ui_container_ref['widget']:
                    ui_container_ref['widget'].layout.display = 'none'
                print("📋 Template file kept for reference")
        
        save_button.on_click(on_save)
        
        # Discovered keys accordion
        keys_display = self._build_discovered_keys_display(template_data)
        accordion = Accordion(children=[keys_display], selected_index=None)
        accordion.set_title(0, '🔍 View Discovered Keys & Sample Values (click to expand)')
        
        # Mapping section
        mapping_section = VBox([
            HTML("<h4 style='margin: 15px 0 10px;'>Create Field Mappings</h4>"),
            HTML("<p style='color: #666; margin-bottom: 10px;'>Map Metalog target fields to source keys from your data. Click 📖 to view field documentation.</p>"),
            rows_container,
            add_button
        ])
        
        # Main container
        ui_container = VBox([
            header,
            accordion,
            mapping_section,
            HBox([save_button]),
            output
        ], layout=Layout(
            border='2px solid #e0e0e0',
            border_radius='8px',
            padding='10px',
            margin='15px 0',
            background_color='white'
        ))
        
        # Store reference for closure
        ui_container_ref['widget'] = ui_container
        
        # Start with one row
        add_row(None)
        
        return ui_container

    def run(self) -> None:
        """
        Run the interactive mapping configuration UI.
        
        Displays a UI for each project with a pending .json.template file.
        """
        # Load schema
        if not self._load_schema():
            return
        
        # Find all .json.template files
        template_files = list(self.config_dir.glob('*.json.template'))
        
        if not template_files:
            print("✅ All configurations are complete. No pending templates found.")
            return
        
        print(f"📋 Found {len(template_files)} project(s) needing configuration:\n")
        
        for template_path in template_files:
            ui = self._create_project_ui(template_path)
            display(ui)
