"""Mechanical half of one audit question: ask() against the real mirror, save
the real Plan into the real plans directory, execute each source's SQL, and
write generated.sql + results.csv. Gold derivation and judgment are NOT
mechanical -- done by hand per question, see the design doc Sections 2-3."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cohortquery
from cohortquery import settings_file
from cohortquery.cli import rundir
from cohortquery.cohort import accessions_of

PLANS_ROOT = Path("/private/pinto-lab/plans")


def write_sidecars(connection, queries, run_dir: Path) -> dict[str, int]:
    run_dir.mkdir(parents=True, exist_ok=True)
    sql_blocks = []
    row_counts: dict[str, int] = {}
    with (run_dir / "results.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source", "biosample"])
        for query in queries:
            if query.sql:
                sql_blocks.append(f"-- {query.source.name}\n{query.sql};")
            else:
                sql_blocks.append(f"-- {query.source.name}: jattr-only, no native SQL")
            keys = sorted(accessions_of(connection.query(query.sql))) if query.sql else []
            row_counts[query.source.name] = len(keys)
            for key in keys:
                writer.writerow([query.source.name, key])
    (run_dir / "generated.sql").write_text("\n\n".join(sql_blocks))
    return row_counts


def run(question: str, question_dir: Path, run_label: str) -> dict:
    """The live half: real ask(), real plan save, real mirror query. Requires
    server-side config (settings_file.stored_settings()) -- never pass or
    print the LLM key directly."""
    settings = settings_file.stored_settings()
    cohortquery.config(db=settings["db"], llm="gemini", llm_key=settings["llm_key"],
                        llm_model="gemini-2.5-flash")
    plan_dir = rundir.new_plan_dir(question, root=PLANS_ROOT)
    plan = cohortquery.ask(question, save=plan_dir / "plan.json")

    run_dir = question_dir / "runs" / run_label
    row_counts = write_sidecars(cohortquery.runtime.database(), plan.translation.queries, run_dir)
    return {
        "plan_path": str(plan_dir / "plan.json"),
        "generated_sql_path": str(run_dir / "generated.sql"),
        "results_path": str(run_dir / "results.csv"),
        "result_row_count": str(row_counts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--question-dir", type=Path, required=True)
    parser.add_argument("--run-label", required=True)
    args = parser.parse_args()
    print(run(args.question, args.question_dir, args.run_label))


if __name__ == "__main__":
    main()
