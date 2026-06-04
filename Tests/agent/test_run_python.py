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
