from pathlib import Path

from secondthought.config import load_settings


def test_load_settings_resolves_prompt_from_project_root(monkeypatch):
    monkeypatch.delenv("SECONDTHOUGHT_MODEL", raising=False)
    monkeypatch.delenv("SECONDTHOUGHT_PROMPT", raising=False)
    settings = load_settings("config/default.toml")

    assert settings.model == "gpt-4.1-mini-2025-04-14"
    assert settings.prompt_path == Path("prompts/constrained.txt").resolve()
