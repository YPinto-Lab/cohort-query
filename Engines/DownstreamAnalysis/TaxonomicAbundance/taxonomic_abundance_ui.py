import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd
import plotly.express as px
from IPython.display import clear_output, display
from ipywidgets import Button, Dropdown, HBox, HTML, Layout, Output, VBox

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None

from .taxonomic_abundance_logic import TaxonomicAbundanceLogic


@dataclass
class _UIContext:
    rank_dropdown: Dropdown
    taxon_dropdown: Dropdown
    group_dropdown: Dropdown
    source_key_dropdown: Dropdown
    remove_source_key_dropdown: Dropdown
    add_source_key_btn: Button
    remove_source_key_btn: Button
    clear_source_keys_btn: Button
    selected_keys_preview: HTML
    plot_btn: Button
    export_btn: Button
    selected_source_keys: List[str] = field(default_factory=list)


class TaxonomicAbundanceUIController:
    def __init__(self, logic: TaxonomicAbundanceLogic):
        self.logic = logic
        self._output_area = Output()
        self._plot_btn: Optional[Button] = None
        self._export_btn: Optional[Button] = None
        self._plot_click_cb = None
        self._export_click_cb = None
        self._is_plotting = False
        self._last_plot_click_ts = 0.0
        self._plot_debounce_seconds = 0.75
        self._last_render_signature = None
        self._controls_dirty = True
        self.current_export_df = None
        self.current_taxon_name = "taxon"

    def create_ui(self) -> VBox:
        self._output_area = Output()
        ctx = self._create_controls()
        self._wire_control_callbacks(ctx)
        self._wire_action_callbacks(ctx)
        self._refresh_selected_keys_controls(ctx)
        self._update_taxa_options(ctx)
        return self._compose_ui(ctx)

    def _create_controls(self) -> _UIContext:
        return _UIContext(
            rank_dropdown=Dropdown(options=self.logic.available_ranks, value=self._default_rank(), description="① Rank:", layout={"width": "250px"}),
            taxon_dropdown=Dropdown(options=[], description="② Taxon:", layout={"width": "300px"}),
            group_dropdown=Dropdown(options=["None"] + self.logic.cat_cols, value="None", description="③ Group By:", layout={"width": "250px"}),
            source_key_dropdown=Dropdown(options=self._source_key_options(), value="", description="④ Add Key:", layout=Layout(width="420px")),
            remove_source_key_dropdown=Dropdown(options=[("Selected key...", "")], value="", description="⑤ Remove:", layout=Layout(width="420px")),
            add_source_key_btn=Button(description="Add", button_style="info", layout=Layout(width="70px")),
            remove_source_key_btn=Button(description="Remove", button_style="warning", layout=Layout(width="80px")),
            clear_source_keys_btn=Button(description="Clear", button_style="", layout=Layout(width="70px")),
            selected_keys_preview=HTML("<span style='color:#666;'>Selected source keys: none</span>"),
            plot_btn=Button(description="Plot Abundance", button_style="primary", icon="bar-chart"),
            export_btn=Button(description="Export Raw Data", button_style="success", icon="download"),
        )

    def _default_rank(self) -> Optional[str]:
        if self.logic.available_ranks:
            return self.logic.available_ranks[-1]
        return None

    def _source_key_options(self):
        return [("Select source key...", "")] + [(k, k) for k in self.logic.source_keys]

    def _wire_control_callbacks(self, ctx: _UIContext):
        ctx.rank_dropdown.observe(lambda *_: self._update_taxa_options(ctx), names="value")
        ctx.rank_dropdown.observe(lambda *_: self._mark_controls_dirty(), names="value")
        ctx.taxon_dropdown.observe(lambda *_: self._mark_controls_dirty(), names="value")
        ctx.group_dropdown.observe(lambda *_: self._mark_controls_dirty(), names="value")
        ctx.add_source_key_btn.on_click(lambda *_: self._on_add_source_key(ctx))
        ctx.remove_source_key_btn.on_click(lambda *_: self._on_remove_source_key(ctx))
        ctx.clear_source_keys_btn.on_click(lambda *_: self._on_clear_source_keys(ctx))

    def _mark_controls_dirty(self):
        self._controls_dirty = True

    def _wire_action_callbacks(self, ctx: _UIContext):
        self._replace_export_callback(ctx.export_btn, lambda *_: self._on_export_click())
        self._replace_plot_callback(ctx.plot_btn, lambda *_: self._on_plot_click(ctx))

    def _replace_export_callback(self, btn: Button, callback):
        if self._export_btn is not None and self._export_click_cb is not None:
            self._export_btn.on_click(self._export_click_cb, remove=True)
        btn.on_click(callback)
        self._export_btn = btn
        self._export_click_cb = callback

    def _replace_plot_callback(self, btn: Button, callback):
        if self._plot_btn is not None and self._plot_click_cb is not None:
            self._plot_btn.on_click(self._plot_click_cb, remove=True)
        btn.on_click(callback)
        self._plot_btn = btn
        self._plot_click_cb = callback

    def _on_add_source_key(self, ctx: _UIContext):
        key = ctx.source_key_dropdown.value
        if not key or key in ctx.selected_source_keys:
            return
        ctx.selected_source_keys.append(key)
        self._refresh_selected_keys_controls(ctx)
        self._mark_controls_dirty()

    def _on_remove_source_key(self, ctx: _UIContext):
        key = ctx.remove_source_key_dropdown.value
        if not key or key not in ctx.selected_source_keys:
            return
        ctx.selected_source_keys.remove(key)
        ctx.remove_source_key_dropdown.value = ""
        self._refresh_selected_keys_controls(ctx)
        self._mark_controls_dirty()

    def _on_clear_source_keys(self, ctx: _UIContext):
        ctx.selected_source_keys.clear()
        ctx.remove_source_key_dropdown.value = ""
        self._refresh_selected_keys_controls(ctx)
        self._mark_controls_dirty()

    def _refresh_selected_keys_controls(self, ctx: _UIContext):
        if not ctx.selected_source_keys:
            ctx.selected_keys_preview.value = "<span style='color:#666;'>Selected source keys: none</span>"
            ctx.remove_source_key_dropdown.options = [("Selected key...", "")]
            return
        chips = " ".join([f"<code style='padding:2px 6px;background:#eef;border-radius:3px;'>{k}</code>" for k in ctx.selected_source_keys])
        ctx.selected_keys_preview.value = f"<span style='color:#333;'>Selected source keys:</span> {chips}"
        ctx.remove_source_key_dropdown.options = [("Selected key...", "")] + [(k, k) for k in ctx.selected_source_keys]

    def _update_taxa_options(self, ctx: _UIContext):
        rank = ctx.rank_dropdown.value
        if not rank:
            return
        taxa = self._taxa_for_rank(rank)
        ctx.taxon_dropdown.options = taxa
        if taxa:
            ctx.taxon_dropdown.value = taxa[0]

    def _taxa_for_rank(self, rank: str) -> List[str]:
        if self.logic._is_wide_mode:
            rank_df = self.logic.taxon_lookup_df[self.logic.taxon_lookup_df["rank"].astype(str).str.lower() == rank.lower()]
            return sorted(rank_df["name"].dropna().astype(str).unique())
        rank_df = self.logic.taxonomy_df[self.logic.taxonomy_df["rank"].str.lower() == rank.lower()]
        return sorted(rank_df["name"].dropna().astype(str).unique())

    def _compose_ui(self, ctx: _UIContext) -> VBox:
        header = self._build_header()
        controls = HBox([ctx.rank_dropdown, ctx.taxon_dropdown, ctx.group_dropdown], layout=Layout(margin="0 0 10px 0"))
        metadata_controls = self._build_metadata_controls(ctx)
        buttons = HBox([ctx.plot_btn, ctx.export_btn], layout=Layout(margin="0 0 15px 0", align_items="center"))
        return VBox([header, controls, metadata_controls, buttons, self._output_area])

    def _build_header(self) -> HTML:
        return HTML(
            "<div style='background: #4A90E2; padding: 15px; border-radius: 8px; margin-bottom: 15px;'>"
            "<h3 style='color: white; margin: 0;'>Single Taxon Abundance</h3>"
            "<p style='color: #E2E8F0; margin: 5px 0 0 0; font-size: 13px;'>"
            "Select a specific taxonomy to view its relative abundance across samples.</p></div>"
        )

    def _build_metadata_controls(self, ctx: _UIContext) -> VBox:
        add_row = HBox([ctx.source_key_dropdown, ctx.add_source_key_btn], layout=Layout(margin="0 0 6px 0", align_items="center"))
        remove_row = HBox([ctx.remove_source_key_dropdown, ctx.remove_source_key_btn, ctx.clear_source_keys_btn], layout=Layout(margin="0 0 6px 0", align_items="center"))
        children = [add_row, remove_row, ctx.selected_keys_preview]
        return VBox(children, layout=Layout(margin="0 0 10px 0"))

    def _on_export_click(self):
        if self.current_export_df is None:
            self._log_output("Please generate a plot before exporting.")
            return
        default_name = f"{self.current_taxon_name.replace(' ', '_')}_abundance.csv"
        save_path = self._choose_save_path(default_name)
        if not save_path:
            self._log_output("Export canceled.")
            return
        self.current_export_df.to_csv(save_path, index=False)
        self._log_output(f"Saved raw data to: {save_path}")

    def _choose_save_path(self, default_name: str) -> str:
        if tk is None or filedialog is None:
            return self._choose_save_path_cli(default_name)
        return self._choose_save_path_dialog(default_name)

    def _choose_save_path_dialog(self, default_name: str) -> str:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        save_path = filedialog.asksaveasfilename(title="Save Raw Abundance Data", initialdir=str(Path.cwd()), initialfile=default_name, defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        root.destroy()
        return save_path

    def _choose_save_path_cli(self, default_name: str) -> str:
        self._log_output("Native file dialog unavailable (_tkinter missing).")
        self._log_output(f"Enter a save path, or press Enter to use: {default_name}")
        typed = input("Save CSV path: ").strip()
        if typed:
            return typed
        return default_name

    def _on_plot_click(self, ctx: _UIContext):
        if self._plot_click_is_blocked():
            return
        self._set_plotting_state(ctx.plot_btn, True)
        try:
            self._render_plot(ctx)
        finally:
            self._set_plotting_state(ctx.plot_btn, False)

    def _plot_click_is_blocked(self) -> bool:
        now = time.monotonic()
        if (now - self._last_plot_click_ts) < self._plot_debounce_seconds:
            return True
        self._last_plot_click_ts = now
        return self._is_plotting

    def _set_plotting_state(self, plot_btn: Button, is_plotting: bool):
        self._is_plotting = is_plotting
        plot_btn.disabled = is_plotting

    def _render_plot(self, ctx: _UIContext):
        with self._output_area:
            clear_output(wait=True)
            params = self._read_plot_params(ctx)
            if not self._validate_plot_params(params):
                return
            if not self._render_needed(params):
                return
            self._render_from_params(params)
            self._last_render_signature = params["signature"]
            self._controls_dirty = False

    def _read_plot_params(self, ctx: _UIContext) -> dict:
        group = ctx.group_dropdown.value
        if group == "None":
            group = None
        selected = list(ctx.selected_source_keys)
        signature = (ctx.rank_dropdown.value, ctx.taxon_dropdown.value, group, tuple(selected))
        return {"rank": ctx.rank_dropdown.value, "taxon": ctx.taxon_dropdown.value, "group": group, "source_keys": selected, "signature": signature}

    def _validate_plot_params(self, params: dict) -> bool:
        if params["rank"] and params["taxon"]:
            return True
        print("Please select both a rank and a taxon.")
        return False

    def _render_needed(self, params: dict) -> bool:
        if self._controls_dirty:
            return True
        return self._last_render_signature != params["signature"]

    def _render_from_params(self, params: dict):
        df_plot, valid_extras = self.logic.build_plot_df(params["rank"], params["taxon"], params["group"], params["source_keys"])
        fig = self._build_figure(df_plot, params)
        fig.show()
        self._show_prevalence(df_plot, params["group"])
        table_df = self.logic.prepare_table(df_plot, params["group"], valid_extras, params["source_keys"])
        self.current_export_df = table_df.copy()
        self.current_taxon_name = params["taxon"]
        self._show_table(table_df)

    def _build_figure(self, df_plot: pd.DataFrame, params: dict):
        if params["group"]:
            fig = self._build_grouped_figure(df_plot, params)
            self._apply_yaxis(fig, df_plot)
            return fig
        fig = self._build_ungrouped_figure(df_plot, params)
        self._apply_yaxis(fig, df_plot)
        return fig

    def _build_grouped_figure(self, df_plot: pd.DataFrame, params: dict):
        group_col = params["group"]
        sorted_df = df_plot.sort_values(group_col).copy()
        counts = sorted_df[group_col].value_counts().to_dict()
        sorted_df["plot_label"] = sorted_df[group_col].apply(lambda x: f"{x}<br>(n={counts.get(x, 0)})")
        return px.box(sorted_df, x="plot_label", y="relative_abundance", color="plot_label", points="all", hover_data=["sample", "taxon_reads", "total_sample_reads"], title=self._plot_title(params), template="plotly_white", height=500, labels={"plot_label": group_col})

    def _build_ungrouped_figure(self, df_plot: pd.DataFrame, params: dict):
        sorted_df = df_plot.sort_values("relative_abundance", ascending=False)
        fig = px.bar(sorted_df, x="sample", y="relative_abundance", hover_data=["taxon_reads", "total_sample_reads"], title=self._plot_title(params), template="plotly_white", height=500)
        fig.update_xaxes(showticklabels=True, tickangle=-45, type="category", title_text="Sample ID")
        return fig

    def _plot_title(self, params: dict) -> str:
        return f"Relative Abundance of <i>{params['taxon']}</i> ({params['rank'].title()})"

    def _apply_yaxis(self, fig, df_plot: pd.DataFrame):
        tick_fmt = self._tick_format(df_plot["relative_abundance"].max())
        fig.update_layout(yaxis_title="Relative Abundance", yaxis_tickformat=tick_fmt)

    def _tick_format(self, max_val: float) -> str:
        if max_val == 0:
            return ".2%"
        if max_val < 0.0001:
            return ".4e"
        if max_val < 0.01:
            return ".4%"
        return ".2%"

    def _show_prevalence(self, df_plot: pd.DataFrame, group: Optional[str]):
        rows = []
        rows.extend(self.logic.group_summary_rows(df_plot, group))
        rows.append(self.logic.summary_row("All Combined", df_plot))
        print("\nPREVALENCE & SUMMARY STATISTICS:")
        display(pd.DataFrame(rows))

    def _show_table(self, table_df: pd.DataFrame):
        display_df = table_df.copy()
        display_df["Relative Abundance"] = display_df["Relative Abundance"].apply(lambda x: f"{x:.6%}")
        print("\nRAW DATA TABLE:")
        display(display_df)

    def _log_output(self, message: str):
        with self._output_area:
            print(message)

