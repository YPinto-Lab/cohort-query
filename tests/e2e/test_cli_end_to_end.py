"""End-to-end CLI test for Ask-SLM.

This test intentionally uses very small mock data to keep each row meaningful
as an explicit test case while still validating the full CLI workflow.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

# Support direct execution from IDEs (Play/Debug) where cwd may be tests/e2e.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from Common.contracts.sra_schema import SRAMetadataSchema


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

            view_name = "MockView"
            workspace_root = tmp_path / "Workspaces"
            workspace_dir = workspace_root / view_name
            workspace_inputs = workspace_dir / "inputs"
            workspace_configs = workspace_dir / "mapping_configs"
            workspace_results = workspace_dir / "results"
            expected_root = tmp_path / "expected"

            expected_root.mkdir(parents=True, exist_ok=True)
            workspace_inputs.mkdir(parents=True, exist_ok=True)
            workspace_configs.mkdir(parents=True, exist_ok=True)
            workspace_results.mkdir(parents=True, exist_ok=True)

            self._write_mock_metadata_csv(workspace_inputs / "metadata.csv")
            self._write_mock_taxonomy_csv(workspace_inputs / "taxonomy.csv")
            self._write_mock_mapping_config(workspace_configs / "PRJTEST1.json")
            expected_files = self._write_expected_outputs(expected_root)

            # Act + Assert: abundance-matrix
            abundance_cmd = [
                sys.executable,
                "askslm.py",
                "abundance-matrix",
                "--view",
                view_name,
                "--inputs-dir",
                str(workspace_inputs),
                "--config-dir",
                str(workspace_configs),
                "--output-dir",
                str(workspace_results),
            ]
            abundance_run = self._run_cli(abundance_cmd, cwd=repo_root)

            abundance_out = workspace_results / "abundance_matrix" / "abundance_matrix.csv"
            self.assertTrue(abundance_out.exists(), f"abundance_matrix.csv was not created.\nSTDOUT:\n{abundance_run.stdout}")
            self.assertIn("Shape: 3 samples", abundance_run.stdout, "Feature matrix shape summary missing from stdout")

            # Pivoted abundance matrix columns can arrive in different order by environment/pandas internals.
            # Compare canonicalized (sorted) columns/rows to keep test deterministic.
            abundance_actual = self._canonicalize_matrix_df(pd.read_csv(abundance_out), index_col="acc")
            abundance_expected = self._canonicalize_matrix_df(pd.read_csv(expected_files["abundance_matrix"]), index_col="acc")
            pd.testing.assert_frame_equal(
                abundance_actual,
                abundance_expected,
                check_dtype=False,
            )
            self._add_checkpoint("abundance-matrix", "passed", f"Validated {abundance_out}")

            # Act + Assert: metadata-overview in workspace-native mode (view + workspace-root only)
            workspace_metadata_cmd = [
                sys.executable,
                "askslm.py",
                "metadata-overview",
                "--view",
                view_name,
                "--workspace-root",
                str(workspace_root),
            ]
            workspace_metadata_run = self._run_cli(workspace_metadata_cmd, cwd=repo_root)

            workspace_metadata_dir = workspace_results / "metadata_overview"
            workspace_summary_out = workspace_metadata_dir / "metadata_overview_summary.csv"
            workspace_projects_out = workspace_metadata_dir / "metadata_overview_projects.csv"
            workspace_discovered_by_project_out = workspace_metadata_dir / "metadata_overview_discovered_keys_by_project.csv"
            workspace_discovered_unique_out = workspace_metadata_dir / "metadata_overview_discovered_keys_unique.csv"

            self.assertTrue(workspace_summary_out.exists(), "Workspace-mode metadata overview summary CSV was not created")
            self.assertTrue(workspace_projects_out.exists(), "Workspace-mode metadata overview projects CSV was not created")
            self.assertTrue(
                workspace_discovered_by_project_out.exists(),
                "Workspace-mode discovered-keys by-project CSV was not created",
            )
            self.assertTrue(
                workspace_discovered_unique_out.exists(),
                "Workspace-mode discovered-keys unique CSV was not created",
            )
            self.assertIn("Metadata Summary", workspace_metadata_run.stdout)

            # Ensure no duplicate <view> segment under workspace results.
            unexpected_workspace_nested = workspace_results / view_name / "metadata_overview"
            self.assertFalse(
                unexpected_workspace_nested.exists(),
                f"Unexpected nested workspace output folder found: {unexpected_workspace_nested}",
            )
            self._add_checkpoint(
                "metadata-overview-workspace-defaults",
                "passed",
                f"Validated workspace-native outputs in {workspace_metadata_dir}",
            )

            # Act + Assert: explicit path overrides with case-variant Inputs path.
            override_metadata_cmd = [
                sys.executable,
                "askslm.py",
                "metadata-overview",
                "--view",
                view_name,
                "--inputs-dir",
                str(workspace_dir / "Inputs"),
                "--config-dir",
                str(workspace_configs),
                "--output-dir",
                str(workspace_results),
            ]
            override_metadata_run = self._run_cli(override_metadata_cmd, cwd=repo_root)
            self.assertIn("Loading metadata from", override_metadata_run.stdout)
            self.assertIn("Metadata Summary", override_metadata_run.stdout)
            self._add_checkpoint(
                "metadata-overview-explicit-overrides",
                "passed",
                "Validated explicit overrides and case-insensitive inputs path handling",
            )

            # Act + Assert: metadata-overview
            metadata_cmd = [
                sys.executable,
                "askslm.py",
                "metadata-overview",
                "--view",
                view_name,
                "--inputs-dir",
                str(workspace_inputs),
                "--config-dir",
                str(workspace_configs),
                "--output-dir",
                str(workspace_results),
            ]
            metadata_run = self._run_cli(metadata_cmd, cwd=repo_root)

            metadata_summary_out = workspace_results / "metadata_overview" / "metadata_overview_summary.csv"
            metadata_projects_out = workspace_results / "metadata_overview" / "metadata_overview_projects.csv"
            metadata_discovered_by_project_out = workspace_results / "metadata_overview" / "metadata_overview_discovered_keys_by_project.csv"
            metadata_discovered_unique_out = workspace_results / "metadata_overview" / "metadata_overview_discovered_keys_unique.csv"

            self.assertTrue(metadata_summary_out.exists(), "Metadata overview summary CSV was not created")
            self.assertTrue(metadata_projects_out.exists(), "Metadata overview projects CSV was not created")
            self.assertTrue(metadata_discovered_by_project_out.exists(), "Metadata discovered-keys by-project CSV was not created")
            self.assertTrue(metadata_discovered_unique_out.exists(), "Metadata discovered-keys unique CSV was not created")
            self.assertIn("Metadata Summary", metadata_run.stdout, "Metadata summary text missing from stdout")
            self.assertIn("Discovered Source Keys", metadata_run.stdout, "Discovered source-keys text missing from stdout")

            pd.testing.assert_frame_equal(
                pd.read_csv(metadata_summary_out),
                pd.read_csv(expected_files["metadata_overview_summary"]),
                check_dtype=False,
            )
            pd.testing.assert_frame_equal(
                pd.read_csv(metadata_projects_out),
                pd.read_csv(expected_files["metadata_overview_projects"]),
                check_dtype=False,
            )
            discovered_by_project_df = pd.read_csv(metadata_discovered_by_project_out)
            discovered_unique_df = pd.read_csv(metadata_discovered_unique_out)
            self.assertIn("metadata", discovered_by_project_df["source"].dropna().unique().tolist())
            self.assertIn("metadata", discovered_unique_df["source"].dropna().unique().tolist())
            self._add_checkpoint(
                "metadata-overview",
                "passed",
                f"Validated {metadata_summary_out}, {metadata_projects_out}, and discovered-key reports",
            )

            # Act + Assert: build-taxonomy-lineage (required by alpha-diversity)
            lineage_cmd = [
                sys.executable,
                "askslm.py",
                "build-taxonomy-lineage",
                "--view",
                view_name,
                "--inputs-dir",
                str(workspace_inputs),
                "--config-dir",
                str(workspace_configs),
                "--output-dir",
                str(workspace_results),
            ]
            lineage_run = self._run_cli(lineage_cmd, cwd=repo_root)
            lineage_db_out = workspace_results / "_cache" / "taxonomy_lineage_db.json"
            lineage_stamp_out = workspace_results / "_cache" / "taxonomy_lineage_db_stamp.json"
            self.assertTrue(lineage_db_out.exists(), "taxonomy_lineage_db.json was not created")
            self.assertTrue(lineage_stamp_out.exists(), "taxonomy_lineage_db_stamp.json was not created")
            self.assertIn("Built taxonomy lineage DB", lineage_run.stdout)
            self._add_checkpoint("build-taxonomy-lineage", "passed", f"Validated {lineage_db_out}")

            # Act + Assert: alpha-diversity
            alpha_cmd = [
                sys.executable,
                "askslm.py",
                "alpha-diversity",
                "--view",
                view_name,
                "--rank",
                "genus",
                "--inputs-dir",
                str(workspace_inputs),
                "--config-dir",
                str(workspace_configs),
                "--output-dir",
                str(workspace_results),
            ]
            alpha_run = self._run_cli(alpha_cmd, cwd=repo_root)

            alpha_csv = workspace_results / "alpha_diversity" / "alpha_diversity.csv"
            alpha_html = workspace_results / "alpha_diversity" / "alpha_diversity.html"
            self.assertTrue(alpha_csv.exists(), f"alpha_diversity.csv was not created.\nSTDOUT:\n{alpha_run.stdout}")
            self.assertTrue(alpha_html.exists(), "alpha_diversity.html was not created")
            self.assertIn("Summary:", alpha_run.stdout, "Alpha diversity summary missing from stdout")

            self._assert_dataframes_close(
                actual=pd.read_csv(alpha_csv),
                expected=pd.read_csv(expected_files["alpha_diversity"]),
                float_cols=["shannon"],
            )
            self._add_checkpoint("alpha-diversity", "passed", f"Validated {alpha_csv}")

            # Act + Assert: taxonomic-abundance
            abundance_cmd = [
                sys.executable,
                "askslm.py",
                "taxonomic-abundance",
                "--view",
                view_name,
                "--rank",
                "genus",
                "--taxon",
                "Some genus 1",
                "--inputs-dir",
                str(workspace_inputs),
                "--config-dir",
                str(workspace_configs),
                "--output-dir",
                str(workspace_results),
            ]
            abundance_run = self._run_cli(abundance_cmd, cwd=repo_root)

            abundance_csv = workspace_results / "taxonomic_abundance" / "taxonomic_abundance_Some_genus_1.csv"
            abundance_summary_csv = workspace_results / "taxonomic_abundance" / "taxonomic_abundance_Some_genus_1_summary.csv"
            abundance_html = workspace_results / "taxonomic_abundance" / "taxonomic_abundance_Some_genus_1.html"

            self.assertTrue(abundance_csv.exists(), "Taxonomic abundance CSV was not created")
            self.assertTrue(abundance_summary_csv.exists(), "Taxonomic abundance summary CSV was not created")
            self.assertTrue(abundance_html.exists(), "Taxonomic abundance HTML was not created")
            self.assertIn("Prevalence Summary", abundance_run.stdout, "Prevalence summary text missing from stdout")

            self._assert_dataframes_close(
                actual=pd.read_csv(abundance_csv),
                expected=pd.read_csv(expected_files["taxonomic_abundance"]),
                float_cols=["relative_abundance"],
            )
            pd.testing.assert_frame_equal(
                pd.read_csv(abundance_summary_csv),
                pd.read_csv(expected_files["taxonomic_abundance_summary"]),
                check_dtype=False,
            )
            self._add_checkpoint("taxonomic-abundance", "passed", f"Validated {abundance_csv} and summary")
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
                target_path = self.ARTIFACTS_DIR / tmp_path.name
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
        """Write a human-readable run log inside the test artifact root."""
        run_ended = time.time()
        total_seconds = run_ended - run_started

        lines = []
        status = self._run_log.get("status", "unknown")
        status_emoji = {"passed": "✅", "failed": "❌", "running": "⏳"}.get(status, "ℹ️")

        lines.append("🧪 Ask-SLM E2E Test Run Log")
        lines.append("=" * 80)
        lines.append(f"{status_emoji} Status: {status}")
        lines.append(
            f"🕒 Started: {self._format_timestamp(self._run_log.get('started_at', run_started))} "
            f"(epoch {self._run_log.get('started_at', run_started):.3f})"
        )
        lines.append(f"🕓 Ended: {self._format_timestamp(run_ended)} (epoch {run_ended:.3f})")
        lines.append(f"⏱️ Total Duration (s): {total_seconds:.3f}")
        lines.append(f"🧭 Path Alias: <TMP_RUN_DIR> = {root}")
        lines.append(f"🧭 Path Alias: <REPO_ROOT> = {REPO_ROOT}")
        if self._run_log.get("error"):
            lines.append(f"💥 Error: {self._run_log['error']}")

        lines.append("")
        lines.append("📍 Checkpoints")
        lines.append("-" * 80)
        for cp in self._run_log.get("checkpoints", []):
            cp_status = cp["status"].lower()
            cp_emoji = {"passed": "✅", "failed": "❌", "running": "⏳"}.get(cp_status, "ℹ️")
            lines.append(
                f"{cp_emoji} [{cp['status'].upper()}] {cp['name']} @ "
                f"{self._format_timestamp(cp['timestamp'])} (epoch {cp['timestamp']:.3f})"
            )
            lines.append(f"  {self._shorten_text(cp['details'], root)}")

        lines.append("")
        lines.append("🛠️ Commands")
        lines.append("-" * 80)
        for i, cmd in enumerate(self._run_log.get("commands", []), start=1):
            lines.append(f"{i}. {self._shorten_text(cmd['command'], root)}")
            lines.append(f"   📁 cwd: {self._shorten_text(cmd['cwd'], root)}")
            lines.append(
                f"   🕒 start: {self._format_timestamp(cmd['start_epoch'])} "
                f"(epoch {cmd['start_epoch']:.3f})"
            )
            lines.append(
                f"   🕓 end: {self._format_timestamp(cmd['end_epoch'])} "
                f"(epoch {cmd['end_epoch']:.3f})"
            )
            lines.append(f"   ⏱️ duration_s: {cmd['duration_s']:.3f}")
            lines.append(f"   🔢 return_code: {cmd['return_code']}")
            if cmd.get("issues"):
                lines.append(f"   ⚠️ issues: {cmd['issues']}")
            lines.append("   📤 stdout:")
            lines.extend(
                [f"     {line}" for line in self._shorten_text(cmd.get("stdout", ""), root).splitlines()]
            )
            lines.append("   📥 stderr:")
            lines.extend(
                [f"     {line}" for line in self._shorten_text(cmd.get("stderr", ""), root).splitlines()]
            )
            lines.append("")

        (root / "test_run.log").write_text("\n".join(lines), encoding="utf-8")

    def _format_timestamp(self, epoch_seconds: float) -> str:
        """Convert epoch seconds to local human-readable timestamp with milliseconds."""
        dt = datetime.fromtimestamp(epoch_seconds)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _shorten_text(self, text: str, tmp_root: Path) -> str:
        """Shorten long absolute paths to readable aliases in logs."""
        shortened = text.replace(str(tmp_root), "<TMP_RUN_DIR>")
        shortened = shortened.replace(str(REPO_ROOT), "<REPO_ROOT>")
        return shortened

    def _run_cli(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        """Run a CLI command and fail with rich debug details if it exits non-zero."""
        start = time.time()
        result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
        end = time.time()

        issues = ""
        if result.returncode != 0:
            issues = "non-zero exit code"
        elif "traceback" in result.stderr.lower() or "error" in result.stderr.lower():
            issues = "stderr contains error-like text"

        self._run_log["commands"].append(
            {
                "command": " ".join(cmd),
                "cwd": str(cwd),
                "start_epoch": start,
                "end_epoch": end,
                "duration_s": end - start,
                "return_code": result.returncode,
                "issues": issues,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )

        if result.returncode != 0:
            joined = " ".join(cmd)
            self.fail(
                "CLI command failed.\n"
                f"Command: {joined}\n"
                f"Exit code: {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\n"
                f"STDERR:\n{result.stderr}\n"
            )
        return result

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
        """Create a minimal, schema-valid metadata.csv fixture."""
        cols = list(SRAMetadataSchema.__fields__.keys())

        def base_row(
            acc: str,
            group_value: str,
            sex: str,
            age_group: str,
            subject_id: str,
            timepoint: str,
            body_site: str,
            host_state: str,
            sequencing_batch: str,
        ) -> dict:
            row = {col: "" for col in cols}
            row.update(
                {
                    "acc": acc,
                    "bioproject": "PRJTEST1",
                    "assay_type": "WGS",
                    "sample_name": acc,
                    "platform": "ILLUMINA",
                    "mbytes": 0,
                    "avgspotlen": 0,
                    "mbases": 0,
                    "insertsize": "0",
                    "jattr": json.dumps(
                        {
                            "group": group_value,
                            "sex": sex,
                            "age_group": age_group,
                            "subject_id": subject_id,
                            "timepoint": timepoint,
                        }
                    ),
                    "attributes": (
                        f"k=body_site, v={body_site}}}"
                        f"k=host_state, v={host_state}}}"
                        f"k=sequencing_batch, v={sequencing_batch}}}"
                    ),
                }
            )
            return row

        metadata_df = pd.DataFrame(
            [
                base_row("SRR0001", "Case", "female", "adult", "SUBJ_1", "baseline", "gut", "healthy", "batch_1"),
                base_row("SRR0002", "Case", "male", "senior", "SUBJ_2", "followup", "blood", "diseased", "batch_2"),
                base_row("SRR0003", "Control", "female", "adult", "SUBJ_3", "baseline", "gut", "healthy", "batch_1"),
            ]
        )
        metadata_df.to_csv(path, index=False)

    def _write_mock_taxonomy_csv(self, path: Path) -> None:
        """Create a tiny taxonomy.csv with multiple ranks and generic lineage names."""
        taxonomy_rows = [
            # SRR0001
            {"acc": "SRR0001", "tax_id": 9000, "rank": "superkingdom", "name": "Some super kingdom", "total_count": 100, "ilevel": 1, "ileft": 1, "iright": 20},
            {"acc": "SRR0001", "tax_id": 9001, "rank": "phylum", "name": "Some phylum", "total_count": 100, "ilevel": 2, "ileft": 2, "iright": 19},
            {"acc": "SRR0001", "tax_id": 9002, "rank": "class", "name": "Some class", "total_count": 100, "ilevel": 3, "ileft": 3, "iright": 18},
            {"acc": "SRR0001", "tax_id": 9003, "rank": "order", "name": "Some order", "total_count": 100, "ilevel": 4, "ileft": 4, "iright": 17},
            {"acc": "SRR0001", "tax_id": 9004, "rank": "family", "name": "Some family", "total_count": 100, "ilevel": 5, "ileft": 5, "iright": 16},
            {"acc": "SRR0001", "tax_id": 1001, "rank": "genus", "name": "Some genus 1", "total_count": 30, "ilevel": 6, "ileft": 6, "iright": 10},
            {"acc": "SRR0001", "tax_id": 1002, "rank": "genus", "name": "Some genus 2", "total_count": 70, "ilevel": 6, "ileft": 11, "iright": 15},
            # SRR0002
            {"acc": "SRR0002", "tax_id": 9000, "rank": "superkingdom", "name": "Some super kingdom", "total_count": 100, "ilevel": 1, "ileft": 1, "iright": 16},
            {"acc": "SRR0002", "tax_id": 9001, "rank": "phylum", "name": "Some phylum", "total_count": 100, "ilevel": 2, "ileft": 2, "iright": 15},
            {"acc": "SRR0002", "tax_id": 9002, "rank": "class", "name": "Some class", "total_count": 100, "ilevel": 3, "ileft": 3, "iright": 14},
            {"acc": "SRR0002", "tax_id": 9003, "rank": "order", "name": "Some order", "total_count": 100, "ilevel": 4, "ileft": 4, "iright": 13},
            {"acc": "SRR0002", "tax_id": 9004, "rank": "family", "name": "Some family", "total_count": 100, "ilevel": 5, "ileft": 5, "iright": 12},
            {"acc": "SRR0002", "tax_id": 1002, "rank": "genus", "name": "Some genus 2", "total_count": 100, "ilevel": 6, "ileft": 6, "iright": 11},
            # SRR0003
            {"acc": "SRR0003", "tax_id": 9000, "rank": "superkingdom", "name": "Some super kingdom", "total_count": 100, "ilevel": 1, "ileft": 1, "iright": 20},
            {"acc": "SRR0003", "tax_id": 9001, "rank": "phylum", "name": "Some phylum", "total_count": 100, "ilevel": 2, "ileft": 2, "iright": 19},
            {"acc": "SRR0003", "tax_id": 9002, "rank": "class", "name": "Some class", "total_count": 100, "ilevel": 3, "ileft": 3, "iright": 18},
            {"acc": "SRR0003", "tax_id": 9003, "rank": "order", "name": "Some order", "total_count": 100, "ilevel": 4, "ileft": 4, "iright": 17},
            {"acc": "SRR0003", "tax_id": 9004, "rank": "family", "name": "Some family", "total_count": 100, "ilevel": 5, "ileft": 5, "iright": 16},
            {"acc": "SRR0003", "tax_id": 1001, "rank": "genus", "name": "Some genus 1", "total_count": 40, "ilevel": 6, "ileft": 6, "iright": 10},
            {"acc": "SRR0003", "tax_id": 1003, "rank": "genus", "name": "Some genus 3", "total_count": 60, "ilevel": 6, "ileft": 11, "iright": 15},
        ]

        for row in taxonomy_rows:
            # Keep self_count intentionally different to ensure computations rely on total_count.
            row["self_count"] = max(int(row["total_count"]) - 1, 0)
            row["bioproject"] = "PRJTEST1"

        taxonomy_df = pd.DataFrame(taxonomy_rows)
        taxonomy_df.to_csv(path, index=False)

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

    def _write_expected_outputs(self, expected_root: Path) -> dict[str, Path]:
        """Create expected CSV files for deterministic assertions and easy debugging."""
        # Expected output of `abundance-matrix` (samples x taxa counts)
        abundance_matrix_df = pd.DataFrame(
            {
                "acc": ["SRR0001", "SRR0002", "SRR0003"],
                "Some genus 2": [70, 100, 0],
                "Some genus 3": [0, 0, 60],
                "Some genus 1": [30, 0, 40],
                "Some class": [100, 100, 100],
                "Some family": [100, 100, 100],
                "Some order": [100, 100, 100],
                "Some phylum": [100, 100, 100],
                "Some super kingdom": [100, 100, 100],
            }
        )

        # Expected output of `alpha-diversity --rank genus`
        alpha_df = pd.DataFrame(
            {
                "acc": ["SRR0001", "SRR0002", "SRR0003"],
                "richness": [2, 1, 2],
                "shannon": [0.6108643020548935, 0.0, 0.6730116670092565],
            }
        )

        # Expected output of `taxonomic-abundance --rank genus --taxon Some genus 1`
        abundance_df = pd.DataFrame(
            {
                "acc": ["SRR0001", "SRR0002", "SRR0003"],
                "total_sample_reads": [100, 100, 100],
                "taxon_reads": [30.0, 0.0, 40.0],
                "relative_abundance": [0.3, 0.0, 0.4],
                "bioproject": ["PRJTEST1", "PRJTEST1", "PRJTEST1"],
            }
        )
        abundance_summary_df = pd.DataFrame(
            {
                "Cohort": ["All Combined"],
                "Total Samples (N)": [3],
                "Samples with 0 Reads": [1],
                "Samples with Non-Zero Reads (%)": ["66.67%"],
                "Mean Rel. Abundance": ["23.333333%"],
            }
        )

        metadata_summary_df = pd.DataFrame(
            {
                "metric": [
                    "samples",
                    "projects",
                    "metadata_columns",
                    "mapped_columns_count",
                    "mapped_columns",
                    "discovered_source_keys_unique",
                    "projects_with_discovered_source_keys",
                ],
                "value": [
                    "3",
                    "1",
                    str(len(SRAMetadataSchema.__fields__) + 1),
                    "1",
                    "Group",
                    str(8 + (len(SRAMetadataSchema.__fields__) - 2)),
                    "1",
                ],
            }
        )
        metadata_projects_df = pd.DataFrame(
            {
                "bioproject": ["PRJTEST1"],
                "samples": [3],
            }
        )
        metadata_discovered_by_project_df = pd.DataFrame(
            {
                "project_id": [
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                ],
                "source": [
                    "from_jattr",
                    "from_jattr",
                    "from_jattr",
                    "from_jattr",
                    "from_jattr",
                    "from_attributes",
                    "from_attributes",
                    "from_attributes",
                ],
                "key_name": [
                    "age_group",
                    "group",
                    "sex",
                    "subject_id",
                    "timepoint",
                    "body_site",
                    "host_state",
                    "sequencing_batch",
                ],
                "unique_values_count": [2, 2, 2, 3, 2, 2, 2, 2],
                "top_values": [
                    "adult | senior",
                    "Case | Control",
                    "female | male",
                    "SUBJ_1 | SUBJ_2 | SUBJ_3",
                    "baseline | followup",
                    "gut | blood",
                    "healthy | diseased",
                    "batch_1 | batch_2",
                ],
            }
        )
        metadata_discovered_unique_df = pd.DataFrame(
            {
                "source": [
                    "from_attributes",
                    "from_attributes",
                    "from_attributes",
                    "from_jattr",
                    "from_jattr",
                    "from_jattr",
                    "from_jattr",
                    "from_jattr",
                ],
                "key_name": [
                    "body_site",
                    "host_state",
                    "sequencing_batch",
                    "age_group",
                    "group",
                    "sex",
                    "subject_id",
                    "timepoint",
                ],
                "projects_count": [1, 1, 1, 1, 1, 1, 1, 1],
                "projects": [
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                    "PRJTEST1",
                ],
                "max_unique_values_count": [2, 2, 2, 2, 2, 2, 3, 2],
            }
        )

        abundance_matrix_path = expected_root / "abundance_matrix.csv"
        alpha_path = expected_root / "alpha_diversity.csv"
        taxonomic_abundance_path = expected_root / "taxonomic_abundance_Some_genus_1.csv"
        abundance_summary_path = expected_root / "taxonomic_abundance_Some_genus_1_summary.csv"
        metadata_summary_path = expected_root / "metadata_overview_summary.csv"
        metadata_projects_path = expected_root / "metadata_overview_projects.csv"
        metadata_discovered_by_project_path = expected_root / "metadata_overview_discovered_keys_by_project.csv"
        metadata_discovered_unique_path = expected_root / "metadata_overview_discovered_keys_unique.csv"

        abundance_matrix_df.to_csv(abundance_matrix_path, index=False)
        alpha_df.to_csv(alpha_path, index=False)
        abundance_df.to_csv(taxonomic_abundance_path, index=False)
        abundance_summary_df.to_csv(abundance_summary_path, index=False)
        metadata_summary_df.to_csv(metadata_summary_path, index=False)
        metadata_projects_df.to_csv(metadata_projects_path, index=False)
        metadata_discovered_by_project_df.to_csv(metadata_discovered_by_project_path, index=False)
        metadata_discovered_unique_df.to_csv(metadata_discovered_unique_path, index=False)

        return {
            "abundance_matrix": abundance_matrix_path,
            "alpha_diversity": alpha_path,
            "taxonomic_abundance": taxonomic_abundance_path,
            "taxonomic_abundance_summary": abundance_summary_path,
            "metadata_overview_summary": metadata_summary_path,
            "metadata_overview_projects": metadata_projects_path,
            "metadata_overview_discovered_by_project": metadata_discovered_by_project_path,
            "metadata_overview_discovered_unique": metadata_discovered_unique_path,
        }


if __name__ == "__main__":
    unittest.main()
