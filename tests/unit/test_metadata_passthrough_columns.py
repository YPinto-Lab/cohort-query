"""End-to-end style unit test validating metadata CSV parsing and matrix output.

This test writes a single-row metadata.csv that exactly matches the user's
provided CSV line, runs the `metadata-overview` CLI command, and validates the
generated `metadata_matrix.csv` matches the expected matrix produced by the
engine. Artifacts are preserved (copied to repo) when the test succeeds so
developers can inspect outputs locally, mirroring the behavior in
`Tests/e2e/test_cli_end_to_end.py`.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pandas as pd

from Common.contracts.sra_schema import SRAMetadataSchema


class TestMetadataCSVExactRow(unittest.TestCase):
    ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "artifacts"
    KEEP_ARTIFACTS_ON_SUCCESS = True
    KEEP_ARTIFACTS_ON_FAILURE = True

    def test_metadata_overview_from_exact_csv_row(self) -> None:
        # Prepare temp workspace
        repo_root = Path(__file__).resolve().parents[2]
        run_started = time.time()
        keep_artifacts = self.KEEP_ARTIFACTS_ON_SUCCESS

        tmp_path = Path(tempfile.mkdtemp(prefix="ask_slm_meta_test_"))
        try:
            view_name = "ExactRowView"
            workspace_root = tmp_path / "Workspaces"
            workspace_dir = workspace_root / view_name
            inputs = workspace_dir / "inputs"
            configs = workspace_dir / "mapping_configs"
            results = workspace_dir / "results"
            expected_root = tmp_path / "expected"
            for p in (inputs, configs, results, expected_root):
                p.mkdir(parents=True, exist_ok=True)

            # Build metadata row mapping to SRAMetadataSchema field order
            cols = list(SRAMetadataSchema.__fields__.keys())
            # The CSV values provided by the user (single row) map, in order, to
            # the schema columns. We construct the row accordingly.
            values = [
                "SRR29697434", "AMPLICON", "STANFORD", "public", "SRX25200342",
                "BAD_39", "Illumina NovaSeq X", "PAIRED", "PCR", "GENOMIC",
                "ILLUMINA", "SRS17790890", "SAMN35299278", "human gut metagenome",
                "SRP439118", "2024-12-12", "512", "", "300", "1824", "",
                "BAD_C5_1", "[Metagenome or environmental]", "[2015-04-08]", "USA",
                "North America", "[USA: San Francisco]", "", "", "",
                "[fastq, run.zq, sra]", "[gs, ncbi, s3]", "[gs.us-east1, ncbi.public, s3.us-east-1]",
                "[{k=bases, v=1824020400}, {k=bytes, v=537051765}, {k=run_file_create_date, v=2024-07-03T20:03:00.000Z}, {k=canonic_day_run, v=C5}, {k=day_run, v=30}, {k=primer_pair_run, v=1}, {k=collection_date_sam, v=2015-04-08}, {k=host_sam, v=Homo sapiens}, {k=host_subject_id_sam, v=BAD}, {k=lat_lon_sam_s_dpl34, v=37.7631 N 122.4575 W}, {k=primary_search, v=35299278}, {k=primary_search, v=974858}, {k=primary_search, v=BAD_39}, {k=primary_search, v=BAD_C5_1}, {k=primary_search, v=PRJNA974858}, {k=primary_search, v=S1973_TCAGTCTCGT-ATAATCCGTG_L003_R1_001.fastq.gz}, {k=primary_search, v=SAMN35299278}, {k=primary_search, v=SRP439118}, {k=primary_search, v=SRR29697434}, {k=primary_search, v=SRS17790890}, {k=primary_search, v=SRX25200342}, {k=primary_search, v=bp0}]",
                '{"bases": 1824020400, "bytes": 537051765, "run_file_create_date": "2024-07-03T20:03:00.000Z", "canonic_day_run": "C5", "day_run": "30", "primer_pair_run": 1, "collection_date_sam": ["2015-04-08"], "host_sam": ["Homo sapiens"], "host_subject_id_sam": "BAD", "lat_lon_sam_s_dpl34": "37.7631 N 122.4575 W", "primary_search": "35299278"}',
                "1", "PRJNA974858",
            ]

            row = {c: v for c, v in zip(cols, values)}
            pd.DataFrame([row]).to_csv(inputs / "metadata.csv", index=False)

            # Minimal taxonomy.csv so workspace preparation succeeds
            tax_rows = [
                {
                    "acc": "SRR29697434",
                    "tax_id": 9000,
                    "rank": "superkingdom",
                    "name": "Some super kingdom",
                    "total_count": 100,
                    "self_count": 99,
                    "ilevel": 1,
                    "ileft": 1,
                    "iright": 2,
                    "bioproject": "PRJNA974858",
                }
            ]
            pd.DataFrame(tax_rows).to_csv(inputs / "taxonomy.csv", index=False)

            # Run CLI metadata-overview
            cmd = [sys.executable, "askslm.py", "metadata-overview", "--view", view_name, "--inputs-dir", str(inputs), "--config-dir", str(configs), "--output-dir", str(results), "--workspace-root", str(workspace_root)]
            proc = subprocess.run(cmd, cwd=repo_root, text=True, capture_output=True)
            if proc.returncode != 0:
                raise AssertionError(f"CLI failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

            out_mat = results / "metadata-overview" / "metadata_matrix.csv"
            self.assertTrue(out_mat.exists(), f"metadata_matrix.csv not generated. STDOUT:\n{proc.stdout}")

            # Build expected by invoking the engine directly (same logic used by CLI)
            from Engines.MetadataOverviewEngine.metadata_overview_engine import MetadataOverviewEngine
            from Accessors.SraAccessor.sra_metadata_accessor import SRAMetadataAccessor

            # Reload canonical metadata/taxonomy via accessor to mimic CLI
            canonical_meta = SRAMetadataAccessor.get(inputs / "metadata.csv")
            # Run engine to get expected matrix
            engine = MetadataOverviewEngine(config_dir=str(configs))
            # Need enriched metadata; CLI previously computed _load_and_enrich which runs mapping/enrichment.
            # For this focused test we can pass canonical_meta as both metadata_df and raw_metadata_df
            result = engine.run(canonical_meta, canonical_meta)
            expected = result.metadata_matrix_df.reset_index()

            # Save expected for artifact inspection
            expected.to_csv(expected_root / "expected_metadata_matrix.csv", index=False)

            # Compare CSV output as text rows so the test does not depend on dtype inference.
            with out_mat.open(newline="", encoding="utf-8") as actual_f, (expected_root / "expected_metadata_matrix.csv").open(newline="", encoding="utf-8") as expected_f:
                actual_rows = list(csv.reader(actual_f))
                expected_rows = list(csv.reader(expected_f))
            self.assertEqual(actual_rows, expected_rows)

            # Preserve artifacts for local debugging if desired
            if self.KEEP_ARTIFACTS_ON_SUCCESS:
                self.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                target = self.ARTIFACTS_DIR / datetime_from_epoch(run_started)
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(tmp_path, target)

        except Exception:
            # Always preserve on failure for debugging
            keep_artifacts = self.KEEP_ARTIFACTS_ON_FAILURE
            raise
        finally:
            if not keep_artifacts:
                shutil.rmtree(tmp_path, ignore_errors=True)


def datetime_from_epoch(epoch: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d_%H-%M-%S_%f")


if __name__ == "__main__":
    unittest.main()




