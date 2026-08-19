"""End to end: question -> plan -> .biom on disk, against the fixture mirror.

Real DuckDB, real biom, real reconciliation. Only the LLM is canned -- everything
below the port is the shipping path. This is the test that proves the five hand-offs
(Cohort -> ProfileMatrix -> ReconciledMetadata -> biom.Table) actually fit together.
"""
import biom
import pytest

import askslm
from askslm.adapters import CannedLlmBackend, DuckDbConnection
from askslm.translation import SourceQuery, Translation

from fixtures.mirror import build_fixture_mirror

# The cohort a real question would produce: every biosample in each metadata source.
IBD_TRANSLATION = Translation(
    interpretation="body_site = stool · disease = IBD",
    queries=(
        SourceQuery(askslm.Source.SRA_METADATA,
                    "SELECT * FROM sra_metadata"),
        SourceQuery(askslm.Source.METALOG_METADATA,
                    "SELECT * FROM metalog_metadata"),
    ),
)


@pytest.fixture
def configured(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    askslm.config(db=path, database=connection, backend=CannedLlmBackend(IBD_TRANSLATION))
    yield tmp_path
    connection.close()


def test_ask_previews_the_cohort_partition(configured):
    plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")

    assert plan.preview.union == 20          # 8 shared + 6 SRA-only + 4 Metalog-only + 2 orphan
    assert plan.preview.shared == 8
    assert plan.error is None


def test_a_source_omitted_from_the_translation_contributes_nothing(configured):
    """Confirms the prompt's new "omit a source that cannot express the question" rule
    is safe to follow: Cohort.by_source is built from whatever queries it is handed, so
    a source with no SourceQuery at all just never appears -- union/shared read only the
    sources present, and no code path indexes by_source[a_source_that_was_never_asked]."""
    askslm.config(db=configured / "fixture.duckdb",
                  database=DuckDbConnection(configured / "fixture.duckdb"),
                  backend=CannedLlmBackend(Translation(
                      interpretation="SRA only -- Metalog has no matching field",
                      queries=(SourceQuery(askslm.Source.SRA_METADATA,
                                           "SELECT * FROM sra_metadata"),))))

    plan = askslm.ask("human tumour RNA-seq")

    assert plan.error is None
    assert set(plan.preview.by_metadata_source) == {askslm.Source.SRA_METADATA}
    assert plan.preview.union == plan.preview.by_metadata_source[askslm.Source.SRA_METADATA]
    assert plan.preview.shared == 0


def test_run_writes_a_biom_unioning_two_same_family_sources(configured):
    out = configured / "motus.biom"
    plan = askslm.ask("gut metagenomes")

    table, report = plan.run(
        profile_sources=[askslm.Source.METALOG_MOTUS3, askslm.Source.METALOG_SPIRE_MOTUS],
        out=out)

    assert out.exists()
    assert report.family is askslm.ProfilerFamily.MOTUS
    assert report.columns == 12              # motus3's 8 + spire's 4 that nothing else profiles
    columns = set(table.ids("sample"))
    assert "SAMN00007" in columns            # spire alone profiles it, and it survived the union
    assert "MG_ORPHAN_1" in columns          # no BioSample: keyed by sample_alias, not dropped
    assert biom.load_table(str(out)).shape == table.shape


def test_the_head_wins_every_overlapping_column(configured):
    plan = askslm.ask("gut metagenomes")

    head_first, _ = plan.run(profile_sources=[askslm.Source.METALOG_MOTUS3,
                                              askslm.Source.METALOG_SPIRE_MOTUS])
    spire_first, _ = plan.run(profile_sources=[askslm.Source.METALOG_SPIRE_MOTUS,
                                               askslm.Source.METALOG_MOTUS3])

    shared_column = "SAMN00004"              # profiled by both sources, with different values
    feature = "ref_mOTU_v3_00095 Escherichia coli"
    assert head_first.get_value_by_ids(feature, shared_column) == pytest.approx(0.20)
    assert spire_first.get_value_by_ids(feature, shared_column) == pytest.approx(0.50)


def test_lineage_is_unioned_so_a_spire_only_feature_survives(configured):
    plan = askslm.ask("gut metagenomes")

    table, _ = plan.run(profile_sources=[askslm.Source.METALOG_MOTUS3,
                                         askslm.Source.METALOG_SPIRE_MOTUS])

    assert "ref_mOTU_v3_99999 Spire-only species" in set(table.ids("observation"))


def test_stat_columns_are_runs_and_carry_their_biosample(configured):
    """B.3: two runs of one BioSample are TWO columns, neither summed nor discarded."""
    plan = askslm.ask("gut metagenomes")

    table, report = plan.run(profile_sources=askslm.Source.SRA_TAXONOMY)

    columns = set(table.ids("sample"))
    assert {"SRR00001A", "SRR00001B"} <= columns
    assert report.columns > report.biosamples          # more runs than biosamples
    for column in ("SRR00001A", "SRR00001B"):
        assert table.metadata(column, axis="sample")["biosample"] == "SAMN00001"


def test_stat_lineage_comes_from_ete3_not_the_stale_table_columns(configured):
    """sra_taxonomy's own name/rank are a lagging snapshot of NCBI's taxonomy, so reading
    them ships outdated names into the biom. The fixture stores tax_id 1239 as its old
    name "Firmicutes"; NCBI renamed it "Bacillota" in 2021. The biom must say Bacillota.

    Ancestry is the second half: the table has no parents at all, so a STAT feature can
    only be projected to a rank if ete3 supplies the lineage."""
    plan = askslm.ask("gut metagenomes")

    table, _ = plan.run(profile_sources=askslm.Source.SRA_TAXONOMY)

    phylum = table.metadata("1239", axis="observation")
    assert phylum["name"] == "Bacillota"

    coli = table.metadata("562", axis="observation")
    assert coli["name"] == "Escherichia coli"
    assert 561 in coli["lineage"]                 # its genus, which the table never gave us
    assert coli["ranks"]["genus"] == 561


def test_metaphlan_features_carry_a_parsed_rank(configured):
    """Real clade_name is one rank per row with no ancestry (k__Bacteria, t__SGB1871),
    so rank has to be parsed out of the prefix. Without it a MetaPhlAn biom mixes every
    rank in one matrix with no way to tell them apart -- and a column sums to ~8, not 1."""
    plan = askslm.ask("gut metagenomes")

    table, _ = plan.run(profile_sources=askslm.Source.METALOG_METAPHLAN4_ALL)

    ranks = {feature: table.metadata(feature, axis="observation")["rank"]
             for feature in table.ids("observation")}
    assert ranks["k__Bacteria"] == "kingdom"
    assert ranks["t__SGB1871"] == "strain"
    assert table.metadata("s__Faecalibacterium_prausnitzii",
                          axis="observation")["name"] == "Faecalibacterium_prausnitzii"


def test_motus_features_keep_their_whole_string_as_the_name(configured):
    """mOTUs species carry no rank prefix, so nothing is parsed off them."""
    plan = askslm.ask("gut metagenomes")

    table, _ = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3)

    feature = "ref_mOTU_v3_00095 Escherichia coli"
    assert table.metadata(feature, axis="observation")["name"] == feature
    assert table.metadata(feature, axis="observation")["rank"] is None


def test_metadata_winner_decides_shared_samples(configured):
    plan = askslm.ask("gut metagenomes")

    table, _ = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3,
                        metadata_winning_source=askslm.Source.METALOG_METADATA)

    sample = table.metadata("SAMN00001", axis="sample")
    assert sample["subject_disease_status"] in {"Crohn's disease", "ulcerative colitis",
                                                "healthy control"}
    assert sample["biosample"] == "SAMN00001"


def test_samples_no_named_source_covers_are_dropped_and_reported(configured):
    plan = askslm.ask("gut metagenomes")

    _, report = plan.run(profile_sources=askslm.Source.METALOG_METAPHLAN4_ALL)

    assert report.biosamples == 6                       # metaphlan covers 6 of the 20
    assert len(report.dropped) == 14
    assert "SAMN00009" in report.dropped                # SRA-only, no MetaPhlAn profile


def test_the_written_biom_is_strict_valid_json(configured):
    """Sparse metadata used to leave pandas NaN in the file. Python and biom both emit
    and re-read NaN happily, so it is invisible from here -- but NaN is not valid JSON
    and a strict parser (R's jsonlite, most non-Python tooling) rejects the file. Since
    the .biom IS the product's output, this has to hold for every family."""
    import json

    plan = askslm.ask("gut metagenomes")

    for name, source in [("motus", askslm.Source.METALOG_MOTUS3),
                         ("stat", askslm.Source.SRA_TAXONOMY),
                         ("metaphlan", askslm.Source.METALOG_METAPHLAN4_ALL)]:
        out = configured / f"{name}.biom"
        plan.run(profile_sources=source, out=out)

        json.loads(out.read_text(), parse_constant=_reject_non_standard)


def _reject_non_standard(value):
    raise AssertionError(f"non-standard JSON constant in the biom: {value}")


def test_cross_family_profile_sources_are_rejected_on_construction(configured):
    plan = askslm.ask("gut metagenomes")

    with pytest.raises(ValueError, match="one ProfilerFamily"):
        plan.run(profile_sources=[askslm.Source.METALOG_MOTUS3,
                                  askslm.Source.METALOG_METAPHLAN4_ALL])


def test_a_metadata_source_cannot_be_used_as_a_profile_source(configured):
    plan = askslm.ask("gut metagenomes")

    with pytest.raises(ValueError, match="PROFILE source"):
        plan.run(profile_sources=askslm.Source.SRA_METADATA)


@pytest.fixture
def configured_with_recording_backend(tmp_path):
    """Same construction as `configured`, but with a backend that records the prompt it
    was handed instead of returning a canned Translation -- so a test can assert on what
    ask() actually sent, not just on what came back."""
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    backend = RecordingLlmBackend(IBD_TRANSLATION)
    askslm.config(db=path, database=connection, backend=backend)
    yield backend
    connection.close()


class RecordingLlmBackend(CannedLlmBackend):
    """CannedLlmBackend that also records the TranslationPrompt it was handed."""

    def translate(self, prompt):
        self.prompt = prompt
        return super().translate(prompt)


def test_ask_sends_the_real_schemas_to_the_backend(configured_with_recording_backend):
    """Regression: ask() used to hardcode schemas="" while the catalog sat unread in the
    mirror. A backend that never sees the vocabularies invents literals."""
    backend = configured_with_recording_backend

    askslm.ask("adults with IBD")

    assert "metalog_metadata" in backend.prompt.schemas
    assert "subject_disease_status" in backend.prompt.schemas


def test_invalid_generated_sql_becomes_plan_error_not_a_crash(configured):
    """HLD H.1: invalid generated SQL -> Plan carries `error`; run() then refuses.

    Distinct from the model DECLINING to translate (Translation.failure, tested
    below) -- this is the model producing SQL that DuckDB itself rejects, e.g. an
    ILIKE against a numeric column. Nothing on the ask() -> CohortDiscovery path
    caught that before, so it surfaced as a raw duckdb.BinderException out of ask().
    """
    askslm.config(db=configured / "fixture.duckdb",
                  database=DuckDbConnection(configured / "fixture.duckdb"),
                  backend=CannedLlmBackend(Translation(
                      interpretation="adults (age_years ILIKE 18)",
                      queries=(
                          SourceQuery(askslm.Source.SRA_METADATA,
                                      "SELECT * FROM sra_metadata"),
                          SourceQuery(askslm.Source.METALOG_METADATA,
                                      "SELECT * FROM metalog_metadata "
                                      "WHERE age_years ILIKE '%18%'"),
                      ))))

    plan = askslm.ask("adults with IBD")

    assert plan.error is not None
    assert "METALOG_METADATA" in plan.error
    assert "~~*" in plan.error or "ILIKE" in plan.error or "BinderException" in plan.error
    with pytest.raises(askslm.TranslationError):
        plan.run(profile_sources=askslm.Source.METALOG_MOTUS3)


def test_an_untranslatable_question_refuses_to_run(configured):
    askslm.config(db=configured / "fixture.duckdb",
                  database=DuckDbConnection(configured / "fixture.duckdb"),
                  backend=CannedLlmBackend(Translation(
                      interpretation="", queries=(),
                      failure="'felt unwell' matches no metadata field")))

    plan = askslm.ask("samples from people who felt unwell")

    assert plan.error is not None
    with pytest.raises(askslm.TranslationError, match="felt unwell"):
        plan.run(profile_sources=askslm.Source.METALOG_MOTUS3)


def test_bad_sql_is_repaired_once_and_the_cohort_survives(configured):
    """Four rounds of prompt tuning each fixed one class of bad SQL and revealed the
    next. Handing the model the database's own rejection generalises instead: DuckDB
    names the offending column, which beats any rule written in advance."""
    broken = Translation(
        interpretation="x",
        queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                             "SELECT biosample FROM metalog_metadata WHERE nope = 1"),))

    class RepairingBackend(CannedLlmBackend):
        def repair(self, sql, error, columns):
            assert "nope" in error                  # the model is told what was wrong
            assert "sample_alias" in columns        # ...and what actually exists
            return "SELECT biosample FROM metalog_metadata"

    connection = DuckDbConnection(configured / "fixture.duckdb")
    askslm.config(db=configured / "fixture.duckdb", database=connection,
                  backend=RepairingBackend(broken))

    plan = askslm.ask("anything")

    assert plan.error is None
    assert plan.preview.union > 0
    connection.close()


def test_a_second_failure_is_reported_rather_than_looping(configured):
    """No third attempt. If the model cannot fix its own SQL with the error in front of
    it, looping burns the user's quota without converging."""
    broken = Translation(
        interpretation="x",
        queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                             "SELECT biosample FROM metalog_metadata WHERE nope = 1"),))

    connection = DuckDbConnection(configured / "fixture.duckdb")
    askslm.config(db=configured / "fixture.duckdb", database=connection,
                  backend=CannedLlmBackend(broken))     # repair() returns sql unchanged

    plan = askslm.ask("anything")

    assert plan.error is not None and "nope" in plan.error
    connection.close()
