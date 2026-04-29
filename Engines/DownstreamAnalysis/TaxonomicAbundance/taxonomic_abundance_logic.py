import json
import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from Common.contracts.sra_schema import SRAMetadataSchema

_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())


@dataclass
class TaxonomicAbundanceInputs:
    taxonomy_df: Optional[pd.DataFrame] = None
    metadata_df: Optional[pd.DataFrame] = None
    abundance_metadata_matrix: Optional[pd.DataFrame] = None
    taxon_lookup_df: Optional[pd.DataFrame] = None
    metadata_cols: Optional[List[str]] = None


class TaxonomicAbundanceLogic:
    def __init__(self, inputs: TaxonomicAbundanceInputs, logger=None):
        self._log = logger or print
        self._setup_mode(inputs)
        self.source_keys = self._discover_source_keys()

    def _setup_mode(self, inputs: TaxonomicAbundanceInputs):
        self._is_wide_mode = inputs.abundance_metadata_matrix is not None
        if self._is_wide_mode:
            self._setup_wide_mode(inputs)
            self._finalize_common_metadata(inputs.taxonomy_df)
            return
        self._setup_long_mode(inputs)
        self._finalize_common_metadata(inputs.taxonomy_df)

    def _setup_wide_mode(self, inputs: TaxonomicAbundanceInputs):
        if inputs.taxon_lookup_df is None:
            raise ValueError("taxon_lookup_df is required when using analysis_wide_df")
        metadata_cols = self._resolve_wide_metadata_cols(inputs)
        self._validate_wide_metadata_cols(inputs.abundance_metadata_matrix, metadata_cols)
        self.metadata_df = inputs.abundance_metadata_matrix[metadata_cols].copy()
        self.taxon_lookup_df = self._prepare_taxon_lookup(inputs.taxon_lookup_df)
        self._taxon_cols = self._resolve_taxon_columns(inputs.abundance_metadata_matrix)
        self._abundance_source = inputs.abundance_metadata_matrix
        self.sample_taxa_matrix = None
        self.taxonomy_df = None

    def _resolve_wide_metadata_cols(self, inputs: TaxonomicAbundanceInputs) -> List[str]:
        if inputs.metadata_cols is not None:
            return list(inputs.metadata_cols)
        if inputs.metadata_df is not None:
            return list(inputs.metadata_df.columns)
        return [c for c in inputs.abundance_metadata_matrix.columns if c in _BASE_METADATA_COLS]

    def _validate_wide_metadata_cols(self, matrix: pd.DataFrame, metadata_cols: List[str]):
        missing_meta = [c for c in metadata_cols if c not in matrix.columns]
        if missing_meta:
            raise ValueError(f"analysis_wide_df is missing metadata columns: {missing_meta}")

    def _prepare_taxon_lookup(self, taxon_lookup_df: pd.DataFrame) -> pd.DataFrame:
        required_lookup = {"taxon_key", "rank", "name"}
        missing_lookup = required_lookup - set(taxon_lookup_df.columns)
        if missing_lookup:
            raise ValueError(f"taxon_lookup_df is missing required columns: {missing_lookup}")
        prepared = taxon_lookup_df.copy()
        prepared["taxon_key"] = prepared["taxon_key"].astype(str)
        return prepared

    def _resolve_taxon_columns(self, matrix: pd.DataFrame) -> List[str]:
        taxon_key_set = set(self.taxon_lookup_df["taxon_key"])
        return [c for c in matrix.columns if c in taxon_key_set]

    def _setup_long_mode(self, inputs: TaxonomicAbundanceInputs):
        if inputs.taxonomy_df is None or inputs.metadata_df is None:
            raise ValueError("taxonomy_df and metadata_df are required in long-format mode")
        self.taxonomy_df = inputs.taxonomy_df
        self.metadata_df = inputs.metadata_df
        self.taxon_lookup_df = None
        self.sample_taxa_matrix = None
        self._taxon_cols = []
        self._abundance_source = None

    def _finalize_common_metadata(self, taxonomy_df: Optional[pd.DataFrame]):
        mapped_cols = [c for c in self.metadata_df.columns if c not in _BASE_METADATA_COLS]
        self.cat_cols = [c for c in mapped_cols if pd.api.types.is_string_dtype(self.metadata_df[c])]
        self.available_ranks = self._discover_available_ranks(taxonomy_df)

    def _discover_available_ranks(self, taxonomy_df: Optional[pd.DataFrame]) -> List[str]:
        order = ["superkingdom", "phylum", "class", "order", "family", "genus", "species"]
        if self._is_wide_mode:
            ranks = self.taxon_lookup_df["rank"].astype(str).str.lower().dropna().unique()
            return [r for r in order if r in ranks]
        ranks = taxonomy_df["rank"].str.lower().dropna().unique()
        return [r for r in order if r in ranks]

    def extract_source_key_value(self, row: pd.Series, key: str) -> Optional[str]:
        requested_key = str(key).strip()
        direct_value = self._extract_direct_value(row, requested_key)
        if direct_value is not None:
            return direct_value
        from_jattr = self._extract_jattr_value(row, requested_key)
        if from_jattr is not None:
            return from_jattr
        return self._extract_attributes_value(row, requested_key)

    def _extract_direct_value(self, row: pd.Series, requested_key: str) -> Optional[str]:
        direct = row.get(requested_key)
        if pd.notna(direct):
            return str(direct)
        key_lower = requested_key.lower()
        for col in row.index:
            if str(col).strip().lower() != key_lower:
                continue
            candidate = row.get(col)
            if pd.notna(candidate):
                return str(candidate)
        return None

    def _extract_jattr_value(self, row: pd.Series, requested_key: str) -> Optional[str]:
        raw = row.get("jattr")
        if pd.isna(raw):
            return None
        parsed = self._parse_json_dict(raw)
        if parsed is None:
            return None
        return self._dict_value_case_insensitive(parsed, requested_key)

    def _parse_json_dict(self, raw) -> Optional[dict]:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _dict_value_case_insensitive(self, data: dict, requested_key: str) -> Optional[str]:
        if requested_key in data:
            return self._stringify_value(data[requested_key])
        key_lower = requested_key.lower()
        for key, value in data.items():
            if str(key).strip().lower() != key_lower:
                continue
            return self._stringify_value(value)
        return None

    def _stringify_value(self, value) -> str:
        if isinstance(value, list):
            return " ".join(value)
        return str(value)

    def _extract_attributes_value(self, row: pd.Series, requested_key: str) -> Optional[str]:
        raw = row.get("attributes")
        if pd.isna(raw):
            return None
        pairs = re.findall(r"k\s*=\s*([^,]+),\s*v\s*=\s*([^}]+)", str(raw))
        key_lower = requested_key.lower()
        for attr_key, attr_val in pairs:
            if str(attr_key).strip().lower() != key_lower:
                continue
            return str(attr_val).strip()
        return None

    def _discover_source_keys(self) -> List[str]:
        keys = set()
        keys.update(self._discover_jattr_keys())
        keys.update(self._discover_attribute_keys())
        return sorted(keys)

    def _discover_jattr_keys(self) -> set:
        if "jattr" not in self.metadata_df.columns:
            return set()
        keys = set()
        for raw in self.metadata_df["jattr"].dropna():
            parsed = self._parse_json_dict(raw)
            if parsed is not None:
                keys.update(str(k) for k in parsed.keys())
        return keys

    def _discover_attribute_keys(self) -> set:
        if "attributes" not in self.metadata_df.columns:
            return set()
        keys = set()
        for raw in self.metadata_df["attributes"].dropna().astype(str):
            keys.update(str(k).strip() for k, _ in re.findall(r"k=([^,]+), v=([^}]+)", raw))
        return keys

    def calculate_abundance(self, rank: str, taxon: str) -> pd.DataFrame:
        plot_df = self._abundance_wide(rank, taxon)
        if not self._is_wide_mode:
            plot_df = self._abundance_long(rank, taxon)
        plot_df["relative_abundance"] = self._safe_ratio(plot_df)
        return plot_df.reset_index().rename(columns={"acc": "sample"})

    def _abundance_wide(self, rank: str, taxon: str) -> pd.DataFrame:
        self._ensure_sample_taxa_matrix()
        taxon_keys = self._taxon_keys(rank, taxon)
        superkingdom_keys = self._rank_keys("superkingdom")
        return self._combine_counts_from_matrix(superkingdom_keys, taxon_keys)

    def _abundance_long(self, rank: str, taxon: str) -> pd.DataFrame:
        rank_df = self.taxonomy_df[self.taxonomy_df["rank"].str.lower() == rank.lower()]
        taxon_counts = self._long_taxon_counts(rank_df, taxon)
        total = self._long_superkingdom_total_counts()
        all_samples = self.taxonomy_df[["acc"]].drop_duplicates().set_index("acc")
        return all_samples.join(total).join(taxon_counts).fillna(0)

    def _ensure_sample_taxa_matrix(self):
        if not self._is_wide_mode:
            return
        if self.sample_taxa_matrix is not None:
            return
        self._log("Preparing abundance matrix for plotting...")
        matrix = self._abundance_source[["acc"] + self._taxon_cols].set_index("acc")
        matrix = self._coerce_object_columns(matrix)
        self.sample_taxa_matrix = matrix.fillna(0)

    def _coerce_object_columns(self, matrix: pd.DataFrame) -> pd.DataFrame:
        obj_cols = matrix.select_dtypes(include=["object"]).columns
        if len(obj_cols) == 0:
            return matrix
        matrix.loc[:, obj_cols] = matrix.loc[:, obj_cols].apply(pd.to_numeric, errors="coerce")
        return matrix

    def _rank_keys(self, rank: str) -> List[str]:
        keys = self.taxon_lookup_df[self.taxon_lookup_df["rank"].astype(str).str.lower() == rank.lower()]["taxon_key"]
        available = set(self.sample_taxa_matrix.columns)
        return [k for k in keys.astype(str).tolist() if k in available]

    def _taxon_keys(self, rank: str, taxon: str) -> List[str]:
        mask = self.taxon_lookup_df["rank"].astype(str).str.lower() == rank.lower()
        keys = self.taxon_lookup_df[mask & (self.taxon_lookup_df["name"] == taxon)]["taxon_key"]
        available = set(self.sample_taxa_matrix.columns)
        return [k for k in keys.astype(str).tolist() if k in available]

    def _combine_counts_from_matrix(self, total_keys: List[str], taxon_keys: List[str]) -> pd.DataFrame:
        total = self._matrix_sum(total_keys, "total_sample_reads")
        taxon_counts = self._matrix_sum(taxon_keys, "taxon_reads")
        all_samples = pd.DataFrame(index=self.sample_taxa_matrix.index)
        return all_samples.join(total).join(taxon_counts).fillna(0)

    def _matrix_sum(self, keys: List[str], name: str) -> pd.Series:
        if keys:
            return self.sample_taxa_matrix[keys].sum(axis=1).rename(name)
        return pd.Series(0, index=self.sample_taxa_matrix.index, name=name)

    def _long_taxon_counts(self, rank_df: pd.DataFrame, taxon: str) -> pd.Series:
        taxon_df = rank_df[rank_df["name"] == taxon]
        if taxon_df["acc"].duplicated().any():
            raise ValueError(f"Expected at most one row per sample for taxon='{taxon}', but found duplicates.")
        return taxon_df.set_index("acc")["total_count"].rename("taxon_reads")

    def _long_superkingdom_total_counts(self) -> pd.Series:
        superkingdom_df = self.taxonomy_df[self.taxonomy_df["rank"].str.lower() == "superkingdom"]
        return superkingdom_df.groupby("acc")["total_count"].sum().rename("total_sample_reads")

    def _safe_ratio(self, plot_df: pd.DataFrame) -> pd.Series:
        numerator = plot_df["taxon_reads"]
        denominator = plot_df["total_sample_reads"]
        return np.where(denominator > 0, numerator / denominator, 0.0)

    def build_plot_df(self, rank: str, taxon: str, group: Optional[str], source_keys: List[str]):
        df_plot = self.calculate_abundance(rank, taxon)
        df_plot, valid_extras = self._merge_selected_metadata(df_plot, group)
        df_plot = self._merge_source_keys(df_plot, source_keys)
        return df_plot, valid_extras

    def _merge_selected_metadata(self, df_plot: pd.DataFrame, group: Optional[str]):
        selected = ["bioproject"] if "bioproject" in self.metadata_df.columns else []
        if group and group not in selected:
            selected.append(group)
        valid_extras = [col for col in selected if col in self.metadata_df.columns]
        if not valid_extras:
            return df_plot, valid_extras
        meta_df = self.metadata_df[["acc"] + valid_extras].drop_duplicates().rename(columns={"acc": "sample"})
        return df_plot.merge(meta_df, on="sample", how="left"), valid_extras

    def _merge_source_keys(self, df_plot: pd.DataFrame, source_keys: List[str]) -> pd.DataFrame:
        if not source_keys:
            return df_plot
        source_df = self._source_keys_dataframe(source_keys)
        if source_df is None:
            return df_plot
        return df_plot.merge(source_df, on="sample", how="left")

    def _source_keys_dataframe(self, source_keys: List[str]) -> Optional[pd.DataFrame]:
        base_cols = [c for c in ["acc", "jattr", "attributes"] if c in self.metadata_df.columns]
        for key in source_keys:
            if key in self.metadata_df.columns and key not in base_cols:
                base_cols.append(key)
        if not base_cols:
            return None
        source_df = self.metadata_df[base_cols].drop_duplicates(subset=["acc"]).copy()
        for key in source_keys:
            source_df[key] = source_df.apply(lambda row: self.extract_source_key_value(row, key), axis=1)
        return source_df[["acc"] + source_keys].rename(columns={"acc": "sample"})

    def group_summary_rows(self, df_plot: pd.DataFrame, group: Optional[str]) -> List[dict]:
        if not group:
            return []
        return [self.summary_row(str(name), subset) for name, subset in df_plot.groupby(group)]

    def summary_row(self, cohort_name: str, subset: pd.DataFrame) -> dict:
        total_n = len(subset)
        zero_reads = (subset["taxon_reads"] == 0).sum()
        prevalence = 0 if total_n == 0 else (total_n - zero_reads) / total_n
        mean_rel = f"{subset['relative_abundance'].mean():.6%}"
        return {
            "Cohort": cohort_name,
            "Total Samples (N)": total_n,
            "Samples with 0 Reads": zero_reads,
            "Samples with Non-Zero Reads (%)": f"{prevalence:.2%}",
            "Mean Rel. Abundance": mean_rel,
        }

    def prepare_table(self, df_plot: pd.DataFrame, group: Optional[str], valid_extras: List[str], source_keys: List[str]):
        sorted_df = self._sort_table_df(df_plot, group)
        final_cols = ["sample"] + valid_extras + source_keys + ["total_sample_reads", "taxon_reads", "relative_abundance"]
        table_df = sorted_df[final_cols].copy()
        table_df = self._rename_table_columns(table_df)
        table_df["Total Sample Reads"] = table_df["Total Sample Reads"].astype(int)
        table_df["Taxon Reads"] = table_df["Taxon Reads"].astype(int)
        return table_df

    def _sort_table_df(self, df_plot: pd.DataFrame, group: Optional[str]) -> pd.DataFrame:
        if group:
            return df_plot.sort_values(by=[group, "taxon_reads"], ascending=[True, False])
        return df_plot.sort_values(by=["taxon_reads"], ascending=[False])

    def _rename_table_columns(self, table_df: pd.DataFrame) -> pd.DataFrame:
        mapping = {
            "sample": "Sample ID (SRR)",
            "total_sample_reads": "Total Sample Reads",
            "taxon_reads": "Taxon Reads",
            "relative_abundance": "Relative Abundance",
            "bioproject": "BioProject",
        }
        return table_df.rename(columns=mapping)

