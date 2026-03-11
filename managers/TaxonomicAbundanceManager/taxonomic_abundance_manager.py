import pandas as pd
import numpy as np
import plotly.express as px
from ipywidgets import Dropdown, VBox, HBox, Button, Output, HTML, Layout
from IPython.display import display, clear_output
from typing import Set

class TaxonomicAbundanceManager:
    """
    Simplified Manager for interactive taxonomic abundance analysis.
    Calculates relative abundance for a specific taxon and plots its distribution.
    """

    def __init__(self, enriched_df: pd.DataFrame, original_columns: Set[str]):
        self.df = enriched_df
        
        # Identify metadata columns for grouping
        self.metadata_cols = [c for c in self.df.columns if c not in original_columns 
                              and c not in ['tax_id', 'rank', 'name', 'ileft', 'iright', 'acc', 'total_count']]
        self.cat_cols = [c for c in self.metadata_cols if pd.api.types.is_string_dtype(self.df[c])]
        
        # Extract available ranks dynamically, keeping standard order
        standard_order = ['superkingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
        existing_ranks = self.df['rank'].str.lower().dropna().unique()
        self.available_ranks = [r for r in standard_order if r in existing_ranks]
        
        self._output_area = Output()

    def _calculate_abundance(self, rank: str, taxon: str) -> pd.DataFrame:
        """Calculates relative abundance of a chosen taxon per sample."""
        # 1. Filter DataFrame to the selected rank
        rank_df = self.df[self.df['rank'].str.lower() == rank.lower()]
        
        # 2. Total abundance per sample at this rank
        total_counts = rank_df.groupby('acc')['total_count'].sum().rename('total_sample_reads')
        
        # 3. Specific taxon abundance per sample
        taxon_df = rank_df[rank_df['name'] == taxon]
        taxon_counts = taxon_df.groupby('acc')['total_count'].sum().rename('taxon_reads')
        
        # 4. Merge and calculate relative abundance
        all_samples = self.df[['acc']].drop_duplicates().set_index('acc')
        plot_df = all_samples.join(total_counts).join(taxon_counts).fillna(0)
        
        plot_df['relative_abundance'] = np.where(
            plot_df['total_sample_reads'] > 0,
            plot_df['taxon_reads'] / plot_df['total_sample_reads'],
            0.0
        )
        
        # 5. Bring in metadata
        plot_df = plot_df.reset_index().rename(columns={'acc': 'sample'})
        if self.metadata_cols:
            meta = self.df[['acc'] + self.metadata_cols].drop_duplicates().rename(columns={'acc': 'sample'})
            plot_df = plot_df.merge(meta, on='sample', how='left')
            
        return plot_df

    def _create_ui(self) -> VBox:
        # --- UI Controls ---
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

        # --- Interactivity ---
        def update_taxa_options(*args):
            """Refresh taxon list when rank changes."""
            if not rank_dropdown.value:
                return
            rank_df = self.df[self.df['rank'].str.lower() == rank_dropdown.value.lower()]
            taxa_list = sorted(rank_df['name'].dropna().unique())
            taxon_dropdown.options = taxa_list
            if taxa_list:
                taxon_dropdown.value = taxa_list[0]
                
        rank_dropdown.observe(update_taxa_options, names='value')
        update_taxa_options() # Populate initially

        def on_plot_click(*args):
            with self._output_area:
                clear_output(wait=True)
                r = rank_dropdown.value
                t = taxon_dropdown.value
                g = group_dropdown.value if group_dropdown.value != 'None' else None
                
                if not r or not t:
                    print("⚠️ Please select both a rank and a taxon.")
                    return
                    
                df_plot = self._calculate_abundance(r, t)
                title = f"Relative Abundance of <i>{t}</i> ({r.title()})"
                
                # --- FIX: Dynamic Y-axis formatting based on data size ---
                max_val = df_plot['relative_abundance'].max()
                if max_val == 0:
                    tick_fmt = ".2%"
                elif max_val < 0.0001:  # extremely small (< 0.01%)
                    tick_fmt = ".4e"    # Scientific notation
                elif max_val < 0.01:    # small (< 1%)
                    tick_fmt = ".4%"    # Show 4 decimal places
                else:
                    tick_fmt = ".2%"    # Default 2 decimal places
                
                # --- Plotting Logic ---
                if g:
                    df_plot = df_plot.sort_values(g)
                    fig = px.box(
                        df_plot, x=g, y='relative_abundance', color=g,
                        points='all', hover_data=['sample', 'taxon_reads', 'total_sample_reads'],
                        title=title, template='plotly_white', height=500
                    )
                else:
                    df_plot = df_plot.sort_values('relative_abundance', ascending=False)
                    fig = px.bar(
                        df_plot, x='sample', y='relative_abundance',
                        hover_data=['taxon_reads', 'total_sample_reads'],
                        title=title, template='plotly_white', height=500
                    )
                    fig.update_xaxes(
                        showticklabels=True, 
                        tickangle=-45, 
                        type='category', 
                        title_text="Sample ID"
                    )
                    
                fig.update_layout(yaxis_title="Relative Abundance", yaxis_tickformat=tick_fmt)
                fig.show()

                # --- NEW: Display Data Table ---
                print("\n📋 Data Summary Table:")
                
                # Filter down to the exact columns requested and rename them for readability
                table_df = df_plot[['sample', 'total_sample_reads', 'taxon_reads', 'relative_abundance']].copy()
                table_df.rename(columns={
                    'sample': 'Sample ID (SRR)',
                    'total_sample_reads': 'Total Sample Reads',
                    'taxon_reads': 'Taxon Reads',
                    'relative_abundance': 'Relative Abundance'
                }, inplace=True)
                
                # Format the relative abundance as a string with 6 decimal places for clarity in the table
                table_df['Relative Abundance'] = table_df['Relative Abundance'].apply(lambda x: f"{x:.6%}")
                
                # Display the table (Jupyter will render it nicely)
                display(table_df)

        plot_btn.on_click(on_plot_click)

        # --- Layout ---
        header = HTML(
            "<div style='background: #4A90E2; padding: 15px; border-radius: 8px; margin-bottom: 15px;'>"
            "<h3 style='color: white; margin: 0;'>🔬 Single Taxon Abundance</h3>"
            "<p style='color: #E2E8F0; margin: 5px 0 0 0; font-size: 13px;'>"
            "Select a specific taxonomy to view its relative abundance across samples.</p></div>"
        )
        
        controls = HBox([rank_dropdown, taxon_dropdown, group_dropdown], layout=Layout(margin='0 0 10px 0'))
        
        return VBox([header, controls, plot_btn, self._output_area])

    def run(self):
        display(self._create_ui())