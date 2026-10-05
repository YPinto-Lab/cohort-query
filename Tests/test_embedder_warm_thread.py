"""The session warms the embedder on a background thread at startup
(Docs/plan-warm-embedder-on-startup.md) while the real call may land from the
main thread moments later -- both must resolve to the same model, never two."""
import threading

import cohortquery
from cohortquery import runtime


def test_embedder_warm_thread_no_double_load(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("cohortquery.adapters.open_local_embedder",
                        lambda: calls.append(1) or object())
    db_path = tmp_path / "fixture.duckdb"
    db_path.touch()
    cohortquery.config(db=db_path, llm="gemini", llm_key="unused-for-this-test")

    warm = threading.Thread(target=runtime.embedder)
    warm.start()
    result = runtime.embedder()
    warm.join()

    assert len(calls) == 1
    assert result is runtime.embedder()
