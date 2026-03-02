"""
This module defines the SRAProcessor, a component responsible for transforming
raw, validated SRA metadata into an enriched, analysis-ready DataFrame.

It implements the 'Guided Configuration' architecture. When processing data for a
project for the first time, it scans the data to find all available metadata keys
and generates a '*.json.template' file. The user then edits this template to
define how raw metadata keys should be mapped to standardized output columns
(e.g., 'tissue_type'). On subsequent runs, the processor uses the completed
'.json' configuration file to perform the transformations automatically.
"""
import json
import re
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

from rich import print

class SRAProcessor:
    """
    Processes SRA metadata DataFrames based on a guided, configurable mapping.
    """
    def __init__(self, config_dir: Path = Path("mapping_configs"), top_n_values: int = 5):
        self.config_dir = config_dir
        self.top_n_values = top_n_values
        self.config_dir.mkdir(exist_ok=True)

    def process(self, df: pd.DataFrame, project_id: str) -> pd.DataFrame:
        """
        Processes the DataFrame by applying mappings defined in a project-specific
        config file. If the config doesn't exist, generates a template to guide
        the user in creating one.

        Args:
            df: The input DataFrame, validated by the SRAAccessor.
            project_id: A unique identifier for the project (e.g., 'PRJEB89352').

        Returns:
            The processed DataFrame with new, enriched columns, or the original
            DataFrame if configuration is pending.
        """
        config_path = self.config_dir / f"{project_id}.json"
        template_path = self.config_dir / f"{project_id}.json.template"

        if not config_path.exists():
            print(f"⚠️ Configuration file not found for project [bold]{project_id}[/bold].")
            self._generate_mapping_template(df, template_path)
            print(f"✅ A new, enhanced configuration template has been created at: [bold]{template_path}[/bold]")
            print("   It now includes sample values for each key to guide you.")
            print("   Please edit this file, then rename it to "
                  f"[bold]{project_id}.json[/bold] and run this cell again.")
            return df # Return original df as configuration is needed

        # If config exists, load it and apply the mappings
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        print(f"✅ Found configuration for project [bold]{project_id}[/bold]. Applying mappings...")
        return self._apply_mappings(df, config)

    def _get_mappings(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Get mappings from config, supporting both 'mappings' and legacy 'suggested_mappings' keys."""
        return config.get("mappings", config.get("suggested_mappings", {}))

    def _scan_for_keys_and_values(self, df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scans 'jattr' and 'attributes' columns separately to find all unique
        metadata keys and a sample of their most common values for each source.
        """
        jattr_key_values = defaultdict(lambda: defaultdict(int))
        attr_key_values = defaultdict(lambda: defaultdict(int))

        # Pass 1: Collect all values and their counts for each key from each source
        for _, row in df.iterrows():
            # Scan jattr (JSON)
            if pd.notna(row['jattr']):
                try:
                    data = json.loads(row['jattr'])
                    for key, value in data.items():
                        if isinstance(value, list):
                            for v in value: jattr_key_values[key][str(v)] += 1
                        elif value is not None:
                            jattr_key_values[key][str(value)] += 1
                except (json.JSONDecodeError, TypeError):
                    continue
            
            # Scan attributes (custom string)
            if pd.notna(row['attributes']):
                try:
                    matches = re.findall(r"k=([^,]+), v=([^}]+)", row['attributes'])
                    for key, value in matches:
                        attr_key_values[key][value] += 1
                except Exception:
                    continue
        
        # Pass 2: Format the output for both sources
        def format_source(key_values: defaultdict) -> List[Dict[str, Any]]:
            discovered_keys = []
            for key, value_counts in sorted(key_values.items()):
                top_values = sorted(value_counts.items(), key=lambda item: item[1], reverse=True)
                top_values = [v[0] for v in top_values[:self.top_n_values]]
                discovered_keys.append({"key_name": key, "top_values": top_values})
            return discovered_keys

        return {
            "from_jattr": format_source(jattr_key_values),
            "from_attributes": format_source(attr_key_values)
        }

    def _generate_mapping_template(self, df: pd.DataFrame, template_path: Path):
        """Generates a .json.template file with source-separated sample values."""
        project_id = df['bioproject'].iloc[0] if not df.empty else "unknown_project"
        discovered_keys = self._scan_for_keys_and_values(df)

        template_content = {
            "_comment": "This template contains discovered metadata keys and sample values. "
                        "Use the interactive UI in the notebook to create mappings, or manually create a .json config file.",
            "project_id": project_id,
            "discovered_keys": discovered_keys
        }

        with open(template_path, 'w') as f:
            json.dump(template_content, f, indent=4)

    def _apply_mappings(self, df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
        """Applies the transformations based on the loaded config file."""
        processed_df = df.copy()
        mappings = self._get_mappings(config)

        for target_col, mapping_rules in mappings.items():
            # Check for static value first
            static_value = mapping_rules.get("static_value")
            if static_value:
                # Apply static value to all rows
                processed_df[target_col] = static_value
                continue
            
            source_key = mapping_rules.get("key_name")
            value_map = mapping_rules.get("value_mappings", {})

            # Skip if the user hasn't edited the template
            if not source_key or "EDIT_ME" in source_key:
                continue

            def find_value(row: pd.Series) -> Optional[str]:
                raw_value = None
                # 1. Check jattr
                if pd.notna(row['jattr']):
                    try:
                        jattr_data = json.loads(row['jattr'])
                        if source_key in jattr_data:
                            value = jattr_data[source_key]
                            raw_value = " ".join(value) if isinstance(value, list) else str(value)
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                # 2. Check attributes if not found in jattr
                if raw_value is None and pd.notna(row['attributes']):
                    try:
                        match = re.search(f"k={re.escape(source_key)}, v=([^}}]+)", row['attributes'])
                        if match:
                            raw_value = match.group(1).strip()
                    except Exception:
                        pass
                
                # 3. Apply value mapping if a raw value was found
                if raw_value is not None:
                    # If a value map exists, use it. Otherwise, return the raw value.
                    if value_map:
                        for map_from, map_to in value_map.items():
                            if map_from.lower() in raw_value.lower():
                                return map_to
                    else:
                        return raw_value # Return the original value if no mapping is defined
                
                return None

            processed_df[target_col] = processed_df.apply(find_value, axis=1)
        
        return processed_df
