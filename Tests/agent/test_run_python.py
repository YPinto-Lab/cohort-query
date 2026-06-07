from pathlib import Path

import pandas as pd
import pytest
from agent.workspace import Workspace
from agent.session import Session
from agent.tools.run_python import run_python_registry


def test_basic_arithmetic(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    r = run_python_registry.execute(sess, "run_python", {"code": "print(1+1)"})
    assert not r.is_error, r.error
    assert "2" in r.summary["stdout"]
    assert r.summary["new_handles"] == []
    assert r.summary["imports_used"] == []


def test_handle_roundtrip_creates_new_handle(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    h = sess.variables.put(pd.DataFrame({"x": [1, 2, 3]}), hint="df")
    code = f"out = {h}.assign(y=lambda d: d.x*2)"
    r = run_python_registry.execute(sess, "run_python", {"code": code})
    assert not r.is_error, r.error
    assert r.summary["new_handles"]
    new_handle = r.summary["new_handles"][0]
    assert sess.variables.get(new_handle)["y"].tolist() == [2, 4, 6]


def test_imports_used_extracted(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    code = "import numpy\nfrom scipy import stats\nprint(numpy.array([1,2]).sum())"
    r = run_python_registry.execute(sess, "run_python", {"code": code})
    assert not r.is_error, r.error
    assert set(r.summary["imports_used"]) >= {"numpy", "scipy"}


def test_exception_is_captured(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    r = run_python_registry.execute(sess, "run_python", {"code": "raise ValueError('nope')"})
    assert r.is_error
    assert "nope" in r.error


def test_timeout(tmp_path):
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    r = run_python_registry.execute(
        sess, "run_python", {"code": "import time; time.sleep(5)", "timeout_s": 1},
    )
    assert r.is_error
    assert "timeout" in r.error.lower()


def test_unpicklable_recognized_object_does_not_crash_run(tmp_path):
    # A biom.Table with metadata holds a non-picklable lambda, so promoting it to a
    # handle fails. run_python must still return the snippet's stdout, not crash.
    root = tmp_path / "ws"; root.mkdir()
    sess = Session.start(Workspace.open(root))
    code = (
        "import numpy as np\n"
        "from biom import Table\n"
        "t = Table(np.array([[1.,2.],[3.,4.]]), ['o1','o2'], ['s1','s2'])\n"
        "t.add_metadata({'s1':{'g':'a'},'s2':{'g':'b'}}, axis='sample')\n"
        "print('shape', t.shape)\n"
    )
    r = run_python_registry.execute(sess, "run_python", {"code": code})
    assert not r.is_error, r.error
    assert "shape (2, 2)" in r.summary["stdout"]
    assert r.summary["new_handles"] == []          # the table could not be kept
    assert "not kept as handles" in r.summary["stdout"]


def test_operating_manual_documents_stateless_execution():
    import agent
    manual = (Path(agent.__file__).parent / "operating_manual.md").read_text()
    assert "fresh subprocess" in manual.lower()
    assert "write_file" in manual and "run_script" in manual
    # every run_python snippet should open with a one-line intent comment (drives the UI label)
    assert "one-line" in manual and "intent" in manual


def test_operating_manual_gives_facade_build_recipe():
    import agent
    manual = (Path(agent.__file__).parent / "operating_manual.md").read_text()
    # the concrete facade calls the agent kept failing to discover
    assert "taxonomy.load" in manual
    assert "taxonomy.lineage_table" in manual
    assert "metadata.extract" in manual
    # the specific pivot fix (pivot_table/aggfunc, not DataFrame.pivot)
    assert "pivot_table" in manual
    assert 'aggfunc="sum"' in manual
    # always build from the whole dataset, never one bioproject
    assert "all bioprojects" in manual.lower()


def test_operating_manual_directs_queries_to_the_feature_table():
    import agent
    manual = (Path(agent.__file__).parent / "operating_manual.md").read_text()
    # query the built table, not the raw inputs
    assert "metadata_to_dataframe" in manual
    assert "current feature table" in manual.lower()
    # track pipeline position and ask when ambiguous
    assert "ambiguous" in manual.lower() and "ask" in manual.lower()


def test_run_python_docstring_warns_about_statelessness():
    from agent.tools.run_python import run_python_registry
    schema = {s["name"]: s for s in run_python_registry.schemas()}["run_python"]
    desc = schema["description"].lower()
    assert "not persist" in desc
    assert "run_script" in desc
