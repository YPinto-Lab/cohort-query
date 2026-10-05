"""Score the translator on real research questions with hand-written gold SQL.

Deliberately NOT a pytest: it needs the full mirror and a live API key, so CI cannot
run it. The fixture tests are what gate. This is a tracked measurement -- run it when
the prompt, the vocabularies, or the backend change, and diff the numbers. HLD H.3.

    python3 Scripts/eval/run_eval.py --db mirror.duckdb --key $GEMINI_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

QUESTIONS = Path(__file__).parent / "questions.jsonl"

# Free tier's real ceiling isn't the 5 RPM number -- it's 250K input tokens/minute,
# and this schema-heavy prompt runs ~80K tokens/call (measured 2026-08-27: 3 calls
# in one minute hit 239K/250K TPM). That caps real throughput at ~3 calls/minute
# regardless of the RPM limit; 22s of pacing leaves margin under that, not just
# under RPM. A day's 20 RPD cap still means a full question set can outrun the
# budget outright -- that's handled in main() by skipping the failure and
# reporting on whatever did complete, not by pacing harder.
RPM_PACING_SECONDS = 22


@dataclass(frozen=True)
class Score:
    per_source: dict[str, float] = field(default_factory=dict)
    shared: float = 0.0


def score_question(generated: dict[str, set], gold: dict[str, set]) -> Score:
    """Execution accuracy: exact set agreement, scored per source AND on the overlap.

    Three numbers rather than one because the per-source design invites a specific
    failure -- "adults with IBD" resolving strictly in SRA and loosely in Metalog
    biases the cohort silently, and an averaged score would hide it.
    """
    per_source = {source: _agreement(generated.get(source, set()), keys)
                  for source, keys in gold.items()}
    return Score(per_source=per_source,
                 shared=_agreement(_overlap(generated), _overlap(gold)))


def _agreement(left: set, right: set) -> float:
    return 1.0 if left == right else 0.0


def _overlap(by_source: dict[str, set]) -> set:
    """Samples present in EVERY source (n-way intersection), not merely "more than
    one" -- with fewer than two sources there is no overlap to speak of, and an
    empty set compares equal to an empty set.

    Today there are exactly two metadata sources, so "in every source" and "in more
    than one source" are the same partition and this is correct as shipped. A third
    metadata source would split them: does "shared" then mean the samples all three
    agree on, or the samples any two overlap on? That call is unmade -- revisit this
    function before trusting its output past two sources.
    """
    sets = list(by_source.values())
    if len(sets) < 2:
        return set()
    return set.intersection(*sets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="the real mirror")
    parser.add_argument("--key", required=True, help="Gemini API key")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--limit", type=int, default=None,
                        help="score only the first N questions -- for a quick, cheap "
                             "check against the daily quota instead of the full set")
    args = parser.parse_args()

    import cohortquery
    from cohortquery.adapters import DuckDbConnection

    connection = DuckDbConnection(args.db)
    cohortquery.config(db=args.db, llm="gemini", llm_key=args.key, llm_model=args.model,
                  database=connection)

    cases = [json.loads(line) for line in QUESTIONS.read_text().splitlines()
             if line.strip() and not line.lstrip().startswith("//")]
    if args.limit is not None:
        cases = cases[:args.limit]

    totals = []
    failed = []
    for case in cases:
        try:
            totals.append(_run_one(connection, case))
        except Exception as exc:
            failed.append(case["question"])
            print(f"\n{case['question']}\n  FAILED: {exc}")
        time.sleep(RPM_PACING_SECONDS)
    _report(totals)
    if failed:
        print(f"\n{len(failed)}/{len(totals) + len(failed)} question(s) failed to "
              "translate (see FAILED lines above) -- likely the free-tier RPD cap; "
              "rerun to fill in the rest once it resets.")
    connection.close()


def _run_one(connection, case: dict) -> Score:
    import cohortquery

    plan = cohortquery.ask(case["question"])
    generated = {query.source.name: _keys(connection, query.sql)
                 for query in plan.translation.queries}
    gold = {source: _keys(connection, sql) for source, sql in case["gold"].items()}
    score = score_question(generated, gold)
    print(f"\n{case['question']}")
    print(f"  interpretation: {plan.translation.interpretation}")
    for source, value in score.per_source.items():
        print(f"  {source}: {value:.0f}")
    print(f"  shared: {score.shared:.0f}")
    return score


def _keys(connection, sql: str) -> set:
    from cohortquery.cohort import accessions_of

    return set(accessions_of(connection.query(sql)))


def _report(scores: list[Score]) -> None:
    if not scores:
        print("no questions scored")
        return
    sources = sorted({source for score in scores for source in score.per_source})
    print("\n=== execution accuracy ===")
    for source in sources:
        values = [score.per_source[source] for score in scores if source in score.per_source]
        print(f"{source}: {sum(values) / len(values):.2f}  ({len(values)} questions)")
    shared = [score.shared for score in scores]
    print(f"shared partition: {sum(shared) / len(shared):.2f}")


if __name__ == "__main__":
    main()
