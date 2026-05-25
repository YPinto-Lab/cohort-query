"""End-to-end CLI test for Ask-SLM.

This test intentionally uses very small mock data to keep each row meaningful
as an explicit test case while still validating the full CLI workflow.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

# Support direct execution from IDEs (Play/Debug) where cwd may be tests/e2e.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Common.contracts.sra_schema import SRAMetadataSchema


@dataclass(frozen=True)
class WorkspaceContext:
    view_name: str
    repo_root: Path
    workspace_root: Path
    workspace_dir: Path
    workspace_inputs: Path
    workspace_configs: Path
    workspace_results: Path
    expected_root: Path


@dataclass(frozen=True)
class ExpectedOutputRefs:
    abundance_matrix: Path
    alpha_diversity: Path
    taxonomic_abundance: Path
    taxonomic_abundance_summary: Path
    metadata_overview_summary: Path
    metadata_overview_projects: Path
    metadata_overview_discovered_by_project: Path
    metadata_overview_discovered_unique: Path
    metadata_matrix: Path


class TestCliEndToEnd(unittest.TestCase):
    """Single E2E test that executes all CLI capabilities on mock data."""

    # Visible repository location for preserved artifacts.
    ARTIFACTS_DIR = REPO_ROOT / "tests" / "e2e" / "artifacts"

    # Keep generated test artifacts after a successful run when debugging locally.
    # Default is False so CI and normal local runs stay clean.
    KEEP_ARTIFACTS_ON_SUCCESS = True

    # Always keep artifacts on failure to make debugging straightforward.
    KEEP_ARTIFACTS_ON_FAILURE = True

    def test_cli_end_to_end_all_capabilities(self) -> None:
        # Arrange
        repo_root = Path(__file__).resolve().parents[2]
        keep_artifacts = self.KEEP_ARTIFACTS_ON_SUCCESS
        run_started = time.time()

        self._run_log = {
            "started_at": run_started,
            "status": "running",
            "commands": [],
            "checkpoints": [],
            "error": None,
        }

        tmp_path = Path(tempfile.mkdtemp(prefix="ask_slm_e2e_"))

        try:
            context = self._prepare_workspace(tmp_path, repo_root)
            expected = self._write_expected_outputs(context.expected_root)

            self._run_abundance_matrix(context, expected)
            self._run_metadata_overview_workspace(context)
            self._run_metadata_overview_overrides(context)
            self._run_metadata_overview(context, expected)
            self._run_build_taxonomy_lineage(context)
            self._run_alpha_diversity(context, expected)
            self._run_taxonomic_abundance(context, expected)
            self._run_log["status"] = "passed"
        except Exception:
            # Never delete artifacts on failure to make debugging straightforward.
            keep_artifacts = self.KEEP_ARTIFACTS_ON_FAILURE
            self._run_log["status"] = "failed"
            self._run_log["error"] = str(sys.exc_info()[1])
            raise
        finally:
            self._write_run_log(tmp_path, run_started)

            if keep_artifacts:
                self.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                target_path = self.ARTIFACTS_DIR / self._artifact_folder_name(run_started)
                try:
                    if target_path.exists():
                        shutil.rmtree(target_path, ignore_errors=True)
                    shutil.copytree(tmp_path, target_path)
                    print(f"\n[ask-slm e2e] Kept test artifacts at: {target_path}")
                except Exception as copy_err:
                    # Do not break the test outcome because of artifact copy failures.
                    print(f"\n[ask-slm e2e] Failed to copy artifacts to repo folder: {copy_err}")
                    print(f"[ask-slm e2e] Artifacts still available in temp: {tmp_path}")
                finally:
                    shutil.rmtree(tmp_path, ignore_errors=True)
            else:
                shutil.rmtree(tmp_path, ignore_errors=True)

    def _add_checkpoint(self, name: str, status: str, details: str) -> None:
        self._run_log["checkpoints"].append(
            {
                "name": name,
                "status": status,
                "details": details,
                "timestamp": time.time(),
            }
        )

    def _write_run_log(self, root: Path, run_started: float) -> None:
        """Write a condensed, human-readable run log to disk using small helpers."""
        run_ended = time.time()
        lines = []
        lines += self._run_log_header(run_started, run_ended, root)
        lines += self._run_log_checkpoints(root)
        lines += self._run_log_commands(root)
        (root / "test_run.log").write_text("\n".join(lines), encoding="utf-8")

    def _run_log_header(self, run_started: float, run_ended: float, root: Path) -> list[str]:
        status = self._run_log.get("status", "unknown")
        status_emoji = {"passed": "✅", "failed": "❌", "running": "⏳"}.get(status, "ℹ️")
        total = run_ended - run_started
        return [
            "🧪 Ask-SLM E2E Test Run Log",
            "=" * 80,
            f"{status_emoji} Status: {status}",
            f"🕒 Started: {self._format_timestamp(self._run_log.get('started_at', run_started))} (epoch {self._run_log.get('started_at', run_started):.3f})",
            f"🕓 Ended: {self._format_timestamp(run_ended)} (epoch {run_ended:.3f})",
            f"⏱️ Total Duration (s): {total:.3f}",
            f"🧭 Path Alias: <TMP_RUN_DIR> = {root}",
            f"🧭 Path Alias: <REPO_ROOT> = {REPO_ROOT}",
        ]

    def _run_log_checkpoints(self, root: Path) -> list[str]:
        lines = ["", "📍 Checkpoints", "-" * 80]
        for cp in self._run_log.get("checkpoints", []):
            cp_status = cp.get("status", "").lower()
            cp_emoji = {"passed": "✅", "failed": "❌", "running": "⏳"}.get(cp_status, "ℹ️")
            lines.append(f"{cp_emoji} [{cp.get('status','').upper()}] {cp.get('name','')} @ {self._format_timestamp(cp.get('timestamp',0))} (epoch {cp.get('timestamp',0):.3f})")
            lines.append(f"  {self._shorten_text(cp.get('details',''), root)}")
        return lines

    def _run_log_commands(self, root: Path) -> list[str]:
        lines = ["", "🛠️ Commands", "-" * 80]
        for i, cmd in enumerate(self._run_log.get("commands", []), start=1):
            lines.append(f"{i}. {self._shorten_text(cmd.get('command',''), root)}")
            lines.append(f"   📁 cwd: {self._shorten_text(cmd.get('cwd',''), root)}")
            lines.append(f"   🕒 start: {self._format_timestamp(cmd.get('start_epoch',0))} (epoch {cmd.get('start_epoch',0):.3f})")
            lines.append(f"   🕓 end: {self._format_timestamp(cmd.get('end_epoch',0))} (epoch {cmd.get('end_epoch',0):.3f})")
            lines.append(f"   ⏱️ duration_s: {cmd.get('duration_s',0):.3f}")
            lines.append(f"   🔢 return_code: {cmd.get('return_code',0)}")
            if cmd.get("issues"):
                lines.append(f"   ⚠️ issues: {cmd.get('issues')}")
            lines.append("   📤 stdout:")
            lines.extend([f"     {line}" for line in self._shorten_text(cmd.get("stdout",""), root).splitlines()])
            lines.append("   📥 stderr:")
            lines.extend([f"     {line}" for line in self._shorten_text(cmd.get("stderr",""), root).splitlines()])
            lines.append("")
        return lines

    def _format_timestamp(self, epoch_seconds: float) -> str:
        """Convert epoch seconds to local human-readable timestamp with milliseconds."""
        dt = datetime.fromtimestamp(epoch_seconds)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _artifact_folder_name(self, run_started: float) -> str:
        """Create a stable timestamped folder name for preserved artifacts."""
        return datetime.fromtimestamp(run_started).strftime("%Y-%m-%d_%H-%M-%S_%f")

    def _shorten_text(self, text: str, tmp_root: Path) -> str:
        """Shorten long absolute paths to readable aliases in logs."""
        shortened = text.replace(str(tmp_root), "<TMP_RUN_DIR>")
        shortened = shortened.replace(str(REPO_ROOT), "<REPO_ROOT>")
        return shortened

    def _determine_issues(self, result: subprocess.CompletedProcess) -> str:
        if result.returncode != 0:
            return "non-zero exit code"
        stderr = (result.stderr or "").lower()
        if "traceback" in stderr or "error" in stderr:
            return "stderr contains error-like text"
        return ""

    def _run_cli(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        """Run CLI command, record metadata, and fail on error."""
        start = time.time()
        result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
        end = time.time()
        issues = self._determine_issues(result)
        self._record_command(" ".join(cmd), str(cwd), start, end, result, issues)
        if result.returncode != 0:
            joined = " ".join(cmd)
            self.fail(f"CLI command failed.\nCommand: {joined}\nExit code: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n")
        return result

    def _record_command(self, command: str, cwd: str, start: float, end: float, result: subprocess.CompletedProcess, issues: str) -> None:
        self._run_log["commands"].append({
            "command": command,
            "cwd": cwd,
            "start_epoch": start,
            "end_epoch": end,
            "duration_s": end - start,
            "return_code": result.returncode,
            "issues": issues,
            "stdout": result.stdout,
            "stderr": result.stderr,
        })

    def _assert_dataframes_close(
        self,
        actual: pd.DataFrame,
        expected: pd.DataFrame,
        float_cols: list[str],
        tol: float = 1e-6,
    ) -> None:
        """Compare two DataFrames with tolerance for numeric float columns."""
        self.assertEqual(
            list(actual.columns),
            list(expected.columns),
            f"Column mismatch. actual={list(actual.columns)} expected={list(expected.columns)}",
        )
        self.assertEqual(len(actual), len(expected), "Row count mismatch")

        for col in actual.columns:
            if col in float_cols:
                diff = (actual[col].astype(float) - expected[col].astype(float)).abs().max()
                self.assertLessEqual(diff, tol, f"Float column '{col}' mismatch. max diff={diff}")
            else:
                self.assertListEqual(
                    actual[col].tolist(),
                    expected[col].tolist(),
                    f"Column '{col}' mismatch",
                )

    def _canonicalize_matrix_df(self, df: pd.DataFrame, index_col: str) -> pd.DataFrame:
        """Sort matrix rows and columns for stable order-insensitive comparisons."""
        non_index_cols = sorted([c for c in df.columns if c != index_col])
        canonical = df[[index_col] + non_index_cols].sort_values(index_col).reset_index(drop=True)
        return canonical

    def _write_mock_metadata_csv(self, path: Path) -> None:
        """Create a minimal, schema-valid metadata.csv fixture (concise builder)."""
        rows = self._mock_metadata_rows()
        pd.DataFrame(rows).to_csv(path, index=False)

    def _mock_metadata_rows(self) -> list[dict]:
        cols = list(SRAMetadataSchema.__fields__.keys())

        def make_row(acc, group, sex, age, subj, tp, body, host, batch):
            row = {c: "" for c in cols}
            row.update({"acc": acc, "bioproject": "PRJTEST1", "assay_type": "WGS", "sample_name": acc, "platform": "ILLUMINA", "mbytes": 0, "avgspotlen": 0, "mbases": 0, "insertsize": "0", "jattr": json.dumps({"group": group, "sex": sex, "age_group": age, "subject_id": subj, "timepoint": tp}), "attributes": f"k=body_site, v={body}}}k=host_state, v={host}}}k=sequencing_batch, v={batch}}}"})
            return row
        return [
            make_row("SRR0001", "Case", "female", "adult", "SUBJ_1", "baseline", "gut", "healthy", "batch_1"),
            make_row("SRR0002", "Case", "male", "senior", "SUBJ_2", "followup", "blood", "diseased", "batch_2"),
            make_row("SRR0003", "Control", "female", "adult", "SUBJ_3", "baseline", "gut", "healthy", "batch_1"),
        ]

    def _expand_mock_metadata_matrix_rows(self) -> pd.DataFrame:
        """Build the expected metadata matrix from mock metadata inputs."""
        base_cols = [c for c in SRAMetadataSchema.__fields__.keys() if c not in {"jattr", "attributes"}]
        rows = []
        for row in self._mock_metadata_rows():
            jattr_data = json.loads(row["jattr"])
            attrs = dict(re.findall(r"k=([^,]+), v=([^}]+)", row["attributes"]))
            expanded = {c: row.get(c, "") for c in base_cols}
            expanded["Group"] = jattr_data.get("group", "")
            for key in ["group", "sex", "age_group", "subject_id", "timepoint"]:
                expanded[key] = jattr_data.get(key, "")
            for key in ["body_site", "host_state", "sequencing_batch"]:
                expanded[key] = attrs.get(key, "")
            rows.append(expanded)

        df = pd.DataFrame(rows)
        ordered_cols = ["acc"] + [c for c in df.columns if c != "acc"]
        return df[ordered_cols]

    def _write_mock_taxonomy_csv(self, path: Path) -> None:
        """Create a tiny taxonomy.csv with multiple ranks and generic lineage names."""
        rows = self._generate_taxonomy_rows()
        for r in rows:
            r["self_count"] = max(int(r["total_count"]) - 1, 0)
            r["bioproject"] = "PRJTEST1"
        pd.DataFrame(rows).to_csv(path, index=False)

    def _generate_taxonomy_rows(self) -> list[dict]:
        samples = {
            "SRR0001": [
                (9000, "superkingdom", "Some super kingdom", 100, 1, 1, 20),
                (9001, "phylum", "Some phylum", 100, 2, 2, 19),
                (9002, "class", "Some class", 100, 3, 3, 18),
                (9003, "order", "Some order", 100, 4, 4, 17),
                (9004, "family", "Some family", 100, 5, 5, 16),
                (1001, "genus", "Some genus 1", 30, 6, 6, 10),
                (1002, "genus", "Some genus 2", 70, 6, 11, 15),
            ],
            "SRR0002": [
                (9000, "superkingdom", "Some super kingdom", 100, 1, 1, 16),
                (9001, "phylum", "Some phylum", 100, 2, 2, 15),
                (9002, "class", "Some class", 100, 3, 3, 14),
                (9003, "order", "Some order", 100, 4, 4, 13),
                (9004, "family", "Some family", 100, 5, 5, 12),
                (1002, "genus", "Some genus 2", 100, 6, 6, 11),
            ],
            "SRR0003": [
                (9000, "superkingdom", "Some super kingdom", 100, 1, 1, 20),
                (9001, "phylum", "Some phylum", 100, 2, 2, 19),
                (9002, "class", "Some class", 100, 3, 3, 18),
                (9003, "order", "Some order", 100, 4, 4, 17),
                (9004, "family", "Some family", 100, 5, 5, 16),
                (1001, "genus", "Some genus 1", 40, 6, 6, 10),
                (1003, "genus", "Some genus 3", 60, 6, 11, 15),
            ],
        }
        rows = []
        for acc, items in samples.items():
            for tax_id, rank, name, total, ilevel, ileft, iright in items:
                rows.append({"acc": acc, "tax_id": tax_id, "rank": rank, "name": name, "total_count": total, "ilevel": ilevel, "ileft": ileft, "iright": iright})
        return rows

    def _write_mock_mapping_config(self, path: Path) -> None:
        """Map jattr.group into the canonical Group column used by CLI grouping."""
        config = {
            "project_id": "PRJTEST1",
            "filters": {"exclude_project": False, "sample_filters": []},
            "mappings": {
                "Group": {
                    "key_name": "group",
                    "value_mappings": {},
                }
            },
            "description": "Tiny E2E test mapping",
        }
        path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # ---- High-level test helpers (keep short) ---------------------------------
    def _prepare_workspace(self, tmp_path: Path, repo_root: Path) -> WorkspaceContext:
        view_name = "MockView"
        workspace_root = tmp_path / "Workspaces"
        workspace_dir = workspace_root / view_name
        workspace_inputs = workspace_dir / "inputs"
        workspace_configs = workspace_dir / "mapping_configs"
        workspace_results = workspace_dir / "results"
        expected_root = tmp_path / "expected"
        for p in (expected_root, workspace_inputs, workspace_configs, workspace_results):
            p.mkdir(parents=True, exist_ok=True)
        self._write_mock_metadata_csv(workspace_inputs / "metadata.csv")
        self._write_mock_taxonomy_csv(workspace_inputs / "taxonomy.csv")
        self._write_mock_mapping_config(workspace_configs / "PRJTEST1.json")
        return WorkspaceContext(
            view_name=view_name,
            repo_root=repo_root,
            workspace_root=workspace_root,
            workspace_dir=workspace_dir,
            workspace_inputs=workspace_inputs,
            workspace_configs=workspace_configs,
            workspace_results=workspace_results,
            expected_root=expected_root,
        )

    def _run_abundance_matrix(self, context: WorkspaceContext, expected: ExpectedOutputRefs) -> None:
        cmd = [sys.executable, "askslm.py", "abundance-matrix", "--view", context.view_name, "--inputs-dir", str(context.workspace_inputs), "--config-dir", str(context.workspace_configs), "--output-dir", str(context.workspace_results), "--workspace-root", str(context.workspace_root)]
        res = self._run_cli(cmd, cwd=context.repo_root)
        out = context.workspace_results / "abundance_matrices" / "stage_04_final_assembly" / "abundance_matrix.csv"
        self.assertTrue(out.exists(), f"abundance_matrix.csv missing\nSTDOUT:\n{res.stdout}")
        actual = self._canonicalize_matrix_df(pd.read_csv(out), index_col="acc")
        expected_df = self._canonicalize_matrix_df(pd.read_csv(expected.abundance_matrix), index_col="acc")
        pd.testing.assert_frame_equal(actual, expected_df, check_dtype=False)
        self._add_checkpoint("abundance-matrix", "passed", f"Validated {out}")

    def _run_metadata_overview_workspace(self, context: WorkspaceContext) -> None:
        cmd = [sys.executable, "askslm.py", "metadata-overview", "--view", context.view_name, "--workspace-root", str(context.workspace_root)]
        self._run_cli(cmd, cwd=context.repo_root)
        out = context.workspace_results / "metadata-overview" / "metadata_overview_summary.csv"
        self.assertTrue(out.exists(), "Workspace metadata overview missing")
        self._add_checkpoint("metadata-overview-workspace-defaults", "passed", f"Validated workspace outputs in {out.parent}")

    def _run_metadata_overview_overrides(self, context: WorkspaceContext) -> None:
        cmd = [sys.executable, "askslm.py", "metadata-overview", "--view", context.view_name, "--inputs-dir", str(context.workspace_dir / "Inputs"), "--config-dir", str(context.workspace_configs), "--output-dir", str(context.workspace_results), "--workspace-root", str(context.workspace_root)]
        res = self._run_cli(cmd, cwd=context.repo_root)
        self.assertIn("Loading metadata from", res.stdout)
        self._add_checkpoint("metadata-overview-explicit-overrides", "passed", "Validated explicit overrides")

    def _run_metadata_overview(self, context: WorkspaceContext, expected: ExpectedOutputRefs) -> None:
        cmd = [sys.executable, "askslm.py", "metadata-overview", "--view", context.view_name, "--inputs-dir", str(context.workspace_inputs), "--config-dir", str(context.workspace_configs), "--output-dir", str(context.workspace_results), "--workspace-root", str(context.workspace_root)]
        self._run_cli(cmd, cwd=context.repo_root)
        summary = context.workspace_results / "metadata-overview" / "metadata_overview_summary.csv"
        projects = context.workspace_results / "metadata-overview" / "metadata_overview_projects.csv"
        metadata_matrix = context.workspace_results / "metadata-overview" / "metadata_matrix.csv"
        pd.testing.assert_frame_equal(pd.read_csv(summary), pd.read_csv(expected.metadata_overview_summary), check_dtype=False)
        pd.testing.assert_frame_equal(pd.read_csv(projects), pd.read_csv(expected.metadata_overview_projects), check_dtype=False)
        actual_matrix = self._canonicalize_matrix_df(pd.read_csv(metadata_matrix), index_col="acc")
        expected_matrix = self._canonicalize_matrix_df(pd.read_csv(expected.metadata_matrix), index_col="acc")
        pd.testing.assert_frame_equal(actual_matrix, expected_matrix, check_dtype=False)
        self._add_checkpoint("metadata-overview", "passed", "Validated metadata overview reports")

    def _run_build_taxonomy_lineage(self, context: WorkspaceContext) -> None:
        cmd = [sys.executable, "askslm.py", "build-taxonomy-lineage", "--view", context.view_name, "--inputs-dir", str(context.workspace_inputs), "--config-dir", str(context.workspace_configs), "--output-dir", str(context.workspace_results), "--workspace-root", str(context.workspace_root)]
        self._run_cli(cmd, cwd=context.repo_root)
        db = context.workspace_results / "abundance_matrices" / "stage_05_accessor" / "taxon_query_db.json"
        self.assertTrue(db.exists(), "lineage DB missing")
        self._add_checkpoint("build-taxonomy-lineage", "passed", f"Validated {db}")

    def _run_alpha_diversity(self, context: WorkspaceContext, expected: ExpectedOutputRefs) -> None:
        cmd = [sys.executable, "askslm.py", "alpha-diversity", "--view", context.view_name, "--rank", "genus", "--inputs-dir", str(context.workspace_inputs), "--config-dir", str(context.workspace_configs), "--output-dir", str(context.workspace_results), "--workspace-root", str(context.workspace_root)]
        res = self._run_cli(cmd, cwd=context.repo_root)
        out = context.workspace_results / "alpha_diversity" / "alpha_diversity.csv"
        self.assertTrue(out.exists(), f"alpha_diversity.csv missing\nSTDOUT:\n{res.stdout}")
        self._assert_dataframes_close(pd.read_csv(out), pd.read_csv(expected.alpha_diversity), float_cols=["shannon"])
        self._add_checkpoint("alpha-diversity", "passed", f"Validated {out}")

    def _run_taxonomic_abundance(self, context: WorkspaceContext, expected: ExpectedOutputRefs) -> None:
        cmd = [sys.executable, "askslm.py", "taxonomic-abundance", "--view", context.view_name, "--rank", "genus", "--taxon", "Some genus 1", "--inputs-dir", str(context.workspace_inputs), "--config-dir", str(context.workspace_configs), "--output-dir", str(context.workspace_results), "--workspace-root", str(context.workspace_root)]
        self._run_cli(cmd, cwd=context.repo_root)
        out = context.workspace_results / "taxonomic_abundance" / "taxonomic_abundance_Some_genus_1.csv"
        self.assertTrue(out.exists(), "taxonomic abundance CSV missing")
        self._assert_dataframes_close(pd.read_csv(out), pd.read_csv(expected.taxonomic_abundance), float_cols=["relative_abundance"])
        self._add_checkpoint("taxonomic-abundance", "passed", f"Validated {out}")

    def _write_expected_outputs(self, expected_root: Path) -> ExpectedOutputRefs:
        """Create expected CSV files for deterministic assertions and easy debugging."""
        abundance_matrix_df = self._expected_abundance_matrix()
        alpha_df = self._expected_alpha()
        abundance_df = self._expected_taxonomic_abundance()
        abundance_summary_df = self._expected_abundance_summary()
        metadata_summary_df = self._expected_metadata_summary()
        metadata_projects_df = pd.DataFrame({"bioproject": ["PRJTEST1"], "samples": [3]})
        metadata_discovered_by_project_df = self._expected_discovered_by_project()
        metadata_discovered_unique_df = self._expected_discovered_unique()
        metadata_matrix_df = self._expand_mock_metadata_matrix_rows()

        abundance_matrix_path = expected_root / "abundance_matrix.csv"
        alpha_path = expected_root / "alpha_diversity.csv"
        taxonomic_abundance_path = expected_root / "taxonomic_abundance_Some_genus_1.csv"
        abundance_summary_path = expected_root / "taxonomic_abundance_Some_genus_1_summary.csv"
        metadata_summary_path = expected_root / "metadata_overview_summary.csv"
        metadata_projects_path = expected_root / "metadata_overview_projects.csv"
        metadata_discovered_by_project_path = expected_root / "metadata_overview_discovered_keys_by_project.csv"
        metadata_discovered_unique_path = expected_root / "metadata_overview_discovered_keys_unique.csv"
        metadata_matrix_path = expected_root / "metadata_matrix.csv"

        abundance_matrix_df.to_csv(abundance_matrix_path, index=False)
        alpha_df.to_csv(alpha_path, index=False)
        abundance_df.to_csv(taxonomic_abundance_path, index=False)
        abundance_summary_df.to_csv(abundance_summary_path, index=False)
        metadata_summary_df.to_csv(metadata_summary_path, index=False)
        metadata_projects_df.to_csv(metadata_projects_path, index=False)
        metadata_discovered_by_project_df.to_csv(metadata_discovered_by_project_path, index=False)
        metadata_discovered_unique_df.to_csv(metadata_discovered_unique_path, index=False)
        metadata_matrix_df.to_csv(metadata_matrix_path, index=False)

        return ExpectedOutputRefs(
            abundance_matrix=abundance_matrix_path,
            alpha_diversity=alpha_path,
            taxonomic_abundance=taxonomic_abundance_path,
            taxonomic_abundance_summary=abundance_summary_path,
            metadata_overview_summary=metadata_summary_path,
            metadata_overview_projects=metadata_projects_path,
            metadata_overview_discovered_by_project=metadata_discovered_by_project_path,
            metadata_overview_discovered_unique=metadata_discovered_unique_path,
            metadata_matrix=metadata_matrix_path,
        )

    def _expected_abundance_matrix(self) -> pd.DataFrame:
        cols = [
            "acc",
            "class||Some class||9002",
            "family||Some family||9004",
            "genus||Some genus 1||1001",
            "genus||Some genus 2||1002",
            "genus||Some genus 3||1003",
            "order||Some order||9003",
            "phylum||Some phylum||9001",
            "superkingdom||Some super kingdom||9000",
        ]
        rows = [
            ["SRR0001", 100, 100, 30, 70, 0, 100, 100, 100],
            ["SRR0002", 100, 100, 0, 100, 0, 100, 100, 100],
            ["SRR0003", 100, 100, 40, 0, 60, 100, 100, 100],
        ]
        return pd.DataFrame(rows, columns=cols)

    def _expected_alpha(self) -> pd.DataFrame:
        return pd.DataFrame({"acc": ["SRR0001", "SRR0002", "SRR0003"], "richness": [2, 1, 2], "shannon": [0.6108643020548935, 0.0, 0.6730116670092565]})

    def _expected_taxonomic_abundance(self) -> pd.DataFrame:
        return pd.DataFrame({"acc": ["SRR0001", "SRR0002", "SRR0003"], "total_sample_reads": [100, 100, 100], "taxon_reads": [30.0, 0.0, 40.0], "relative_abundance": [0.3, 0.0, 0.4], "bioproject": ["PRJTEST1"] * 3})

    def _expected_abundance_summary(self) -> pd.DataFrame:
        return pd.DataFrame({"Cohort": ["All Combined"], "Total Samples (N)": [3], "Samples with 0 Reads": [1], "Samples with Non-Zero Reads (%)": ["66.67%"], "Mean Rel. Abundance": ["23.333333%"]})

    def _expected_metadata_summary(self) -> pd.DataFrame:
        return pd.DataFrame({"metric": ["samples", "projects", "metadata_columns", "mapped_columns_count", "mapped_columns", "discovered_source_keys_unique", "projects_with_discovered_source_keys"], "value": ["3", "1", str(len(SRAMetadataSchema.__fields__) + 1), "1", "Group", str(8 + (len(SRAMetadataSchema.__fields__) - 2)), "1"]})

    def _expected_discovered_by_project(self) -> pd.DataFrame:
        return pd.DataFrame({
            "project_id": ["PRJTEST1"] * 8,
            "source": ["from_jattr"] * 5 + ["from_attributes"] * 3,
            "key_name": ["age_group", "group", "sex", "subject_id", "timepoint", "body_site", "host_state", "sequencing_batch"],
            "unique_values_count": [2, 2, 2, 3, 2, 2, 2, 2],
            "top_values": ["adult | senior", "Case | Control", "female | male", "SUBJ_1 | SUBJ_2 | SUBJ_3", "baseline | followup", "gut | blood", "healthy | diseased", "batch_1 | batch_2"],
        })

    def _expected_discovered_unique(self) -> pd.DataFrame:
        return pd.DataFrame({
            "source": ["from_attributes"] * 3 + ["from_jattr"] * 5,
            "key_name": ["body_site", "host_state", "sequencing_batch", "age_group", "group", "sex", "subject_id", "timepoint"],
            "projects_count": [1] * 8,
            "projects": ["PRJTEST1"] * 8,
            "max_unique_values_count": [2, 2, 2, 2, 2, 2, 3, 2],
        })


if __name__ == "__main__":
    unittest.main()
