"""End-to-end smoke test: one real question, through the LLM, to a written .biom.

Nothing else exercises the whole path. The unit tests use a fixture mirror and a canned
LLM; `Scripts/eval` scores translation alone. This is the only check that `ask()` and
`run()` still work against the real mirror, a real API key, and the real 13.6B-row
taxonomy -- which is how the two most expensive bugs of 2026-08 were found (an OOM after
66 minutes with no output, and a metadata read that silently cost half the runtime).

Costs one LLM call and reads the real mirror, so it is NOT part of the pytest run.
Invoke it deliberately, on a compute node:

    python Scripts/smoke/full_cohort.py --out-dir /some/scratch
    python Scripts/smoke/full_cohort.py --out-dir /scratch --question "..." --expect-samples 3573

Settings come from cohortquery's own resolution -- COHORTQUERY_DB / COHORTQUERY_LLM_KEY, else
~/.cohortquery/config.toml -- so this stays correct if that ever changes.

Salvaged from tools/just-ask/tmp_bugfix_test/run_full_cohort.py (2026-08-23), which
carried a `sys.path.insert` onto a private copy of the package: it imported August code
no matter what was installed, which is exactly the drift that copy was meant to help fix.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cohortquery
from cohortquery import Source
from cohortquery.settings_file import stored_settings

DEFAULT_QUESTION = "IBD fecal metagenomic with calprotectin"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="where the plan and biom are written; must be writable")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--expect-samples", type=int, default=None,
                        help="fail unless the biom has exactly this many columns")
    args = parser.parse_args()

    settings = stored_settings()
    if not settings.get("db"):
        print("No mirror configured. Set COHORTQUERY_DB or run the terminal app once.",
              file=sys.stderr)
        return 2
    cohortquery.config(db=settings["db"], llm="gemini", llm_key=settings.get("llm_key", ""))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"mirror   : {settings['db']}")
    print(f"question : {args.question}", flush=True)

    asked = time.monotonic()
    plan = cohortquery.ask(args.question, save=args.out_dir / "plan.json")
    print(f"ask()    : {time.monotonic() - asked:.1f}s", flush=True)
    print(plan, flush=True)
    if plan.error:
        print(f"PLAN ERROR: {plan.error}", file=sys.stderr)
        return 1

    started = time.monotonic()
    table, report = plan.run(
        profile_sources=Source.SRA_TAXONOMY,
        out=args.out_dir / "cohort.biom",
        metadata_winning_source=Source.SRA_METADATA,
        on_step=lambda step: print(f"  [{time.monotonic() - started:6.1f}s] {step}", flush=True),
        plan_dir=args.out_dir,
    )
    elapsed = time.monotonic() - started
    print(f"run()    : {elapsed:.1f}s")
    print(f"biom     : {table.shape[0]} features x {table.shape[1]} samples")
    print(f"report   : {report}")

    written = args.out_dir / "cohort.biom"
    if not written.exists() or written.stat().st_size == 0:
        print("FAIL: no biom was written", file=sys.stderr)
        return 1
    if args.expect_samples is not None and table.shape[1] != args.expect_samples:
        print(f"FAIL: expected {args.expect_samples} samples, got {table.shape[1]}",
              file=sys.stderr)
        return 1
    print(f"OK: {written} ({written.stat().st_size / 1e6:.1f} MB) in {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
