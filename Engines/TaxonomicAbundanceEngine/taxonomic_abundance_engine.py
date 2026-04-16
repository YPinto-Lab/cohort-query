import pandas as pd
import numpy as np
import plotly.express as px
import time
from ipywidgets import Dropdown, VBox, HBox, Button, Output, HTML, Layout
from IPython.display import display, clear_output
from typing import Optional

from Common.contracts.sra_schema import SRAMetadataSchema

# Base columns defined by the metadata schema — anything beyond these is a mapped field
_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())


class TaxonomicAbundanceManager:
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

        # State variables for exporting
        self.current_export_df = None
        self.current_taxon_name = "taxon"

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
        update_taxa_options()

        def on_export_click(*args):
            if self.current_export_df is not None:
                filename = f"{self.current_taxon_name.replace(' ', '_')}_abundance.csv"
                self.current_export_df.to_csv(filename, index=False)
                with self._output_area:
                    print(f"✅ Successfully saved raw data to: {filename}")
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
            with self._output_area:
                try:
                    clear_output(wait=True)
                    r = rank_dropdown.value
                    t = taxon_dropdown.value
                    g = group_dropdown.value if group_dropdown.value != 'None' else None
                    
                    if not r or not t:
                        print("⚠️ Please select both a rank and a taxon.")
                        return
                        
                    # 1. Calculate base metrics
                    df_plot = self._calculate_abundance(r, t)
                    
                    # 2. Merge metadata dynamically for plotting and tables
                    extra_columns = ['bioproject']
                    if g and g not in extra_columns:
                        extra_columns.append(g)
                        
                    # FIXED: Now checks valid extras against self.metadata_df
                    valid_extras = [col for col in extra_columns if col in self.metadata_df.columns]
                    if valid_extras:
                        # FIXED: Now merges from self.metadata_df
                        meta_df = self.metadata_df[['acc'] + valid_extras].drop_duplicates().rename(columns={'acc': 'sample'})
                        df_plot = df_plot.merge(meta_df, on='sample', how='left')
                    
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

                    final_cols = ['sample'] + valid_extras + ['total_sample_reads', 'taxon_reads', 'relative_abundance']
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
                finally:
                    self._is_plotting = False

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
        buttons = HBox([plot_btn, export_btn], layout=Layout(margin='0 0 15px 0', align_items='center'))
        
        ui = VBox([header, controls, buttons, self._output_area])
        self._ui = ui
        return ui

    def run(self):
        if self._ui is not None:
            self._ui.close()
            self._ui = None
        display(self._create_ui())


# Canonical iDesign name for this engine.
TaxonomicAbundanceEngine = TaxonomicAbundanceManager