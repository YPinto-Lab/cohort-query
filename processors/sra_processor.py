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
import logging
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

logger = logging.getLogger(__name__)

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
            logger.debug("Configuration file not found for project %s", project_id)
            self._generate_mapping_template(df, template_path)
            logger.info("Created configuration template at %s", template_path)
            logger.info("Template includes sample values for each key")
            logger.info("Edit template, rename to %s.json, and rerun", project_id)
            return df # Return original df as configuration is needed

        # If config exists, load it and apply the mappings
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        logger.info("Found configuration for project %s. Applying mappings", project_id)
        return self._apply_mappings(df, config)

    def _get_mappings(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Get mappings from config, supporting both 'mappings' and legacy 'suggested_mappings' keys."""
        return config.get("mappings", config.get("suggested_mappings", {}))

    def _scan_for_keys_and_values(self, df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        """
        Scans 'jattr' and 'attributes' columns to find all unique metadata keys
        and count how many unique samples (accession IDs) have each value.

        Counts are deduplicated: if a key appears in both jattr and attributes
        for the same sample, the sample is counted only once.
        """
        # key -> value -> set of accession IDs (for unique sample counting)
        jattr_key_samples: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
        attr_key_samples: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))

        for _, row in df.iterrows():
            acc = str(row.get('acc', ''))

            if pd.notna(row['jattr']):
                try:
                    data = json.loads(row['jattr'])
                    for key, value in data.items():
                        if isinstance(value, list):
                            for v in value:
                                jattr_key_samples[key][str(v)].add(acc)
                        elif value is not None:
                            jattr_key_samples[key][str(value)].add(acc)
                except (json.JSONDecodeError, TypeError):
                    continue

            if pd.notna(row['attributes']):
                try:
                    matches = re.findall(r"k=([^,]+), v=([^}]+)", row['attributes'])
                    for key, value in matches:
                        attr_key_samples[key][value].add(acc)
                except Exception:
                    continue

        def format_source(key_samples: Dict[str, Dict[str, set]], other_source: Dict[str, Dict[str, set]]) -> List[Dict[str, Any]]:
            discovered_keys = []
            for key, value_acc_sets in sorted(key_samples.items()):
                value_counts = {}
                for value, acc_set in value_acc_sets.items():
                    # Union with the other source to deduplicate across jattr/attributes
                    combined = acc_set | other_source.get(key, {}).get(value, set())
                    value_counts[value] = len(combined)
                sorted_values = sorted(value_counts.items(), key=lambda item: item[1], reverse=True)
                top_values = [v[0] for v in sorted_values[:self.top_n_values]]
                values_with_counts = [{"value": v, "count": c} for v, c in sorted_values]
                discovered_keys.append({
                    "key_name": key,
                    "top_values": top_values,
                    "values_with_counts": values_with_counts
                })
            return discovered_keys

        return {
            "from_jattr": format_source(jattr_key_samples, attr_key_samples),
            "from_attributes": format_source(attr_key_samples, jattr_key_samples)
        }

    def refresh_template(self, df: pd.DataFrame, project_id: str) -> Path:
        """
        (Re)generate the .json.template file so discovered keys and value counts
        are always up to date.  Safe to call at any time — only the template is
        touched; existing .json configs are never modified.

        Returns the path to the template file.
        """
        template_path = self.config_dir / f"{project_id}.json.template"
        self._generate_mapping_template(df, template_path)
        return template_path

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

    def _get_field_value(self, row: pd.Series, key: str) -> Optional[str]:
        """Extract a field value from a row by searching jattr and attributes."""
        value = None
        
        # Check jattr first
        if pd.notna(row['jattr']):
            try:
                jattr_data = json.loads(row['jattr'])
                if key in jattr_data:
                    v = jattr_data[key]
                    value = " ".join(v) if isinstance(v, list) else str(v)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Check attributes if not found
        if value is None and pd.notna(row['attributes']):
            try:
                match = re.search(f"k={re.escape(key)}, v=([^}}]+)", row['attributes'])
                if match:
                    value = match.group(1).strip()
            except Exception:
                pass
        
        return value

    def _apply_filters(self, df: pd.DataFrame, filters: Dict[str, Any]) -> pd.DataFrame:
        """Apply sample filters to the DataFrame.
        
        Args:
            df: Input DataFrame
            filters: Filter configuration containing:
                - exclude_project: bool - if True, exclude all samples
                - sample_filters: list of filter rules
        
        Returns:
            Filtered DataFrame
        """
        # Check if entire project should be excluded
        if filters.get("exclude_project", False):
            logger.info("Project excluded by filter configuration")
            return df.iloc[0:0]  # Return empty df with same columns
        
        sample_filters = filters.get("sample_filters", [])
        if not sample_filters:
            return df
        
        logger.info("Applying %d filter(s)", len(sample_filters))
        
        # Build a mask for each row
        result_df = df.copy()
        
        for filter_rule in sample_filters:
            action = filter_rule.get("action", "include")
            key = filter_rule.get("key")
            operator = filter_rule.get("operator", "equals")
            value = filter_rule.get("value", "")
            
            if not key:
                continue
            
            # Create mask based on operator
            def check_condition(row):
                field_value = self._get_field_value(row, key)
                
                if operator == "is_empty":
                    return field_value is None or field_value == ""
                elif operator == "is_not_empty":
                    return field_value is not None and field_value != ""
                elif field_value is None:
                    return False
                elif operator == "equals":
                    return field_value.lower() == value.lower()
                elif operator == "contains":
                    return value.lower() in field_value.lower()
                elif operator == "starts_with":
                    return field_value.lower().startswith(value.lower())
                elif operator == "ends_with":
                    return field_value.lower().endswith(value.lower())
                return False
            
            mask = result_df.apply(check_condition, axis=1)
            
            if action == "include":
                # Keep only rows matching the condition
                result_df = result_df[mask]
            else:  # exclude
                # Remove rows matching the condition
                result_df = result_df[~mask]
            
            logger.info(
                "Filter '%s %s %s' (%s): %d samples remaining",
                key,
                operator,
                value,
                action,
                len(result_df),
            )
        
        return result_df

    def _apply_mappings(self, df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
        """Applies the transformations based on the loaded config file."""
        processed_df = df.copy()
        
        # Apply filters first
        filters = config.get("filters", {})
        if filters:
            processed_df = self._apply_filters(processed_df, filters)
            if processed_df.empty:
                logger.info("All samples were filtered out")
                return processed_df
        
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
