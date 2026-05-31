import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Accessors.matrix_writers.matrix_writer_factory import MatrixWriterFactory


def _matrix():
    matrix = pd.DataFrame({"superkingdom||Bacteria||2": [2, 2]},
                          index=pd.Index(["SRR1", "SRR2"], name="acc"))
    total_reads = pd.Series([2, 2], index=pd.Index(["SRR1", "SRR2"], name="acc"))
    taxon_key_lookup = pd.DataFrame({"taxon_key": ["superkingdom||Bacteria||2"], "tax_id": [2],
                                     "rank": ["superkingdom"], "name": ["Bacteria"]})
    tax_id_lineage_lookup = pd.DataFrame({"tax_id": [2], "superkingdom": ["Bacteria"]})
    return AbundanceMatrix(
        matrix=matrix,
        total_reads=total_reads,
        taxon_key_lookup=taxon_key_lookup,
        tax_id_lineage_lookup=tax_id_lineage_lookup,
    )


def test_counts_writer_creates_csv(tmp_path):
    path = MatrixWriterFactory().create("counts").write(_matrix(), tmp_path / "counts.csv")

    assert path.exists()
    assert "superkingdom||Bacteria||2" in path.read_text()


def test_relative_writer_normalizes(tmp_path):
    path = MatrixWriterFactory().create("relative").write(_matrix(), tmp_path / "rel.csv")

    written = pd.read_csv(path, index_col=0)
    assert abs(written.loc["SRR1"].sum() - 1.0) < 1e-9


def test_maaslin_writer_is_wide_tsv(tmp_path):
    path = MatrixWriterFactory().create("maaslin").write(_matrix(), tmp_path / "m.tsv")

    written = pd.read_csv(path, sep="\t", index_col=0)
    assert list(written.index) == ["SRR1", "SRR2"]
    assert list(written.columns) == ["superkingdom||Bacteria||2"]


def test_biom_writer_roundtrip(tmp_path):
    import json

    path = MatrixWriterFactory().create("biom").write(_matrix(), tmp_path / "t.biom")

    table = json.loads(path.read_text())
    assert table["shape"] == [1, 2]
    assert [row["id"] for row in table["rows"]] == ["superkingdom||Bacteria||2"]
    assert {col["id"] for col in table["columns"]} == {"SRR1", "SRR2"}
