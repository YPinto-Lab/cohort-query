"""Where config comes from, and in what order. The lab server must never be asked
a question -- that is what the environment override is for."""
from cohortquery.settings_file import stored_settings, write_settings


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch):
    """CI and the lab server set env vars and must never hit a prompt or a file."""
    config = tmp_path / "config.toml"
    write_settings(config, db="/from/file.duckdb", llm_key="file-key")
    monkeypatch.setenv("COHORTQUERY_DB", "/from/env.duckdb")
    monkeypatch.setenv("COHORTQUERY_LLM_KEY", "env-key")

    settings = stored_settings(config)

    assert settings == {"db": "/from/env.duckdb", "llm_key": "env-key"}


def test_the_file_is_used_when_the_environment_is_empty(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    write_settings(config, db="/from/file.duckdb", llm_key="file-key")
    monkeypatch.delenv("COHORTQUERY_DB", raising=False)
    monkeypatch.delenv("COHORTQUERY_LLM_KEY", raising=False)

    settings = stored_settings(config)

    assert settings == {"db": "/from/file.duckdb", "llm_key": "file-key"}


def test_nothing_stored_anywhere_returns_empty_so_the_app_can_prompt(tmp_path, monkeypatch):
    monkeypatch.delenv("COHORTQUERY_DB", raising=False)
    monkeypatch.delenv("COHORTQUERY_LLM_KEY", raising=False)

    assert stored_settings(tmp_path / "absent.toml") == {}


def test_a_written_file_is_not_world_readable(tmp_path):
    """It holds an API key."""
    config = tmp_path / "config.toml"

    write_settings(config, db="/x.duckdb", llm_key="secret")

    assert (config.stat().st_mode & 0o077) == 0
