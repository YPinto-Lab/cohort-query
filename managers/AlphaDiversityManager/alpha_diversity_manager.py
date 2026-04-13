"""
Alpha Diversity Analysis Manager.

This module provides an interactive UI for computing and visualizing alpha diversity
metrics (Richness & Shannon Index) with taxonomic filtering capabilities.

Following the iDesign architecture pattern, this manager orchestrates the presentation
layer for alpha diversity analysis, coordinating with the TaxonomyAccessor for
taxonomic data operations.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from ipywidgets import Dropdown, VBox, HBox, Output, HTML, Button, Layout, Checkbox
from IPython.display import display, clear_output
from typing import Dict, List, Optional, Set

from Accessors.TaxonomyAccessor import TaxonomyAccessor
from common.contracts.sra_schema import SRAMetadataSchema


# Standard taxonomic ranks (most commonly used for diversity analysis)
STANDARD_RANKS = ['superkingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']

# Base columns defined by the metadata schema — anything beyond these is a mapped field
_BASE_METADATA_COLS = set(SRAMetadataSchema.__fields__.keys())



class AlphaDiversityManager:
    """
    Manager for interactive alpha diversity analysis in Jupyter notebooks.
    Provides a widget-based UI for users to:
      - Filter data by taxonomic clade
      - Select aggregation level for counting taxa
      - Color plots by categorical grouping variables
      - View richness and Shannon diversity metrics
    """

    # Accepts either long-format taxonomy table or OTU/ASV table with these columns
    REQUIRED_TAX_COLS = {'acc', 'tax_id', 'rank', 'name', 'total_count'}

    def __init__(
        self,
        taxonomy_df: Optional[pd.DataFrame] = None,
        metadata_df: Optional[pd.DataFrame] = None,
        analysis_wide_df: Optional[pd.DataFrame] = None,
        taxon_lookup_df: Optional[pd.DataFrame] = None,
        metadata_cols: Optional[List[str]] = None,
    ):
        self._is_wide_mode = analysis_wide_df is not None

        if self._is_wide_mode:
            if taxon_lookup_df is None:
                raise ValueError("taxon_lookup_df is required when using analysis_wide_df")

            if metadata_cols is None and metadata_df is not None:
                metadata_cols = list(metadata_df.columns)
            if metadata_cols is None:
                metadata_cols = [c for c in analysis_wide_df.columns if c in _BASE_METADATA_COLS]

            missing_meta = [c for c in metadata_cols if c not in analysis_wide_df.columns]
            if missing_meta:
                raise ValueError(f"analysis_wide_df is missing metadata columns: {missing_meta}")

            self.metadata_df = analysis_wide_df[metadata_cols].copy()
            self.taxon_lookup_df = taxon_lookup_df.copy()

            required_lookup = {'taxon_key', 'tax_id', 'rank', 'name', 'ileft', 'iright'}
            missing_lookup = required_lookup - set(self.taxon_lookup_df.columns)
            if missing_lookup:
                raise ValueError(f"taxon_lookup_df is missing required columns: {missing_lookup}")

            self.taxon_lookup_df['taxon_key'] = self.taxon_lookup_df['taxon_key'].astype(str)
            taxon_cols = [c for c in analysis_wide_df.columns if c in set(self.taxon_lookup_df['taxon_key'])]
            self.sample_taxa_matrix = (
                analysis_wide_df[['acc'] + taxon_cols]
                .set_index('acc')
                .apply(pd.to_numeric, errors='coerce')
                .fillna(0)
            )

            key_to_tax = self.taxon_lookup_df[['taxon_key', 'tax_id']].drop_duplicates()
            self._taxon_key_to_tax_id: Dict[str, str] = {
                str(k): str(v) for k, v in zip(key_to_tax['taxon_key'], key_to_tax['tax_id'])
            }
            self.taxonomy_df = None
        else:
            if taxonomy_df is None or metadata_df is None:
                raise ValueError("taxonomy_df and metadata_df are required in long-format mode")

            missing = self.REQUIRED_TAX_COLS - set(taxonomy_df.columns)
            if missing:
                raise ValueError(f"taxonomy_df is missing required columns: {missing}")
            self.taxonomy_df = taxonomy_df.copy()
            self.metadata_df = metadata_df.copy()
            self.taxon_lookup_df = None
            self.sample_taxa_matrix = None
            self._taxon_key_to_tax_id = {}

        # Computed attributes
        self.tax_accessor: Optional[TaxonomyAccessor] = None
        self.all_ranks: List[str] = []
        self.standard_ranks_display: List[str] = []
        self.mapped_cols: List[str] = []
        self.categorical_cols: List[str] = []
        self._output_area: Optional[Output] = None
        self._is_updating_plot = False
    
    # --- Alpha Diversity Calculation Functions ---
    
    @staticmethod
    def calculate_richness(counts: np.ndarray) -> int:
        """Number of unique taxa with count > 0."""
        return int(np.sum(counts > 0))

    @staticmethod
    def calculate_shannon(counts: np.ndarray) -> float:
        """Shannon diversity index: H = -Σ(pi * ln(pi))."""
        counts = counts[counts > 0]  # Remove zeros
        if len(counts) == 0:
            return 0.0
        proportions = counts / counts.sum()
        return float(-np.sum(proportions * np.log(proportions)))

    def compute_alpha_diversity(self, aggregated_df: pd.DataFrame, sample_col: str = 'sample') -> pd.DataFrame:
        """Compute alpha diversity metrics for each sample."""
        results = []
        for sample, group in aggregated_df.groupby(sample_col):
            counts = group['count'].values
            results.append({
                'sample': sample,
                'richness': self.calculate_richness(counts),
                'shannon': self.calculate_shannon(counts)
            })
        return pd.DataFrame(results)
    
    # --- Data Validation ---
    

    def _initialize_taxonomy(self) -> bool:
        """Build the taxonomy accessor from the taxonomy DataFrame."""
        print("📊 Building taxonomy lineage database...")

        self.tax_accessor = TaxonomyAccessor()
        if self._is_wide_mode:
            lineage_df = self.taxon_lookup_df[['tax_id', 'rank', 'name', 'ileft', 'iright']].copy()
            lineage_df = lineage_df.drop_duplicates(subset=['tax_id'])
            lineage_df['acc'] = '__global__'
            self.tax_accessor.build_from_dataframe(lineage_df)
        else:
            self.tax_accessor.build_from_dataframe(self.taxonomy_df)

        # Get available ranks
        self.all_ranks = self.tax_accessor.get_available_ranks()
        self.standard_ranks_display = [r for r in self.all_ranks if r.lower() in STANDARD_RANKS]

        print(f"📋 Standard ranks available: {self.standard_ranks_display}")
        print(f"   (+ {len(self.all_ranks) - len(self.standard_ranks_display)} additional ranks available)")

        # Identify mapped columns from metadata_df for grouping options
        self.mapped_cols = [c for c in self.metadata_df.columns if c not in _BASE_METADATA_COLS]
        self.categorical_cols = [
            c for c in self.mapped_cols
            if pd.api.types.is_string_dtype(self.metadata_df[c])
        ]

        return True
    
    # --- Taxonomy Helpers ---
    
    def _get_taxa_at_rank(self, rank: str) -> List[str]:
        """Get unique taxon names at a given rank."""
        taxa = set()
        for lineage in self.tax_accessor.database.values():
            for ancestor in lineage:
                if ancestor.get('rank', '').lower() == rank.lower():
                    name = ancestor.get('name', '')
                    if name:
                        taxa.add(name)
        return sorted(taxa)
    
    def _get_matching_tax_ids(self, filter_rank: str, filter_taxon: str) -> Set[str]:
        """Get tax_ids that belong to the specified taxon at the given rank."""
        matching_tax_ids = set()
        for tax_id, lineage in self.tax_accessor.database.items():
            for ancestor in lineage:
                if (ancestor.get('rank', '').lower() == filter_rank.lower() and 
                    ancestor.get('name', '') == filter_taxon):
                    matching_tax_ids.add(str(tax_id))
                    break
        return matching_tax_ids

    def _compute_diversity_from_wide(self, selected_rank: str, filter_rank: str, filter_taxon: str) -> pd.DataFrame:
        """Compute alpha diversity directly from the wide sample x taxon matrix."""
        all_samples = self.sample_taxa_matrix.index
        active_keys = list(self.sample_taxa_matrix.columns)

        if filter_rank != 'No Filter' and filter_taxon != 'All Taxa':
            matching_tax_ids = self._get_matching_tax_ids(filter_rank, filter_taxon)
            active_keys = [
                k for k in active_keys
                if str(self._taxon_key_to_tax_id.get(str(k), '')) in matching_tax_ids
            ]

        if not active_keys:
            return pd.DataFrame({'sample': all_samples, 'richness': 0, 'shannon': 0.0})

        matrix = self.sample_taxa_matrix[active_keys]

        agg_labels: List[str] = []
        for key in active_keys:
            tax_id = str(self._taxon_key_to_tax_id.get(str(key), ''))
            ancestor = self.tax_accessor.get_ancestor_at_rank(tax_id, selected_rank)
            if ancestor:
                agg_labels.append(f"{ancestor['name']}|{ancestor['tax_id']}")
            else:
                agg_labels.append(f"Unclassified ({selected_rank})|NA")

        aggregated_matrix = matrix.T.groupby(agg_labels).sum().T

        richness = (aggregated_matrix > 0).sum(axis=1).astype(int)
        shannon = aggregated_matrix.apply(lambda row: self.calculate_shannon(row.values), axis=1)

        return pd.DataFrame({
            'sample': aggregated_matrix.index,
            'richness': richness.values,
            'shannon': shannon.values,
        })
    
    # --- UI Creation ---
    
    def _create_ui(self) -> VBox:
        """Create and return the complete UI widget."""
        
        # Output area for plots and messages
        self._output_area = Output()
        
        # Track state for rank options
        def get_current_ranks():
            if show_all_ranks.value:
                return self.all_ranks
            return self.standard_ranks_display
        
        # Toggle for showing all ranks
        show_all_ranks = Checkbox(
            value=False, 
            description='Show all ranks', 
            indent=False,
            layout=Layout(width='auto')
        )
        
        # Filter rank selector (which rank to filter by)
        filter_rank_dropdown = Dropdown(
            options=['No Filter'] + self.standard_ranks_display,
            value='No Filter',
            description='① Filter by:',
            style={'description_width': '80px'},
            layout={'width': '200px'}
        )
        
        # Filter taxon selector (which taxon to filter to)
        filter_taxon_dropdown = Dropdown(
            options=['All Taxa'],
            value='All Taxa',
            description='Select:',
            style={'description_width': '50px'},
            layout={'width': '220px'},
            disabled=True
        )
        
        # Update filter taxon options when filter rank changes
        def on_filter_rank_change(change):
            if change.new == 'No Filter':
                filter_taxon_dropdown.options = ['All Taxa']
                filter_taxon_dropdown.value = 'All Taxa'
                filter_taxon_dropdown.disabled = True
            else:
                taxa = self._get_taxa_at_rank(change.new)
                filter_taxon_dropdown.options = ['All Taxa'] + taxa
                filter_taxon_dropdown.value = 'All Taxa'
                filter_taxon_dropdown.disabled = False
        
        filter_rank_dropdown.observe(on_filter_rank_change, names='value')
        
        # Rank selector for counting/aggregation level
        rank_dropdown = Dropdown(
            options=self.standard_ranks_display,
            value=self.standard_ranks_display[-1] if self.standard_ranks_display else None,
            description='② Count at:',
            style={'description_width': '80px'},
            layout={'width': '200px'}
        )
        
        # Update rank dropdowns when show_all_ranks changes
        def on_show_all_change(change):
            current_ranks = get_current_ranks()
            # Update counting rank dropdown
            current_val = rank_dropdown.value
            rank_dropdown.options = current_ranks
            if current_val in current_ranks:
                rank_dropdown.value = current_val
            elif current_ranks:
                rank_dropdown.value = current_ranks[-1]
            # Update filter rank dropdown
            filter_rank_dropdown.options = ['No Filter'] + current_ranks
        
        show_all_ranks.observe(on_show_all_change, names='value')
        
        # Grouping variable selector (from mapped columns)
        group_dropdown = Dropdown(
            options=['None'] + self.categorical_cols,
            value='None',
            description='③ Color by:',
            style={'description_width': '80px'},
            layout={'width': '200px'}
        )
        
        update_btn = Button(description='Update Plot', button_style='primary', icon='refresh')
        
        header_html = HTML("""
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        padding: 15px; border-radius: 8px; margin-bottom: 15px;">
                <h3 style="color: white; margin: 0;">🧬 Alpha Diversity Analysis</h3>
                <p style="color: #e0e0e0; margin: 5px 0 0 0; font-size: 12px;">
                    Richness (observed taxa) & Shannon Index (evenness-weighted diversity)
                </p>
            </div>
        """)
        
        help_html = HTML("""
            <div style="background: #f8f9fa; padding: 10px; border-radius: 6px; margin-bottom: 10px; font-size: 12px; color: #666;">
                <b>① Filter by:</b> Limit analysis to specific taxon (e.g., only Bacteria)<br>
                <b>② Count at:</b> Taxonomic level to count unique taxa (e.g., count genera)<br>
                <b>③ Color by:</b> Split boxplots by a sample grouping variable
            </div>
        """)
        
        # Plot update function
        def update_plot(_=None):
            if self._is_updating_plot:
                return

            self._is_updating_plot = True
            with self._output_area:
                try:
                    clear_output(wait=True)
                    
                    selected_rank = rank_dropdown.value
                    filter_rank = filter_rank_dropdown.value
                    filter_taxon = filter_taxon_dropdown.value
                    group_var = group_dropdown.value if group_dropdown.value != 'None' else None
                    
                    if self._is_wide_mode:
                        total_samples = len(self.sample_taxa_matrix.index)
                        if filter_rank != 'No Filter' and filter_taxon != 'All Taxa':
                            print(f"🔍 Filtering to {filter_taxon} ({filter_rank})...")
                            matching_tax_ids = self._get_matching_tax_ids(filter_rank, filter_taxon)
                            matching_keys = [
                                k for k in self.sample_taxa_matrix.columns
                                if str(self._taxon_key_to_tax_id.get(str(k), '')) in matching_tax_ids
                            ]
                            samples_with_data = (self.sample_taxa_matrix[matching_keys].sum(axis=1) > 0).sum() if matching_keys else 0
                            print(f"   → {samples_with_data}/{total_samples} samples have {filter_taxon} taxa")

                        print(f"🔄 Counting unique taxa at {selected_rank} level...")
                        diversity_df = self._compute_diversity_from_wide(selected_rank, filter_rank, filter_taxon)
                    else:
                        # Start with full taxonomy data
                        working_df = self.taxonomy_df.copy()

                        # Get ALL unique samples BEFORE filtering (to ensure all appear in plot)
                        all_samples = working_df['acc'].unique()
                        total_samples = len(all_samples)

                        # Apply taxon filter if selected
                        if filter_rank != 'No Filter' and filter_taxon != 'All Taxa':
                            print(f"🔍 Filtering to {filter_taxon} ({filter_rank})...")

                            matching_tax_ids = self._get_matching_tax_ids(filter_rank, filter_taxon)
                            working_df = working_df[working_df['tax_id'].astype(str).isin(matching_tax_ids)]
                            samples_with_data = working_df['acc'].nunique()
                            print(f"   → {samples_with_data}/{total_samples} samples have {filter_taxon} taxa")

                        print(f"🔄 Counting unique taxa at {selected_rank} level...")

                        # Aggregate at selected rank (may have fewer samples if filtering removed some)
                        if working_df.empty:
                            # No data after filter - create empty diversity_df
                            diversity_df = pd.DataFrame({'sample': all_samples, 'richness': 0, 'shannon': 0.0})
                        else:
                            aggregated_df = self.tax_accessor.aggregate_counts_at_rank(
                                working_df,
                                target_rank=selected_rank,
                                tax_id_col='tax_id',
                                count_col='total_count',
                                sample_col='acc'
                            )

                            # Compute alpha diversity
                            diversity_df = self.compute_alpha_diversity(aggregated_df)
                    
                    # Ensure ALL samples are included (even if they have 0 taxa after filtering)
                    all_samples = self.sample_taxa_matrix.index if self._is_wide_mode else self.taxonomy_df['acc'].unique()
                    all_samples_df = pd.DataFrame({'sample': all_samples})
                    diversity_df = all_samples_df.merge(diversity_df, on='sample', how='left')
                    diversity_df['richness'] = diversity_df['richness'].fillna(0).astype(int)
                    diversity_df['shannon'] = diversity_df['shannon'].fillna(0.0)
                    
                    # Merge with grouping variable from metadata (unaffected by taxonomy filter)
                    if group_var:
                        sample_groups = self.metadata_df[['acc', group_var]].drop_duplicates()
                        diversity_df = diversity_df.merge(sample_groups, left_on='sample', right_on='acc', how='left')
                        color_col = group_var
                    else:
                        color_col = None
                    
                    filter_text = f" within {filter_taxon}" if filter_taxon != 'All Taxa' else ""
                    samples_with_zero = (diversity_df['richness'] == 0).sum()
                    if samples_with_zero > 0:
                        print(f"✅ Computed diversity for {len(diversity_df)} samples{filter_text} ({samples_with_zero} samples have 0 taxa)")
                    else:
                        print(f"✅ Computed diversity for {len(diversity_df)} samples{filter_text}")
                    
                    # Create subplot figure (vertical layout - one plot per row)
                    title_filter = f" ({filter_taxon})" if filter_taxon != 'All Taxa' else ""
                    fig = make_subplots(
                        rows=2, cols=1,
                        subplot_titles=[f'{selected_rank.title()} Richness{title_filter}',
                                       f'Shannon Index{title_filter}'],
                        vertical_spacing=0.25
                    )
                    
                    # Plot 1: Richness
                    if color_col:
                        for group_name in diversity_df[color_col].unique():
                            group_data = diversity_df[diversity_df[color_col] == group_name]
                            n_samples = len(group_data)
                            fig.add_trace(
                                go.Box(y=group_data['richness'], name=f"{group_name} (n={n_samples})", 
                                       boxmean=True, showlegend=True),
                                row=1, col=1
                            )
                    else:
                        n_samples = len(diversity_df)
                        fig.add_trace(
                            go.Box(y=diversity_df['richness'], name=f'All Samples (n={n_samples})', 
                                   boxmean=True, marker_color='#667eea'),
                            row=1, col=1
                        )
                    
                    # Plot 2: Shannon
                    if color_col:
                        for group_name in diversity_df[color_col].unique():
                            group_data = diversity_df[diversity_df[color_col] == group_name]
                            n_samples = len(group_data)
                            fig.add_trace(
                                go.Box(y=group_data['shannon'], name=f"{group_name} (n={n_samples})",
                                       boxmean=True, showlegend=False),
                                row=2, col=1
                            )
                    else:
                        n_samples = len(diversity_df)
                        fig.add_trace(
                            go.Box(y=diversity_df['shannon'], name=f'All Samples (n={n_samples})',
                                   boxmean=True, marker_color='#764ba2'),
                            row=2, col=1
                        )
                    
                    fig.update_layout(
                        height=900,
                        title_text=f"Alpha Diversity at {selected_rank.title()} Level{title_filter}",
                        showlegend=bool(color_col),
                        template='plotly_white'
                    )
                    
                    fig.update_xaxes(tickangle=-30, row=1, col=1)
                    fig.update_xaxes(tickangle=-30, row=2, col=1)
                    fig.update_yaxes(title_text=f"# of {selected_rank.title()}s", row=1, col=1)
                    fig.update_yaxes(title_text="Shannon Index (H')", row=2, col=1)
                    
                    fig.show()
                    
                    # Summary statistics
                    print(f"\n📈 Summary Statistics:")
                    print(f"   Richness - Mean: {diversity_df['richness'].mean():.1f}, "
                          f"Median: {diversity_df['richness'].median():.1f}, "
                          f"Range: [{diversity_df['richness'].min()}, {diversity_df['richness'].max()}]")
                    print(f"   Shannon  - Mean: {diversity_df['shannon'].mean():.2f}, "
                          f"Median: {diversity_df['shannon'].median():.2f}, "
                          f"Range: [{diversity_df['shannon'].min():.2f}, {diversity_df['shannon'].max():.2f}]")
                finally:
                    self._is_updating_plot = False
        
        update_btn.on_click(update_plot)
        
        # Layout - cleaner organization
        filter_section = HBox([
            HTML("<span style='font-weight:bold; margin-right:10px;'>Filter:</span>"),
            filter_rank_dropdown, 
            filter_taxon_dropdown
        ], layout=Layout(align_items='center', margin='0 0 8px 0'))
        
        analysis_section = HBox([
            HTML("<span style='font-weight:bold; margin-right:10px;'>Analyze:</span>"),
            rank_dropdown, 
            group_dropdown,
            update_btn
        ], layout=Layout(align_items='center', margin='0 0 8px 0'))
        
        options_section = HBox([show_all_ranks], layout=Layout(margin='0 0 8px 0'))
        
        controls = VBox([filter_section, analysis_section, options_section])
        ui = VBox([header_html, help_html, controls, self._output_area])
        
        return ui
    
    # --- Public API ---
    
    def run(self) -> None:
        """
        Initialize the taxonomy database and display the interactive UI.
        
        This is the main entry point for using the AlphaDiversityManager.
        Call this method to show the interactive alpha diversity analysis widget.
        """
        if not self._initialize_taxonomy():
            return
        
        ui = self._create_ui()
        display(ui)
