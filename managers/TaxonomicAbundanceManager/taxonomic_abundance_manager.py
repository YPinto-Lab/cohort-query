import pandas as pd
import numpy as np
import plotly.express as px
from ipywidgets import Dropdown, VBox, HBox, Button, Output, HTML, Layout
from IPython.display import display, clear_output
from typing import Set

class TaxonomicAbundanceManager:
    """
    Manager for interactive taxonomic abundance analysis.
    Calculates relative abundance, visualizes distribution, generates 
    prevalence summaries, and allows CSV exporting.
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
        
        # State variables for exporting
        self.current_export_df = None
        self.current_taxon_name = "taxon"

    def _calculate_abundance(self, rank: str, taxon: str) -> pd.DataFrame:
        """Calculates relative abundance of a chosen taxon per sample."""
        rank_df = self.df[self.df['rank'].str.lower() == rank.lower()]
        total_counts = rank_df.groupby('acc')['total_count'].sum().rename('total_sample_reads')
        
        taxon_df = rank_df[rank_df['name'] == taxon]
        taxon_counts = taxon_df.groupby('acc')['total_count'].sum().rename('taxon_reads')
        
        all_samples = self.df[['acc']].drop_duplicates().set_index('acc')
        plot_df = all_samples.join(total_counts).join(taxon_counts).fillna(0)
        
        plot_df['relative_abundance'] = np.where(
            plot_df['total_sample_reads'] > 0,
            plot_df['taxon_reads'] / plot_df['total_sample_reads'],
            0.0
        )
        
        plot_df = plot_df.reset_index().rename(columns={'acc': 'sample'})
        
        return plot_df

    def _create_ui(self) -> VBox:
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
            rank_df = self.df[self.df['rank'].str.lower() == rank_dropdown.value.lower()]
            taxa_list = sorted(rank_df['name'].dropna().unique())
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
                    
        export_btn.on_click(on_export_click)

        def on_plot_click(*args):
            with self._output_area:
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
                    
                valid_extras = [col for col in extra_columns if col in self.df.columns]
                if valid_extras:
                    meta_df = self.df[['acc'] + valid_extras].drop_duplicates().rename(columns={'acc': 'sample'})
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

        plot_btn.on_click(on_plot_click)

        header = HTML(
            "<div style='background: #4A90E2; padding: 15px; border-radius: 8px; margin-bottom: 15px;'>"
            "<h3 style='color: white; margin: 0;'>🔬 Single Taxon Abundance</h3>"
            "<p style='color: #E2E8F0; margin: 5px 0 0 0; font-size: 13px;'>"
            "Select a specific taxonomy to view its relative abundance across samples.</p></div>"
        )
        
        controls = HBox([rank_dropdown, taxon_dropdown, group_dropdown], layout=Layout(margin='0 0 10px 0'))
        buttons = HBox([plot_btn, export_btn], layout=Layout(margin='0 0 15px 0', align_items='center'))
        
        return VBox([header, controls, buttons, self._output_area])

    def run(self):
        display(self._create_ui())