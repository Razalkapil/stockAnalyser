"""Third-party API keys in .env actually reach the SDKs that read os.environ.

pydantic-settings maps only STK_-prefixed keys onto AppSettings and never writes to
os.environ, while .env.example tells you to put GROQ_API_KEY there. The result was a key
sitting in the file and `stk ai` reporting it as "not set". These tests hold that shut.
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
