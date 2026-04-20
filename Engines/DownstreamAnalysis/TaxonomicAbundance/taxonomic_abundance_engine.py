import pandas as pd
import numpy as np
import plotly.express as px
import time
import json
import re
from pathlib import Path
from ipywidgets import Dropdown, VBox, HBox, Button, Output, HTML, Layout
from IPython.display import display, clear_output
from typing import Optional

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None

from Common.contracts.sra_schema import SRAMetadataSchema

# Base columns defined by the metadata schema — anything beyond these is a mapped field
_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())


class TaxonomicAbundanceEngine:
    _ACTIVE_UIS = []

    """
    Manager for interactive taxonomic abundance analysis.
    Calculates relative abundance, visualizes distribution, generates
    prevalence summaries, and allows CSV exporting.
    """

    def __init__(
        self,
        taxonomy_df: pd.DataFrame = None,
        metadata_df: pd.DataFrame = None,
        abundance_metadata_matrix: pd.DataFrame = None,
        taxon_lookup_df: pd.DataFrame = None,
        metadata_cols: list = None,
        logger=None,
    ):
        """
        Args:
            taxonomy_df: Taxonomy DataFrame (many rows per acc, one per detected taxon).
            metadata_df: Enriched metadata DataFrame (1 row per acc), including any
                         mapped fields added by SRAProcessor.
        """
        self._is_wide_mode = abundance_metadata_matrix is not None
        self._log = logger or print

        if self._is_wide_mode:
            if taxon_lookup_df is None:
                raise ValueError("taxon_lookup_df is required when using analysis_wide_df")

            if metadata_cols is None and metadata_df is not None:
                metadata_cols = list(metadata_df.columns)
            if metadata_cols is None:
                metadata_cols = [c for c in abundance_metadata_matrix.columns if c in _BASE_METADATA_COLS]

            missing_meta = [c for c in metadata_cols if c not in abundance_metadata_matrix.columns]
            if missing_meta:
                raise ValueError(f"analysis_wide_df is missing metadata columns: {missing_meta}")

            self.metadata_df = abundance_metadata_matrix[metadata_cols].copy()
            self.taxon_lookup_df = taxon_lookup_df.copy()

            required_lookup = {'taxon_key', 'rank', 'name'}
            missing_lookup = required_lookup - set(self.taxon_lookup_df.columns)
            if missing_lookup:
                raise ValueError(f"taxon_lookup_df is missing required columns: {missing_lookup}")

            self.taxon_lookup_df['taxon_key'] = self.taxon_lookup_df['taxon_key'].astype(str)
            taxon_key_set = set(self.taxon_lookup_df['taxon_key'])
            self._taxon_cols = [c for c in abundance_metadata_matrix.columns if c in taxon_key_set]
            self._abundance_source = abundance_metadata_matrix
            # Lazily materialize this heavy matrix on first calculation request.
            self.sample_taxa_matrix = None

            self.taxonomy_df = None
        else:
            if taxonomy_df is None or metadata_df is None:
                raise ValueError("taxonomy_df and metadata_df are required in long-format mode")
            self.taxonomy_df = taxonomy_df
            self.metadata_df = metadata_df
            self.taxon_lookup_df = None
            self.sample_taxa_matrix = None
            self._taxon_cols = []
            self._abundance_source = None

        # Identify mapped columns in metadata for grouping
        mapped_cols = [c for c in self.metadata_df.columns if c not in _BASE_METADATA_COLS]
        self.cat_cols = [c for c in mapped_cols if pd.api.types.is_string_dtype(self.metadata_df[c])]

        # Extract available ranks from taxonomy, keeping standard order
        standard_order = ['superkingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
        if self._is_wide_mode:
            existing_ranks = self.taxon_lookup_df['rank'].astype(str).str.lower().dropna().unique()
        else:
            existing_ranks = taxonomy_df['rank'].str.lower().dropna().unique()
        self.available_ranks = [r for r in standard_order if r in existing_ranks]

        self._output_area = Output()
        self._ui: Optional[VBox] = None
        self._plot_btn: Optional[Button] = None
        self._export_btn: Optional[Button] = None
        self._plot_click_cb = None
        self._export_click_cb = None
        self._is_plotting = False
        self._last_plot_click_ts = 0.0
        self._plot_debounce_seconds = 0.75
        self._last_render_signature = None
        self._controls_dirty = True

        # State variables for exporting
        self.current_export_df = None
        self.current_taxon_name = "taxon"

        # Optional metadata columns users can append to table/export output.
        self._source_keys = self._discover_source_keys()

    def _extract_source_key_value(self, row: pd.Series, key: str) -> Optional[str]:
        """Extract a source key value from jattr/attributes for a single sample row."""
        requested_key = str(key).strip()
        requested_key_lower = requested_key.lower()

        # Prefer an existing concrete column when available.
        if requested_key in row.index:
            direct_value = row.get(requested_key)
            if pd.notna(direct_value):
                return str(direct_value)
        else:
            for col in row.index:
                if str(col).strip().lower() == requested_key_lower:
                    direct_value = row.get(col)
                    if pd.notna(direct_value):
                        return str(direct_value)
                    break

        value = None

        if 'jattr' in row and pd.notna(row.get('jattr')):
            try:
                jattr_data = json.loads(row['jattr'])
                if isinstance(jattr_data, dict):
                    raw = None
                    if requested_key in jattr_data:
                        raw = jattr_data[requested_key]
                    else:
                        for k, v in jattr_data.items():
                            if str(k).strip().lower() == requested_key_lower:
                                raw = v
                                break

                    if raw is not None:
                        value = " ".join(raw) if isinstance(raw, list) else str(raw)
            except (json.JSONDecodeError, TypeError):
                pass

        if value is None and 'attributes' in row and pd.notna(row.get('attributes')):
            try:
                for attr_key, attr_val in re.findall(r"k\s*=\s*([^,]+),\s*v\s*=\s*([^}]+)", str(row['attributes'])):
                    if str(attr_key).strip().lower() == requested_key_lower:
                        value = str(attr_val).strip()
                        break
            except Exception:
                pass

        return value

    def _discover_source_keys(self) -> list:
        """Discover source keys present in jattr/attributes columns."""
        keys = set()

        if 'jattr' in self.metadata_df.columns:
            for raw in self.metadata_df['jattr'].dropna():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        keys.update(str(k) for k in parsed.keys())
                except (json.JSONDecodeError, TypeError):
                    continue

        if 'attributes' in self.metadata_df.columns:
            for raw in self.metadata_df['attributes'].dropna().astype(str):
                for key, _ in re.findall(r"k=([^,]+), v=([^}]+)", raw):
                    keys.add(str(key).strip())

        return sorted(keys)

    def _ensure_sample_taxa_matrix(self):
        """Build sample x taxa matrix only when needed in wide mode."""
        if not self._is_wide_mode:
            return
        if self.sample_taxa_matrix is not None:
            return

        self._log("⏳ Preparing abundance matrix for plotting...")
        matrix = self._abundance_source[['acc'] + self._taxon_cols].set_index('acc')

        # Avoid expensive conversion on already numeric columns.
        obj_cols = matrix.select_dtypes(include=['object']).columns
        if len(obj_cols) > 0:
            matrix.loc[:, obj_cols] = matrix.loc[:, obj_cols].apply(pd.to_numeric, errors='coerce')

        self.sample_taxa_matrix = matrix.fillna(0)


    def _calculate_rank_relative_abundance(self, rank: str, taxon: str) -> pd.DataFrame:
        """Calculates abundance normalized within the selected taxonomic rank.
        Denominator: sum of counts at the selected rank in each sample.
        This is kept for future use when rank-normalized abundance is desired.
        """
        if self._is_wide_mode:
            self._ensure_sample_taxa_matrix()
            rank_keys = self.taxon_lookup_df[
                self.taxon_lookup_df['rank'].astype(str).str.lower() == rank.lower()
            ]['taxon_key'].astype(str).tolist()
            taxon_keys = self.taxon_lookup_df[
                (self.taxon_lookup_df['rank'].astype(str).str.lower() == rank.lower())
                & (self.taxon_lookup_df['name'] == taxon)
            ]['taxon_key'].astype(str).tolist()

            rank_keys = [k for k in rank_keys if k in self.sample_taxa_matrix.columns]
            taxon_keys = [k for k in taxon_keys if k in self.sample_taxa_matrix.columns]

            total_counts = self.sample_taxa_matrix[rank_keys].sum(axis=1).rename('total_sample_reads') if rank_keys else pd.Series(0, index=self.sample_taxa_matrix.index, name='total_sample_reads')
            taxon_counts = self.sample_taxa_matrix[taxon_keys].sum(axis=1).rename('taxon_reads') if taxon_keys else pd.Series(0, index=self.sample_taxa_matrix.index, name='taxon_reads')

            all_samples = pd.DataFrame(index=self.sample_taxa_matrix.index)
            plot_df = all_samples.join(total_counts).join(taxon_counts).fillna(0)
        else:
            rank_df = self.taxonomy_df[self.taxonomy_df['rank'].str.lower() == rank.lower()]
            total_counts = rank_df.groupby('acc')['total_count'].sum().rename('total_sample_reads')

            taxon_df = rank_df[rank_df['name'] == taxon]
            if taxon_df['acc'].duplicated().any():
                raise ValueError(
                    f"Expected at most one row per sample for rank='{rank}', taxon='{taxon}', "
                    "but found duplicates."
                )
            taxon_counts = taxon_df.set_index('acc')['total_count'].rename('taxon_reads')

            all_samples = self.taxonomy_df[['acc']].drop_duplicates().set_index('acc')
            plot_df = all_samples.join(total_counts).join(taxon_counts).fillna(0)

        plot_df['relative_abundance_within_rank'] = np.where(
            plot_df['total_sample_reads'] > 0,
            plot_df['taxon_reads'] / plot_df['total_sample_reads'],
            0.0
        )

        plot_df = plot_df.reset_index().rename(columns={'acc': 'sample'})

        return plot_df

    def _calculate_abundance(self, rank: str, taxon: str) -> pd.DataFrame:
        """Calculates per-sample relative abundance of a chosen taxon.
        Denominator: total reads in the sample, computed as the sum of
        `total_count` across superkingdom rows for each sample.
        Numerator: total_count of the selected taxon at the selected rank.
        """
        if self._is_wide_mode:
            self._ensure_sample_taxa_matrix()
            taxon_keys = self.taxon_lookup_df[
                (self.taxon_lookup_df['rank'].astype(str).str.lower() == rank.lower())
                & (self.taxon_lookup_df['name'] == taxon)
            ]['taxon_key'].astype(str).tolist()
            superkingdom_keys = self.taxon_lookup_df[
                self.taxon_lookup_df['rank'].astype(str).str.lower() == 'superkingdom'
            ]['taxon_key'].astype(str).tolist()

            taxon_keys = [k for k in taxon_keys if k in self.sample_taxa_matrix.columns]
            superkingdom_keys = [k for k in superkingdom_keys if k in self.sample_taxa_matrix.columns]

            taxon_counts = self.sample_taxa_matrix[taxon_keys].sum(axis=1).rename('taxon_reads') if taxon_keys else pd.Series(0, index=self.sample_taxa_matrix.index, name='taxon_reads')
            total_counts = self.sample_taxa_matrix[superkingdom_keys].sum(axis=1).rename('total_sample_reads') if superkingdom_keys else pd.Series(0, index=self.sample_taxa_matrix.index, name='total_sample_reads')

            all_samples = pd.DataFrame(index=self.sample_taxa_matrix.index)
            plot_df = all_samples.join(total_counts).join(taxon_counts).fillna(0)
        else:
            rank_df = self.taxonomy_df[self.taxonomy_df['rank'].str.lower() == rank.lower()]
            taxon_df = rank_df[rank_df['name'] == taxon]
            if taxon_df['acc'].duplicated().any():
                raise ValueError(
                    f"Expected at most one row per sample for rank='{rank}', taxon='{taxon}', "
                    "but found duplicates."
                )
            taxon_counts = taxon_df.set_index('acc')['total_count'].rename('taxon_reads')

            superkingdom_df = self.taxonomy_df[
                self.taxonomy_df['rank'].str.lower() == 'superkingdom'
            ]
            total_counts = superkingdom_df.groupby('acc')['total_count'].sum().rename('total_sample_reads')

            all_samples = self.taxonomy_df[['acc']].drop_duplicates().set_index('acc')
            plot_df = all_samples.join(total_counts).join(taxon_counts).fillna(0)

        plot_df['relative_abundance'] = np.where(
            plot_df['total_sample_reads'] > 0,
            plot_df['taxon_reads'] / plot_df['total_sample_reads'],
            0.0
        )

        plot_df = plot_df.reset_index().rename(columns={'acc': 'sample'})

        return plot_df

    def _create_ui(self) -> VBox:
        # Recreate output widget on each UI build to avoid stale multi-view output duplication.
        self._output_area = Output()

        rank_dropdown = Dropdown(
            options=self.available_ranks,
            value=self.available_ranks[-1] if self.available_ranks else None,
            description='① Rank:', layout={'width': '250px'}
        )
        taxon_dropdown = Dropdown(
            options=[], description='② Taxon:', layout={'width': '300px'}
        )
        group_dropdown = Dropdown(
            options=['None'] + self.cat_cols,
            value='None', description='③ Group By:', layout={'width': '250px'}
        )

        selected_source_keys = []
        source_key_dropdown = Dropdown(
            options=[('Select source key...', '')] + [(k, k) for k in self._source_keys],
            value='',
            description='④ Add Key:',
            layout=Layout(width='420px')
        )
        remove_source_key_dropdown = Dropdown(
            options=[('Selected key...', '')],
            value='',
            description='⑤ Remove:',
            layout=Layout(width='420px')
        )
        add_source_key_btn = Button(description='Add', button_style='info', layout=Layout(width='70px'))
        remove_source_key_btn = Button(description='Remove', button_style='warning', layout=Layout(width='80px'))
        clear_source_keys_btn = Button(description='Clear', button_style='', layout=Layout(width='70px'))
        selected_keys_preview = HTML("<span style='color:#666;'>Selected source keys: none</span>")

        def _refresh_selected_keys_controls():
            if selected_source_keys:
                chips = " ".join(
                    [f"<code style='padding:2px 6px;background:#eef;border-radius:3px;'>{k}</code>" for k in selected_source_keys]
                )
                selected_keys_preview.value = f"<span style='color:#333;'>Selected source keys:</span> {chips}"
                remove_source_key_dropdown.options = [('Selected key...', '')] + [(k, k) for k in selected_source_keys]
            else:
                selected_keys_preview.value = "<span style='color:#666;'>Selected source keys: none</span>"
                remove_source_key_dropdown.options = [('Selected key...', '')]

        def _on_add_source_key(*_):
            key = source_key_dropdown.value
            if key and key not in selected_source_keys:
                selected_source_keys.append(key)
                _refresh_selected_keys_controls()
                self._controls_dirty = True

        def _on_remove_source_key(*_):
            key = remove_source_key_dropdown.value
            if key and key in selected_source_keys:
                selected_source_keys.remove(key)
                remove_source_key_dropdown.value = ''
                _refresh_selected_keys_controls()
                self._controls_dirty = True

        def _on_clear_source_keys(*_):
            selected_source_keys.clear()
            remove_source_key_dropdown.value = ''
            _refresh_selected_keys_controls()
            self._controls_dirty = True

        add_source_key_btn.on_click(_on_add_source_key)
        remove_source_key_btn.on_click(_on_remove_source_key)
        clear_source_keys_btn.on_click(_on_clear_source_keys)
        _refresh_selected_keys_controls()
        
        plot_btn = Button(description='Plot Abundance', button_style='primary', icon='bar-chart')
        export_btn = Button(description='Export Raw Data', button_style='success', icon='download')

        def update_taxa_options(*args):
            if not rank_dropdown.value:
                return
            # FIXED: Now correctly points to self.taxonomy_df instead of self.df
            if self._is_wide_mode:
                rank_df = self.taxon_lookup_df[
                    self.taxon_lookup_df['rank'].astype(str).str.lower() == rank_dropdown.value.lower()
                ]
                taxa_list = sorted(rank_df['name'].dropna().astype(str).unique())
            else:
                rank_df = self.taxonomy_df[self.taxonomy_df['rank'].str.lower() == rank_dropdown.value.lower()]
                taxa_list = sorted(rank_df['name'].dropna().astype(str).unique())
            taxon_dropdown.options = taxa_list
            if taxa_list:
                taxon_dropdown.value = taxa_list[0]
                
        rank_dropdown.observe(update_taxa_options, names='value')
        rank_dropdown.observe(lambda *_: setattr(self, '_controls_dirty', True), names='value')
        taxon_dropdown.observe(lambda *_: setattr(self, '_controls_dirty', True), names='value')
        group_dropdown.observe(lambda *_: setattr(self, '_controls_dirty', True), names='value')
        update_taxa_options()

        def on_export_click(*args):
            if self.current_export_df is not None:
                default_filename = f"{self.current_taxon_name.replace(' ', '_')}_abundance.csv"
                save_path = ""

                if tk is not None and filedialog is not None:
                    root = tk.Tk()
                    root.withdraw()
                    root.attributes("-topmost", True)
                    save_path = filedialog.asksaveasfilename(
                        title="Save Raw Abundance Data",
                        initialdir=str(Path.cwd()),
                        initialfile=default_filename,
                        defaultextension=".csv",
                        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                    )
                    root.destroy()
                else:
                    with self._output_area:
                        print("ℹ️ Native file dialog unavailable (_tkinter missing).")
                        print(f"Enter a save path, or press Enter to use: {default_filename}")
                    typed_path = input("Save CSV path: ").strip()
                    save_path = typed_path or default_filename

                if not save_path:
                    with self._output_area:
                        print("ℹ️ Export canceled.")
                    return

                self.current_export_df.to_csv(save_path, index=False)
                with self._output_area:
                    print(f"✅ Successfully saved raw data to: {save_path}")
            else:
                with self._output_area:
                    print("⚠️ Please generate a plot before exporting.")
                    
        if self._export_btn is not None and self._export_click_cb is not None:
            self._export_btn.on_click(self._export_click_cb, remove=True)
        export_btn.on_click(on_export_click)
        self._export_btn = export_btn
        self._export_click_cb = on_export_click

        def on_plot_click(*args):
            now = time.monotonic()
            if (now - self._last_plot_click_ts) < self._plot_debounce_seconds:
                return
            self._last_plot_click_ts = now

            if self._is_plotting:
                return

            self._is_plotting = True
            plot_btn.disabled = True
            with self._output_area:
                try:
                    clear_output(wait=True)
                    r = rank_dropdown.value
                    t = taxon_dropdown.value
                    g = group_dropdown.value if group_dropdown.value != 'None' else None
                    selected_source_keys_for_render = list(selected_source_keys)

                    # Keep the baseline BioProject column and append selected source keys.
                    selected_meta_cols = ['bioproject'] if 'bioproject' in self.metadata_df.columns else []

                    # Protect against duplicate callback registration causing repeated renders.
                    render_signature = (r, t, g, tuple(selected_source_keys_for_render))
                    if (not self._controls_dirty) and self._last_render_signature == render_signature:
                        return
                    
                    if not r or not t:
                        print("⚠️ Please select both a rank and a taxon.")
                        return
                        
                    # 1. Calculate base metrics
                    df_plot = self._calculate_abundance(r, t)
                    
                    # 2. Merge metadata dynamically for plotting and tables
                    extra_columns = []
                    for col in selected_meta_cols:
                        if col not in extra_columns:
                            extra_columns.append(col)
                    if g and g not in extra_columns:
                        extra_columns.append(g)
                        
                    # FIXED: Now checks valid extras against self.metadata_df
                    valid_extras = [col for col in extra_columns if col in self.metadata_df.columns]
                    if valid_extras:
                        # FIXED: Now merges from self.metadata_df
                        meta_df = self.metadata_df[['acc'] + valid_extras].drop_duplicates().rename(columns={'acc': 'sample'})
                        df_plot = df_plot.merge(meta_df, on='sample', how='left')

                    # Append selected source keys as additional columns for table/export.
                    if selected_source_keys_for_render:
                        source_base_cols = [c for c in ['acc', 'jattr', 'attributes'] if c in self.metadata_df.columns]
                        for key in selected_source_keys_for_render:
                            if key in self.metadata_df.columns and key not in source_base_cols:
                                source_base_cols.append(key)
                        if source_base_cols:
                            source_df = self.metadata_df[source_base_cols].drop_duplicates(subset=['acc']).copy()
                            for key in selected_source_keys_for_render:
                                source_df[key] = source_df.apply(lambda row: self._extract_source_key_value(row, key), axis=1)
                            source_df = source_df[['acc'] + selected_source_keys_for_render].rename(columns={'acc': 'sample'})
                            df_plot = df_plot.merge(source_df, on='sample', how='left')
                    
                    # 3. Plotting Logic
                    title = f"Relative Abundance of <i>{t}</i> ({r.title()})"
                    max_val = df_plot['relative_abundance'].max()
                    
                    if max_val == 0: tick_fmt = ".2%"
                    elif max_val < 0.0001: tick_fmt = ".4e"
                    elif max_val < 0.01: tick_fmt = ".4%"
                    else: tick_fmt = ".2%"
                    
                    if g:
                        plot_df_sorted = df_plot.sort_values(g).copy()
                        
                        # 1. Count how many samples are in each group
                        group_counts = plot_df_sorted[g].value_counts().to_dict()
                        
                        # 2. Create a new label combining the name and the 'n'
                        plot_df_sorted['plot_label'] = plot_df_sorted[g].apply(
                            lambda x: f"{x}<br>(n={group_counts.get(x, 0)})"
                        )
                        
                        # 3. Use the new label for the X-axis and color
                        fig = px.box(
                            plot_df_sorted, x='plot_label', y='relative_abundance', color='plot_label',
                            points='all', hover_data=['sample', 'taxon_reads', 'total_sample_reads'],
                            title=title, template='plotly_white', height=500,
                            labels={'plot_label': g} # Keeps the legend/axis titles looking clean
                        )
                    else:
                        plot_df_sorted = df_plot.sort_values('relative_abundance', ascending=False)
                        fig = px.bar(
                            plot_df_sorted, x='sample', y='relative_abundance',
                            hover_data=['taxon_reads', 'total_sample_reads'],
                            title=title, template='plotly_white', height=500
                        )
                        fig.update_xaxes(showticklabels=True, tickangle=-45, type='category', title_text="Sample ID")
                        
                    fig.update_layout(yaxis_title="Relative Abundance", yaxis_tickformat=tick_fmt)
                    fig.show()

                    # =========================================================
                    # 📊 PREVALENCE SUMMARY CALCULATIONS
                    # =========================================================
                    def generate_summary_row(name, subset):
                        total_n = len(subset)
                        zero_reads = (subset['taxon_reads'] == 0).sum()
                        prevalence = (total_n - zero_reads) / total_n if total_n > 0 else 0
                        return {
                            'Cohort': name,
                            'Total Samples (N)': total_n,
                            'Samples with 0 Reads': zero_reads,
                            'Samples with Non-Zero Reads (%)': f"{prevalence:.2%}",
                            'Mean Rel. Abundance': f"{subset['relative_abundance'].mean():.6%}"
                        }

                    summary_rows = []
                    if g:
                        # Calculate per group
                        for group_name, group_data in df_plot.groupby(g):
                            summary_rows.append(generate_summary_row(str(group_name), group_data))
                    
                    # Calculate for ALL data
                    summary_rows.append(generate_summary_row('All Combined', df_plot))
                    
                    summary_df = pd.DataFrame(summary_rows)
                    print("\n📈 PREVALENCE & SUMMARY STATISTICS:")
                    display(summary_df)


                    # =========================================================
                    # 📋 RAW DATA TABLE PREPARATION
                    # =========================================================
                    # Sort exactly how you want it: Group first (alphabetical), then Taxon Reads (descending)
                    if g:
                        df_plot = df_plot.sort_values(by=[g, 'taxon_reads'], ascending=[True, False])
                    else:
                        df_plot = df_plot.sort_values(by=['taxon_reads'], ascending=[False])

                    final_cols = ['sample'] + valid_extras + selected_source_keys_for_render + ['total_sample_reads', 'taxon_reads', 'relative_abundance']
                    table_df = df_plot[final_cols].copy()
                    
                    table_df.rename(columns={
                        'sample': 'Sample ID (SRR)',
                        'total_sample_reads': 'Total Sample Reads',
                        'taxon_reads': 'Taxon Reads',
                        'relative_abundance': 'Relative Abundance',
                        'bioproject': 'BioProject'
                    }, inplace=True)
                    
                    table_df['Total Sample Reads'] = table_df['Total Sample Reads'].astype(int)
                    table_df['Taxon Reads'] = table_df['Taxon Reads'].astype(int)
                    
                    # Save raw numbers for CSV export
                    self.current_export_df = table_df.copy()
                    self.current_taxon_name = t
                    
                    # Format relative abundance for the visual table display only
                    display_df = table_df.copy()
                    display_df['Relative Abundance'] = display_df['Relative Abundance'].apply(lambda x: f"{x:.6%}")
                    
                    print("\n📋 RAW DATA TABLE:")
                    display(display_df)
                    self._last_render_signature = render_signature
                    self._controls_dirty = False
                finally:
                    self._is_plotting = False
                    plot_btn.disabled = False

        if self._plot_btn is not None and self._plot_click_cb is not None:
            self._plot_btn.on_click(self._plot_click_cb, remove=True)
        plot_btn.on_click(on_plot_click)
        self._plot_btn = plot_btn
        self._plot_click_cb = on_plot_click

        header = HTML(
            "<div style='background: #4A90E2; padding: 15px; border-radius: 8px; margin-bottom: 15px;'>"
            "<h3 style='color: white; margin: 0;'>🔬 Single Taxon Abundance</h3>"
            "<p style='color: #E2E8F0; margin: 5px 0 0 0; font-size: 13px;'>"
            "Select a specific taxonomy to view its relative abundance across samples.</p></div>"
        )
        
        controls = HBox([rank_dropdown, taxon_dropdown, group_dropdown], layout=Layout(margin='0 0 10px 0'))
        metadata_controls = VBox([
            HBox([source_key_dropdown, add_source_key_btn], layout=Layout(margin='0 0 6px 0', align_items='center')),
            HBox([remove_source_key_dropdown, remove_source_key_btn, clear_source_keys_btn], layout=Layout(margin='0 0 6px 0', align_items='center')),
            selected_keys_preview,
        ], layout=Layout(margin='0 0 10px 0'))
        buttons = HBox([plot_btn, export_btn], layout=Layout(margin='0 0 15px 0', align_items='center'))
        
        ui = VBox([header, controls, metadata_controls, buttons, self._output_area])
        self._ui = ui
        return ui

    def run(self):
        if not hasattr(TaxonomicAbundanceEngine, '_ACTIVE_UIS'):
            TaxonomicAbundanceEngine._ACTIVE_UIS = []

        # Ensure only one taxonomic abundance UI is alive at a time across instances.
        for ui in list(TaxonomicAbundanceEngine._ACTIVE_UIS):
            try:
                ui.close()
            except Exception:
                pass
        TaxonomicAbundanceEngine._ACTIVE_UIS.clear()

        if self._ui is not None:
            self._ui.close()
            self._ui = None
        ui = self._create_ui()
        TaxonomicAbundanceEngine._ACTIVE_UIS.append(ui)
        display(ui)


# Canonical iDesign name for this engine.
TaxonomicAbundanceEngine = TaxonomicAbundanceEngine