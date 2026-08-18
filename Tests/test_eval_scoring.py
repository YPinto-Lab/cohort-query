"""Execution accuracy, not string match: two queries can differ in every character and
still select the same cohort -- and can also match textually while diverging on the
partition, which is the specific failure per-source translation invites (HLD E.2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Scripts" / "eval"))

from run_eval import Score, score_question


def test_identical_sets_score_one_everywhere():
    score = score_question(
        generated={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S2", "S3"}},
        gold={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S2", "S3"}})

    assert score == Score(per_source={"SRA_METADATA": 1.0, "METALOG_METADATA": 1.0},
                          shared=1.0)


def test_one_source_right_and_the_other_wrong_is_not_averaged_away():
    """Reporting a single number would hide exactly the bias we are hunting: a concept
    resolved strictly in one vocabulary and loosely in the other."""
    score = score_question(
        generated={"SRA_METADATA": {"S1"}, "METALOG_METADATA": set()},
        gold={"SRA_METADATA": {"S1"}, "METALOG_METADATA": {"S9"}})

    assert score.per_source["SRA_METADATA"] == 1.0
    assert score.per_source["METALOG_METADATA"] == 0.0


def test_the_shared_partition_is_scored_separately():
    """Both sources can be individually plausible while their OVERLAP is wrong."""
    score = score_question(
        generated={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S3"}},
        gold={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S2"}})

    assert score.per_source["SRA_METADATA"] == 1.0
    assert score.shared == 0.0        # generated overlap is empty, gold's is {S2}


def test_two_empty_sets_agree():
    """A question both queries correctly find nothing for is not a failure."""
    score = score_question(generated={"SRA_METADATA": set()}, gold={"SRA_METADATA": set()})

    assert score.per_source["SRA_METADATA"] == 1.0
