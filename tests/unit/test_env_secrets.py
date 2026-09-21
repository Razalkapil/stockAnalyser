"""Secrets in .env actually reach the code that reads them.

Two halves of the same failure. Third-party API keys: pydantic-settings maps only
STK_-prefixed keys onto AppSettings and never writes to os.environ, while .env.example tells
you to put GROQ_API_KEY there -- so the key sat in the file and `stk ai` reported it "not
set". And STK_AUTH__TOKEN, which IS STK_-prefixed but had no field to land on, so
`extra="ignore"` swallowed it and the only token that worked was one from
`stk api token create`. These tests hold both shut.
"""

from __future__ import annotations

import pytest

from stk.config.settings import ENV_FILE_SECRETS, load_env_file_secrets


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_FILE_SECRETS:
        monkeypatch.delenv(name, raising=False)


def write(tmp_path, body: str):
    path = tmp_path / ".env"
    path.write_text(body)
    return path


def test_a_key_in_the_env_file_reaches_the_environment(tmp_path, monkeypatch):
    import os  # noqa: PLC0415

    path = write(tmp_path, "STK_APP__ENV=local\nGROQ_API_KEY=gsk_secret\n")
    assert load_env_file_secrets(path) == ["GROQ_API_KEY"]
    assert os.environ["GROQ_API_KEY"] == "gsk_secret"


def test_the_real_environment_wins_over_the_file(tmp_path, monkeypatch):
    """`GROQ_API_KEY=... stk ai ...` and systemd's EnvironmentFile must not be overridden by a
    stale value in a checked-out .env."""
    import os  # noqa: PLC0415

    monkeypatch.setenv("GROQ_API_KEY", "from_the_shell")
    path = write(tmp_path, "GROQ_API_KEY=from_the_file\n")
    assert load_env_file_secrets(path) == []
    assert os.environ["GROQ_API_KEY"] == "from_the_shell"


def test_an_empty_value_is_not_a_key(tmp_path):
    import os  # noqa: PLC0415

    path = write(tmp_path, "GROQ_API_KEY=\n")
    assert load_env_file_secrets(path) == []
    assert "GROQ_API_KEY" not in os.environ


def test_a_missing_env_file_is_not_an_error(tmp_path):
    assert load_env_file_secrets(tmp_path / "nope.env") == []


def test_only_the_named_secrets_are_copied(tmp_path):
    import os  # noqa: PLC0415

    path = write(tmp_path, "SOME_OTHER_SECRET=nope\nGROQ_API_KEY=yes\n")
    load_env_file_secrets(path)
    assert "SOME_OTHER_SECRET" not in os.environ


def test_the_example_file_documents_every_secret_we_load():
    """If .env.example tells you to put a key there, something must read it."""
    from pathlib import Path  # noqa: PLC0415

    example = Path(__file__).parents[2] / ".env.example"
    body = example.read_text()
    for name in ENV_FILE_SECRETS:
        if f"{name}=" in body:
            continue
        pytest.fail(f"{name} is loaded from .env but .env.example does not mention it")


class TestConfiguredApiToken:
    """STK_AUTH__TOKEN is a credential the API actually accepts, not a decorative env var."""

    @pytest.fixture(autouse=True)
    def _isolate_settings(self, monkeypatch):
        from stk.config.settings import get_settings  # noqa: PLC0415

        monkeypatch.delenv("STK_AUTH__TOKEN", raising=False)
        yield
        # Clear it BEFORE reloading: this fixture unwinds ahead of monkeypatch, so a test's
        # token would otherwise still be in the environment for the reload.
        monkeypatch.delenv("STK_AUTH__TOKEN", raising=False)
        get_settings(force_reload=True)  # never leave a test's token in the singleton

    def test_the_env_var_lands_on_a_real_setting(self, monkeypatch):
        from stk.config.settings import get_settings  # noqa: PLC0415

        monkeypatch.setenv("STK_AUTH__TOKEN", "t" * 40)
        assert get_settings(force_reload=True).auth.token == "t" * 40

    def test_blank_means_not_configured_not_an_empty_token(self, monkeypatch):
        """`.env.example` ships the key blank; that must not become a token the API compares."""
        from stk.config.settings import get_settings  # noqa: PLC0415

        monkeypatch.setenv("STK_AUTH__TOKEN", "")
        assert get_settings(force_reload=True).auth.token is None

    def test_a_short_token_is_refused_at_startup(self, monkeypatch):
        from pydantic import ValidationError  # noqa: PLC0415

        from stk.config.settings import get_settings  # noqa: PLC0415

        monkeypatch.setenv("STK_AUTH__TOKEN", "hunter2")
        with pytest.raises(ValidationError, match="at least 32"):
            get_settings(force_reload=True)

    def test_verify_accepts_the_configured_token_and_nothing_else(self):
        from stk.api.auth import verify_configured_token  # noqa: PLC0415

        tok = "x" * 40
        assert verify_configured_token(tok, tok) is True
        assert verify_configured_token(tok, "x" * 39) is False
        assert verify_configured_token(tok, "") is False

    def test_no_configured_token_accepts_nothing(self):
        """Not even an empty presented token -- `not configured` must not read as a match."""
        from stk.api.auth import verify_configured_token  # noqa: PLC0415

        assert verify_configured_token(None, "anything") is False
        assert verify_configured_token(None, "") is False
        assert verify_configured_token("", "") is False


def test_the_example_file_documents_the_api_token():
    from pathlib import Path  # noqa: PLC0415

    example = Path(__file__).parents[2] / ".env.example"
    assert "STK_AUTH__TOKEN=" in example.read_text()
