"""
Longitudinal Analysis Manager.

This module provides an interactive UI for analyzing microbiome changes over time
within subjects. Supports trajectory plots, paired comparisons, taxon tracking,
and change-point detection.

Following the iDesign architecture pattern, this manager orchestrates the presentation
layer for longitudinal analysis, handling repeated measures / time series data.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from ipywidgets import (
    Dropdown, VBox, HBox, Output, HTML, Button, Layout, 
    Checkbox, Text, IntSlider, SelectMultiple
)
from IPython.display import display, clear_output
from scipy import stats
from typing import List, Optional, Set, Tuple, Any

from Accessors.TaxonomyAccessor import TaxonomyAccessor


# Standard taxonomic ranks for filtering
STANDARD_RANKS = ['superkingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']

# Column name candidates for auto-detection
SUBJECT_CANDIDATES = ['subject_id', 'host_subject_id', 'patient_id', 'participant_id', 'individual_id']
TIMEPOINT_CANDIDATES = ['timepoint', 'collection_date', 'visit', 'visit_number', 'day', 'days_post_treatment', 'week']


class LongitudinalAnalysisManager:
    """
    Manager for interactive longitudinal analysis in Jupyter notebooks.
    
    Provides a widget-based UI for users to:
    - Visualize diversity trajectories over time (spaghetti plots)
    - Perform paired comparisons between timepoints (Wilcoxon test)
    - Track specific taxa abundance over time
    - Detect significant change-points in diversity
    
    REQUIRES: subject_id and timepoint columns in the enriched DataFrame.
    """
    
    def __init__(self, enriched_df: pd.DataFrame, original_columns: Set[str]):
        """
        Initialize the Longitudinal Analysis Manager.
        
        Args:
            enriched_df: The analysis-ready DataFrame with taxonomy and count data.
            original_columns: Set of column names from the original (pre-mapping) DataFrame.
                             Used to identify which columns were added by mappings.
        """
        self.enriched_df = enriched_df
        self.original_columns = original_columns
        
        # Detected column names
        self.subject_col: Optional[str] = None
        self.timepoint_col: Optional[str] = None
        
        # Computed attributes
        self.mapped_cols: List[str] = []
        self.categorical_cols: List[str] = []
        self.subjects: List[str] = []
        self.timepoints: List[Any] = []
        self.top_taxa: List[str] = []
        
        # Taxonomy accessor for filtering
        self.tax_accessor: Optional[TaxonomyAccessor] = None
        self.all_ranks: List[str] = []
        self.standard_ranks_display: List[str] = []
        
        # UI components (created in run())
        self._output_area: Optional[Output] = None
    
    # --- Column Detection ---
    
    def _detect_longitudinal_columns(self) -> Tuple[bool, bool]:
        """
        Detect subject_id and timepoint columns in the DataFrame.
        
        Returns:
            Tuple of (has_subject_col, has_timepoint_col)
        """
        # Find subject column
        for candidate in SUBJECT_CANDIDATES:
            if candidate in self.enriched_df.columns:
                self.subject_col = candidate
                break
        
        # Find timepoint column
        for candidate in TIMEPOINT_CANDIDATES:
            if candidate in self.enriched_df.columns:
                self.timepoint_col = candidate
                break
        
        return (self.subject_col is not None, self.timepoint_col is not None)
    
    def _initialize_data(self) -> bool:
        """
        Initialize data structures after column detection.
        
        Returns:
            True if both required columns were found.
        """
        has_subject, has_timepoint = self._detect_longitudinal_columns()
        
        if not has_subject or not has_timepoint:
            return False
        
        # Identify mapped columns
        self.mapped_cols = [c for c in self.enriched_df.columns if c not in self.original_columns]
        
        # Get categorical columns for grouping (excluding subject/timepoint)
        self.categorical_cols = [
            c for c in self.mapped_cols 
            if pd.api.types.is_string_dtype(self.enriched_df[c])
            and c not in [self.subject_col, self.timepoint_col]
        ]
        
        # Get unique subjects and timepoints
        self.subjects = sorted([str(s) for s in self.enriched_df[self.subject_col].dropna().unique()])
        self.timepoints = sorted(self.enriched_df[self.timepoint_col].dropna().unique())
        
        # Get top taxa for taxon tracking
        if 'name' in self.enriched_df.columns:
            self.top_taxa = self.enriched_df.groupby('name')['total_count'].sum().nlargest(50).index.tolist()
        else:
            self.top_taxa = []
        
        # Initialize taxonomy accessor for filtering
        self._initialize_taxonomy()
        
        return True
    
    def _initialize_taxonomy(self) -> bool:
        """Build the taxonomy accessor from the enriched DataFrame."""
        required_cols = {'tax_id', 'rank', 'name', 'ileft', 'iright'}
        available_cols = set(self.enriched_df.columns)
        
        if not required_cols.issubset(available_cols):
            # Taxonomy columns not available - filtering won't be available
            self.tax_accessor = None
            return False
        
        self.tax_accessor = TaxonomyAccessor()
        self.tax_accessor.build_from_dataframe(self.enriched_df)
        
        # Get available ranks
        self.all_ranks = self.tax_accessor.get_available_ranks()
        self.standard_ranks_display = [r for r in self.all_ranks if r.lower() in [sr.lower() for sr in STANDARD_RANKS]]
        
        return True
    
    # --- Taxonomy Helpers ---
    
    def _get_taxa_at_rank(self, rank: str) -> List[str]:
        """Get unique taxon names at a given rank."""
        if not self.tax_accessor:
            return []
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
        if not self.tax_accessor:
            return set()
        matching_tax_ids = set()
        for tax_id, lineage in self.tax_accessor.database.items():
            for ancestor in lineage:
                if (ancestor.get('rank', '').lower() == filter_rank.lower() and 
                    ancestor.get('name', '') == filter_taxon):
                    matching_tax_ids.add(str(tax_id))
                    break
        return matching_tax_ids
    
    # --- Diversity Calculation ---
    
    def _calculate_diversity_per_sample(
        self, 
        selected_subjects: Optional[List[str]] = None,
        working_df: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        Calculate diversity metrics (richness, shannon) for each sample.
        
        Args:
            selected_subjects: If provided, only compute for these subjects.
            working_df: If provided, use this DataFrame instead of self.enriched_df
                        (useful for taxonomy-filtered data).
        
        Returns:
            DataFrame with columns: acc, richness, shannon, subject_col, timepoint_col, [categorical_cols]
        """
        df = working_df if working_df is not None else self.enriched_df
        results = []
        
        for acc in df['acc'].unique():
            sample_df = df[df['acc'] == acc]
            
            # Skip if subject not in selected list
            subj = str(sample_df.iloc[0][self.subject_col])
            if selected_subjects and subj not in selected_subjects:
                continue
            
            counts = sample_df['total_count'].values
            counts = counts[counts > 0]
            
            richness = int(np.sum(counts > 0))
            if len(counts) > 0:
                proportions = counts / counts.sum()
                shannon = float(-np.sum(proportions * np.log(proportions)))
            else:
                shannon = 0.0
            
            # Get subject and timepoint
            row = sample_df.iloc[0]
            result = {
                'acc': acc,
                'richness': richness,
                'shannon': shannon,
                self.subject_col: row[self.subject_col],
                self.timepoint_col: row[self.timepoint_col]
            }
            
            # Add grouping variables
            for col in self.categorical_cols:
                if col in sample_df.columns:
                    result[col] = row[col]
            
            results.append(result)
        
        return pd.DataFrame(results)
    
    # --- UI Components ---
    
    def _create_missing_fields_ui(self) -> HTML:
        """Create UI showing which longitudinal fields are missing."""
        html = HTML(f"""
            <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); 
                        padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                <h3 style="color: white; margin: 0;">📈 Longitudinal Analysis</h3>
                <p style="color: #ffe0e6; margin: 10px 0 0 0;">
                    Analyze microbiome changes over time within subjects
                </p>
            </div>
            <div style="background: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 8px;">
                <h4 style="margin: 0 0 10px 0; color: #856404;">⚠️ Longitudinal Fields Required</h4>
                <p style="margin: 0; color: #856404;">
                    To enable longitudinal analysis, map these fields in <b>Step 5</b>:
                </p>
                <ul style="margin: 10px 0; color: #856404;">
                    {'<li><code>subject_id</code> → Map to patient/participant identifier</li>' if not self.subject_col else '<li>✅ <code>subject_id</code> detected</li>'}
                    {'<li><code>timepoint</code> → Map to collection date or visit number</li>' if not self.timepoint_col else '<li>✅ <code>timepoint</code> detected</li>'}
                </ul>
                <p style="margin: 0; font-size: 12px; color: #856404;">
                    Look for source keys like: <code>host_subject_id</code>, <code>collection_date</code>, <code>visit</code>
                </p>
            </div>
        """)
        return html
    
    def _create_ui(self) -> VBox:
        """Create and return the complete longitudinal analysis UI widget."""
        
        # Output area for plots and messages
        self._output_area = Output()
        
        header_html = HTML(f"""
            <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); 
                        padding: 20px; border-radius: 8px; margin-bottom: 15px;">
                <h3 style="color: white; margin: 0;">📈 Longitudinal Analysis</h3>
                <p style="color: #ffe0e6; margin: 5px 0 0 0; font-size: 12px;">
                    Tracking {len(self.subjects)} subjects across {len(self.timepoints)} timepoints
                </p>
            </div>
        """)
        
        help_html = HTML("""
            <div style="background: #f8f9fa; padding: 10px; border-radius: 6px; margin-bottom: 10px; font-size: 12px; color: #666;">
                <b>① Filter by:</b> Limit analysis to specific taxon (e.g., only Bacteria)<br>
                <b>📉 Trajectory:</b> Individual subject diversity over time (spaghetti plot)<br>
                <b>🔄 Paired:</b> Compare two timepoints with statistical test<br>
                <b>🔬 Taxon Track:</b> Follow specific taxa abundance over time<br>
                <b>📍 Change-Point:</b> Detect significant shifts in diversity
            </div>
        """)
        
        # --- Taxonomy Filter Section (like Alpha Diversity) ---
        filter_rank_dropdown = Dropdown(
            options=['No Filter'] + self.standard_ranks_display if self.tax_accessor else ['No Filter'],
            value='No Filter',
            description='① Filter by:',
            style={'description_width': '80px'},
            layout={'width': '200px'}
        )
        
        filter_taxon_dropdown = Dropdown(
            options=['All Taxa'],
            value='All Taxa',
            description='Select:',
            style={'description_width': '50px'},
            layout={'width': '220px'},
            disabled=True
        )
        
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
        
        # Analysis type selector
        analysis_dropdown = Dropdown(
            options=[
                ('📉 Trajectory Plot (Spaghetti)', 'trajectory'),
                ('🔄 Paired Comparison', 'paired'),
                ('🔬 Track Specific Taxon', 'taxon_track'),
                ('📍 Change-Point Detection', 'changepoint')
            ],
            value='trajectory',
            description='Analysis:',
            style={'description_width': '70px'},
            layout={'width': '280px'}
        )
        
        # Metric selector
        metric_dropdown = Dropdown(
            options=[('Richness', 'richness'), ('Shannon Index', 'shannon')],
            value='richness',
            description='Metric:',
            style={'description_width': '70px'},
            layout={'width': '200px'}
        )
        
        # Rank selector for counting
        rank_options = self.standard_ranks_display if self.standard_ranks_display else ['species', 'genus', 'family']
        rank_dropdown = Dropdown(
            options=rank_options,
            value=rank_options[-1] if rank_options else 'species',
            description='Count at:',
            style={'description_width': '70px'},
            layout={'width': '180px'}
        )
        
        # Group by selector
        group_dropdown = Dropdown(
            options=['None'] + self.categorical_cols,
            value='None',
            description='Group by:',
            style={'description_width': '70px'},
            layout={'width': '200px'}
        )
        
        # --- Subject filter options (using checkboxes for reliability) ---
        subject_filter_options = VBox([], layout=Layout(display='none'))
        
        filter_subjects_checkbox = Checkbox(
            value=False,
            description='Filter subjects',
            indent=False,
            layout=Layout(width='auto')
        )
        
        subject_search = Text(
            placeholder='Search subject ID...',
            description='Search:',
            style={'description_width': '55px'},
            layout={'width': '200px'}
        )
        
        # Create a checkbox for each subject
        subject_checkboxes = {}
        for subj in self.subjects:
            cb = Checkbox(
                value=False,
                description=subj,
                indent=False,
                layout=Layout(width='auto', margin='0 10px 2px 0')
            )
            subject_checkboxes[subj] = cb
        
        # Container for visible checkboxes (scrollable)
        checkbox_container = VBox(
            list(subject_checkboxes.values())[:50],  # Show first 50 by default
            layout=Layout(
                max_height='150px',
                overflow_y='auto',
                border='1px solid #ddd',
                padding='5px',
                margin='5px 0'
            )
        )
        
        subject_count_label = HTML(
            f"<span style='font-size: 11px; color: #666;'>0 of {len(self.subjects)} selected (showing all)</span>"
        )
        
        # Select All / Deselect All buttons
        select_all_btn = Button(
            description='Select All',
            button_style='info',
            layout=Layout(width='90px', height='28px'),
            style={'font_size': '11px'}
        )
        deselect_all_btn = Button(
            description='Deselect All',
            button_style='warning',
            layout=Layout(width='95px', height='28px'),
            style={'font_size': '11px'}
        )
        
        # Track currently visible checkboxes
        visible_subjects = [self.subjects.copy()]  # Use list to allow mutation in nested func
        
        def get_selected_subjects_from_checkboxes() -> List[str]:
            """Get list of subjects that are checked."""
            return [subj for subj, cb in subject_checkboxes.items() if cb.value]
        
        def update_subject_count():
            """Update the subject count label based on current selection."""
            selected = get_selected_subjects_from_checkboxes()
            n_selected = len(selected)
            if n_selected == 0:
                subject_count_label.value = f"<span style='font-size: 11px; color: #666;'>0 of {len(self.subjects)} selected (showing all)</span>"
            else:
                subject_count_label.value = f"<span style='font-size: 11px; color: #28a745;'>{n_selected} of {len(self.subjects)} selected</span>"
        
        def on_checkbox_change(change):
            update_subject_count()
        
        # Attach observer to each checkbox
        for cb in subject_checkboxes.values():
            cb.observe(on_checkbox_change, names='value')
        
        def on_subject_search(change):
            query = change.new.lower().strip()
            
            if query:
                filtered = [s for s in self.subjects if query in s.lower()]
            else:
                filtered = self.subjects.copy()
            
            visible_subjects[0] = filtered
            # Update visible checkboxes (limit to 100 for performance)
            checkbox_container.children = [subject_checkboxes[s] for s in filtered[:100]]
            
            if len(filtered) > 100:
                subject_count_label.value = f"<span style='font-size: 11px; color: #666;'>Showing first 100 of {len(filtered)} matches</span>"
        
        subject_search.observe(on_subject_search, names='value')
        
        def on_select_all(btn):
            for subj in visible_subjects[0]:
                subject_checkboxes[subj].value = True
            update_subject_count()
        
        def on_deselect_all(btn):
            for subj in visible_subjects[0]:
                subject_checkboxes[subj].value = False
            update_subject_count()
        
        select_all_btn.on_click(on_select_all)
        deselect_all_btn.on_click(on_deselect_all)
        
        def on_filter_subjects_change(change):
            subject_filter_options.layout.display = 'block' if change.new else 'none'
        
        filter_subjects_checkbox.observe(on_filter_subjects_change, names='value')
        
        subject_filter_options.children = [
            HBox([subject_search, select_all_btn, deselect_all_btn], layout=Layout(align_items='center', gap='5px')),
            subject_count_label,
            checkbox_container
        ]
        
        # --- Paired comparison options ---
        paired_options = VBox([], layout=Layout(display='none'))
        
        baseline_dropdown = Dropdown(
            options=self.timepoints,
            value=self.timepoints[0] if self.timepoints else None,
            description='Baseline:',
            style={'description_width': '70px'},
            layout={'width': '200px'}
        )
        
        compare_dropdown = Dropdown(
            options=self.timepoints,
            value=self.timepoints[-1] if len(self.timepoints) > 1 else (self.timepoints[0] if self.timepoints else None),
            description='Compare to:',
            style={'description_width': '80px'},
            layout={'width': '200px'}
        )
        
        paired_options.children = [
            HTML("<div style='font-size: 12px; color: #666; margin: 5px 0;'>Select timepoints for paired comparison:</div>"),
            HBox([baseline_dropdown, compare_dropdown])
        ]
        
        # --- Taxon tracking options ---
        taxon_options = VBox([], layout=Layout(display='none'))
        
        taxon_search = Text(
            placeholder='Search taxon name...',
            description='Taxon:',
            style={'description_width': '70px'},
            layout={'width': '300px'}
        )
        
        taxon_select = SelectMultiple(
            options=self.top_taxa[:20],
            description='Select:',
            style={'description_width': '70px'},
            layout={'width': '300px', 'height': '120px'}
        )
        
        def on_taxon_search(change):
            query = change.new.lower()
            if query:
                filtered = [t for t in self.top_taxa if query in t.lower()][:20]
            else:
                filtered = self.top_taxa[:20]
            taxon_select.options = filtered
        
        taxon_search.observe(on_taxon_search, names='value')
        
        taxon_options.children = [
            HTML("<div style='font-size: 12px; color: #666; margin: 5px 0;'>Track specific taxa over time:</div>"),
            taxon_search,
            taxon_select
        ]
        
        # --- Change-point options ---
        changepoint_options = VBox([], layout=Layout(display='none'))
        
        sensitivity_slider = IntSlider(
            value=2,
            min=1,
            max=5,
            description='Sensitivity:',
            style={'description_width': '80px'},
            layout={'width': '300px'}
        )
        
        changepoint_options.children = [
            HTML("<div style='font-size: 12px; color: #666; margin: 5px 0;'>Detect significant shifts in diversity:</div>"),
            sensitivity_slider
        ]
        
        # Toggle visibility based on analysis type
        def on_analysis_change(change):
            paired_options.layout.display = 'block' if change.new == 'paired' else 'none'
            taxon_options.layout.display = 'block' if change.new == 'taxon_track' else 'none'
            changepoint_options.layout.display = 'block' if change.new == 'changepoint' else 'none'
            metric_dropdown.layout.display = 'none' if change.new == 'taxon_track' else 'block'
        
        analysis_dropdown.observe(on_analysis_change, names='value')
        
        update_btn = Button(description='Generate Plot', button_style='primary', icon='chart-line')
        
        def get_selected_subjects() -> List[str]:
            """Return list of subjects to analyze based on filter settings."""
            if filter_subjects_checkbox.value:
                selected = get_selected_subjects_from_checkboxes()
                if len(selected) > 0:
                    return selected
            return self.subjects
        
        def get_filtered_dataframe() -> pd.DataFrame:
            """Apply taxonomy filter to the enriched DataFrame."""
            filter_rank = filter_rank_dropdown.value
            filter_taxon = filter_taxon_dropdown.value
            
            if filter_rank == 'No Filter' or filter_taxon == 'All Taxa':
                return self.enriched_df
            
            matching_tax_ids = self._get_matching_tax_ids(filter_rank, filter_taxon)
            filtered_df = self.enriched_df[self.enriched_df['tax_id'].astype(str).isin(matching_tax_ids)]
            return filtered_df
        
        # --- Plot Update Function ---
        def update_plot(_=None):
            with self._output_area:
                clear_output(wait=True)
                
                analysis_type = analysis_dropdown.value
                metric = metric_dropdown.value
                group_var = group_dropdown.value if group_dropdown.value != 'None' else None
                selected_subjects = get_selected_subjects()
                filter_rank = filter_rank_dropdown.value
                filter_taxon = filter_taxon_dropdown.value
                
                # Apply taxonomy filter
                if filter_rank != 'No Filter' and filter_taxon != 'All Taxa':
                    print(f"🔍 Filtering to {filter_taxon} ({filter_rank})...")
                    working_df = get_filtered_dataframe()
                    print(f"   → Kept {len(working_df):,} rows from {len(self.enriched_df):,} total")
                    if working_df.empty:
                        print(f"⚠️ No data remaining after filter. Try a different taxon.")
                        return
                else:
                    working_df = self.enriched_df
                
                # Show subject filter info
                if filter_subjects_checkbox.value and len(selected_subjects) < len(self.subjects):
                    preview = ', '.join(selected_subjects[:5])
                    suffix = '...' if len(selected_subjects) > 5 else ''
                    print(f"🔍 Filtering to {len(selected_subjects)} subject(s): {preview}{suffix}")
                
                print(f"⏳ Computing diversity metrics...")
                diversity_df = self._calculate_diversity_per_sample(selected_subjects, working_df)
                
                if diversity_df.empty:
                    print("⚠️ No data for selected subjects")
                    return
                
                filter_suffix = f" ({filter_taxon})" if filter_taxon != 'All Taxa' else ""
                
                if analysis_type == 'trajectory':
                    self._plot_trajectory(diversity_df, metric, group_var, filter_suffix)
                
                elif analysis_type == 'paired':
                    baseline = baseline_dropdown.value
                    compare = compare_dropdown.value
                    self._plot_paired_comparison(diversity_df, metric, baseline, compare, filter_suffix)
                
                elif analysis_type == 'taxon_track':
                    selected_taxa = list(taxon_select.value)
                    self._plot_taxon_tracking(selected_subjects, selected_taxa, filter_subjects_checkbox.value, working_df)
                
                elif analysis_type == 'changepoint':
                    sensitivity = sensitivity_slider.value
                    self._plot_changepoint_detection(diversity_df, metric, sensitivity, filter_suffix)
        
        update_btn.on_click(update_plot)
        
        # Layout
        filter_section = HBox([
            filter_rank_dropdown, 
            filter_taxon_dropdown
        ], layout=Layout(align_items='center', margin='0 0 8px 0'))
        
        row1 = HBox([analysis_dropdown, metric_dropdown, rank_dropdown], 
                    layout=Layout(margin='0 0 8px 0'))
        row2 = HBox([group_dropdown, filter_subjects_checkbox, update_btn],
                    layout=Layout(margin='0 0 8px 0', align_items='center'))
        
        controls = VBox([filter_section, row1, row2, subject_filter_options, paired_options, taxon_options, changepoint_options])
        ui = VBox([header_html, help_html, controls, self._output_area])
        
        return ui
    
    # --- Plot Functions ---
    
    def _plot_trajectory(self, diversity_df: pd.DataFrame, metric: str, group_var: Optional[str], filter_suffix: str = "") -> None:
        """Generate spaghetti plot of diversity trajectories."""
        print(f"📉 Generating trajectory plot for {metric}...")
        
        fig = go.Figure()
        
        # Sort timepoints for proper line ordering
        try:
            diversity_df[self.timepoint_col] = pd.to_numeric(diversity_df[self.timepoint_col])
            diversity_df = diversity_df.sort_values(self.timepoint_col)
        except:
            pass
        
        if group_var:
            groups = diversity_df[group_var].unique()
            colors = px.colors.qualitative.Set2[:len(groups)]
            color_map = dict(zip(groups, colors))
            
            for subj in diversity_df[self.subject_col].unique():
                subj_df = diversity_df[diversity_df[self.subject_col] == subj].sort_values(self.timepoint_col)
                grp = subj_df[group_var].iloc[0] if len(subj_df) > 0 else 'Unknown'
                fig.add_trace(go.Scatter(
                    x=subj_df[self.timepoint_col],
                    y=subj_df[metric],
                    mode='lines+markers',
                    name=str(grp),
                    legendgroup=str(grp),
                    showlegend=subj == diversity_df[diversity_df[group_var] == grp][self.subject_col].iloc[0],
                    line=dict(color=color_map.get(grp, 'gray'), width=1),
                    marker=dict(size=6),
                    opacity=0.6,
                    hovertemplate=f"Subject: {subj}<br>{self.timepoint_col}: %{{x}}<br>{metric}: %{{y:.2f}}<extra></extra>"
                ))
            
            # Add group means
            for grp in groups:
                grp_df = diversity_df[diversity_df[group_var] == grp]
                mean_df = grp_df.groupby(self.timepoint_col)[metric].mean().reset_index()
                fig.add_trace(go.Scatter(
                    x=mean_df[self.timepoint_col],
                    y=mean_df[metric],
                    mode='lines+markers',
                    name=f'{grp} (mean)',
                    legendgroup=str(grp),
                    line=dict(color=color_map.get(grp, 'gray'), width=4),
                    marker=dict(size=12, symbol='diamond')
                ))
        else:
            for subj in diversity_df[self.subject_col].unique():
                subj_df = diversity_df[diversity_df[self.subject_col] == subj].sort_values(self.timepoint_col)
                fig.add_trace(go.Scatter(
                    x=subj_df[self.timepoint_col],
                    y=subj_df[metric],
                    mode='lines+markers',
                    name=str(subj),
                    showlegend=False,
                    line=dict(width=1, color='steelblue'),
                    marker=dict(size=5),
                    opacity=0.5,
                    hovertemplate=f"Subject: {subj}<br>{self.timepoint_col}: %{{x}}<br>{metric}: %{{y:.2f}}<extra></extra>"
                ))
            
            # Add overall mean
            mean_df = diversity_df.groupby(self.timepoint_col)[metric].mean().reset_index()
            fig.add_trace(go.Scatter(
                x=mean_df[self.timepoint_col],
                y=mean_df[metric],
                mode='lines+markers',
                name='Mean',
                line=dict(color='crimson', width=4),
                marker=dict(size=12, symbol='diamond')
            ))
        
        metric_names = {'richness': 'Richness', 'shannon': "Shannon Index (H')"}
        fig.update_layout(
            title=f"{metric_names[metric]} Trajectories Over Time{filter_suffix}",
            xaxis_title=self.timepoint_col.replace('_', ' ').title(),
            yaxis_title=metric_names[metric],
            template='plotly_white',
            height=500,
            hovermode='closest'
        )
        fig.show()
        
        print(f"✅ Plotted {diversity_df[self.subject_col].nunique()} subject trajectories")
    
    def _plot_paired_comparison(self, diversity_df: pd.DataFrame, metric: str, baseline: Any, compare: Any, filter_suffix: str = "") -> None:
        """Generate paired comparison plot with Wilcoxon test."""
        print(f"🔄 Comparing {baseline} vs {compare}...")
        
        # Get paired data
        baseline_df = diversity_df[diversity_df[self.timepoint_col] == baseline][[self.subject_col, metric]].rename(columns={metric: 'baseline'})
        compare_df = diversity_df[diversity_df[self.timepoint_col] == compare][[self.subject_col, metric]].rename(columns={metric: 'compare'})
        
        paired_df = baseline_df.merge(compare_df, on=self.subject_col, how='inner')
        paired_df['change'] = paired_df['compare'] - paired_df['baseline']
        
        if len(paired_df) < 2:
            print(f"⚠️ Not enough paired samples (found {len(paired_df)})")
            return
        
        # Wilcoxon test
        stat, pval = stats.wilcoxon(paired_df['baseline'], paired_df['compare'])
        
        # Create figure
        fig = make_subplots(rows=1, cols=2, subplot_titles=['Paired Values', 'Change Distribution'])
        
        # Paired plot with connecting lines
        for _, row in paired_df.iterrows():
            color = 'green' if row['change'] > 0 else 'red'
            fig.add_trace(go.Scatter(
                x=[baseline, compare],
                y=[row['baseline'], row['compare']],
                mode='lines+markers',
                line=dict(color=color, width=1),
                marker=dict(size=8),
                showlegend=False,
                hovertemplate=f"Subject: {row[self.subject_col]}<br>Baseline: {row['baseline']:.2f}<br>Compare: {row['compare']:.2f}<extra></extra>"
            ), row=1, col=1)
        
        # Change histogram
        fig.add_trace(go.Histogram(
            x=paired_df['change'],
            nbinsx=15,
            marker_color='steelblue',
            showlegend=False
        ), row=1, col=2)
        
        # Add mean line
        fig.add_vline(x=0, line_dash='dash', line_color='gray', row=1, col=2)
        fig.add_vline(x=paired_df['change'].mean(), line_color='red', row=1, col=2)
        
        metric_names = {'richness': 'Richness', 'shannon': "Shannon Index"}
        stars = ''.join(['*' if pval < t else '' for t in [0.05, 0.01, 0.001]])
        
        fig.update_layout(
            title=f"Paired Comparison{filter_suffix}: {baseline} → {compare} (p={pval:.4f})",
            template='plotly_white',
            height=400,
            annotations=[
                dict(
                    text=f"Wilcoxon p={pval:.4f} {stars}",
                    xref="paper", yref="paper",
                    x=0.5, y=1.08, showarrow=False,
                    font=dict(size=14, color='red' if pval < 0.05 else 'gray')
                )
            ]
        )
        fig.update_xaxes(title_text=self.timepoint_col.title(), row=1, col=1)
        fig.update_yaxes(title_text=metric_names[metric], row=1, col=1)
        fig.update_xaxes(title_text=f"Change in {metric_names[metric]}", row=1, col=2)
        fig.update_yaxes(title_text="Count", row=1, col=2)
        
        fig.show()
        
        # Summary
        print(f"\n📊 Paired Analysis Summary (n={len(paired_df)} subjects):")
        print(f"   Baseline ({baseline}): Mean={paired_df['baseline'].mean():.2f}, SD={paired_df['baseline'].std():.2f}")
        print(f"   Compare ({compare}):   Mean={paired_df['compare'].mean():.2f}, SD={paired_df['compare'].std():.2f}")
        print(f"   Mean change: {paired_df['change'].mean():.2f} ± {paired_df['change'].std():.2f}")
        print(f"   Wilcoxon p-value: {pval:.4f} {'✅ Significant' if pval < 0.05 else ''}")
    
    def _plot_taxon_tracking(self, selected_subjects: List[str], selected_taxa: List[str], filter_active: bool, working_df: Optional[pd.DataFrame] = None) -> None:
        """Generate taxon abundance tracking plots."""
        if not selected_taxa:
            print("⚠️ Select at least one taxon to track")
            return
        
        print(f"🔬 Tracking {len(selected_taxa)} taxa over time...")
        
        # Use provided working_df or fall back to enriched_df
        df = working_df if working_df is not None else self.enriched_df
        
        # Filter to selected subjects
        if filter_active and selected_subjects:
            df = df[df[self.subject_col].astype(str).isin(selected_subjects)]
        
        # Get counts per taxon per sample
        taxon_data = df[df['name'].isin(selected_taxa)].copy()
        taxon_agg = taxon_data.groupby(['acc', 'name']).agg({
            'total_count': 'sum',
            self.subject_col: 'first',
            self.timepoint_col: 'first'
        }).reset_index()
        
        # Calculate relative abundance per sample
        sample_totals = df.groupby('acc')['total_count'].sum()
        taxon_agg['rel_abundance'] = taxon_agg.apply(
            lambda r: r['total_count'] / sample_totals[r['acc']] * 100 if sample_totals[r['acc']] > 0 else 0,
            axis=1
        )
        
        fig = make_subplots(
            rows=len(selected_taxa), cols=1,
            subplot_titles=[f"<b>{t}</b>" for t in selected_taxa],
            shared_xaxes=True,
            vertical_spacing=0.08
        )
        
        for idx, taxon in enumerate(selected_taxa, 1):
            taxon_df = taxon_agg[taxon_agg['name'] == taxon]
            
            # Individual trajectories
            for subj in taxon_df[self.subject_col].unique():
                subj_df = taxon_df[taxon_df[self.subject_col] == subj].sort_values(self.timepoint_col)
                fig.add_trace(go.Scatter(
                    x=subj_df[self.timepoint_col],
                    y=subj_df['rel_abundance'],
                    mode='lines+markers',
                    showlegend=False,
                    line=dict(width=1, color='steelblue'),
                    opacity=0.4,
                    hovertemplate=f"Subject: {subj}<br>Rel. Abd: %{{y:.2f}}%<extra></extra>"
                ), row=idx, col=1)
            
            # Mean trajectory
            mean_df = taxon_df.groupby(self.timepoint_col)['rel_abundance'].mean().reset_index()
            fig.add_trace(go.Scatter(
                x=mean_df[self.timepoint_col],
                y=mean_df['rel_abundance'],
                mode='lines+markers',
                name=taxon,
                line=dict(width=3, color='crimson'),
                marker=dict(size=10)
            ), row=idx, col=1)
            
            fig.update_yaxes(title_text="Rel. Abd (%)", row=idx, col=1)
        
        fig.update_layout(
            title="Taxon Abundance Tracking Over Time",
            template='plotly_white',
            height=200 + 150 * len(selected_taxa),
            showlegend=False
        )
        fig.update_xaxes(title_text=self.timepoint_col.replace('_', ' ').title(), row=len(selected_taxa), col=1)
        
        fig.show()
        print(f"✅ Tracked {len(selected_taxa)} taxa across {taxon_agg[self.subject_col].nunique()} subjects")
    
    def _plot_changepoint_detection(self, diversity_df: pd.DataFrame, metric: str, sensitivity: int, filter_suffix: str = "") -> None:
        """Detect and visualize change points in diversity."""
        threshold = 2.0 / sensitivity  # Higher sensitivity = lower threshold
        
        print(f"📍 Detecting change points (sensitivity={sensitivity})...")
        
        results = []
        for subj in diversity_df[self.subject_col].unique():
            subj_df = diversity_df[diversity_df[self.subject_col] == subj].sort_values(self.timepoint_col)
            if len(subj_df) < 3:
                continue
            
            values = subj_df[metric].values
            timepoints_subj = subj_df[self.timepoint_col].values
            
            # Simple change-point: z-score of differences
            diffs = np.diff(values)
            if len(diffs) > 1 and np.std(diffs) > 0:
                z_scores = np.abs(diffs - np.mean(diffs)) / np.std(diffs)
                
                for i, (z, tp) in enumerate(zip(z_scores, timepoints_subj[1:])):
                    if z > threshold:
                        results.append({
                            self.subject_col: subj,
                            'timepoint': tp,
                            'change': diffs[i],
                            'z_score': z,
                            'prev_value': values[i],
                            'new_value': values[i+1]
                        })
        
        if not results:
            print(f"ℹ️ No significant change points detected at sensitivity {sensitivity}")
            print("   Try increasing sensitivity or check if your data has enough variation")
            return
        
        cp_df = pd.DataFrame(results)
        
        # Visualization
        fig = make_subplots(rows=1, cols=2, subplot_titles=[
            'Change Points by Timepoint',
            'Change Magnitude Distribution'
        ])
        
        # Count change points per timepoint
        cp_counts = cp_df.groupby('timepoint').size().reset_index(name='count')
        fig.add_trace(go.Bar(
            x=cp_counts['timepoint'],
            y=cp_counts['count'],
            marker_color='coral',
            hovertemplate="Timepoint: %{x}<br>Change points: %{y}<extra></extra>"
        ), row=1, col=1)
        
        # Change magnitude histogram
        fig.add_trace(go.Histogram(
            x=cp_df['change'],
            nbinsx=20,
            marker_color='steelblue',
            showlegend=False
        ), row=1, col=2)
        
        metric_names = {'richness': 'Richness', 'shannon': "Shannon Index"}
        fig.update_layout(
            title=f"Change-Point Detection in {metric_names[metric]}{filter_suffix}",
            template='plotly_white',
            height=400
        )
        fig.update_xaxes(title_text=self.timepoint_col.title(), row=1, col=1)
        fig.update_yaxes(title_text="# of Change Points", row=1, col=1)
        fig.update_xaxes(title_text=f"Change in {metric_names[metric]}", row=1, col=2)
        fig.update_yaxes(title_text="Count", row=1, col=2)
        
        fig.show()
        
        print(f"\n📊 Change-Point Summary:")
        print(f"   Total change points detected: {len(cp_df)}")
        print(f"   Subjects with changes: {cp_df[self.subject_col].nunique()}")
        print(f"   Most common timepoint: {cp_counts.loc[cp_counts['count'].idxmax(), 'timepoint']}")
        
        # Show top changes
        print(f"\n🔝 Top 5 largest changes:")
        top_changes = cp_df.nlargest(5, 'z_score')
        for _, row in top_changes.iterrows():
            direction = "📈" if row['change'] > 0 else "📉"
            print(f"   {direction} Subject {row[self.subject_col]} at {row['timepoint']}: "
                  f"{row['prev_value']:.2f} → {row['new_value']:.2f} (Δ={row['change']:+.2f})")
    
    # --- Public API ---
    
    def run(self) -> None:
        """
        Detect required columns and display the interactive UI.
        
        This is the main entry point for using the LongitudinalAnalysisManager.
        Call this method to show the interactive longitudinal analysis widget.
        """
        if not self._initialize_data():
            # Show missing fields message
            display(self._create_missing_fields_ui())
            return
        
        print(f"✅ Longitudinal columns detected:")
        print(f"   Subject ID: '{self.subject_col}' ({len(self.subjects)} unique subjects)")
        print(f"   Timepoint: '{self.timepoint_col}' ({len(self.timepoints)} unique timepoints)")
        print()
        
        ui = self._create_ui()
        display(ui)


# Canonical iDesign name for this engine.
LongitudinalAnalysisEngine = LongitudinalAnalysisManager
