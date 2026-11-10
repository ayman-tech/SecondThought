"""Configs must resolve their relative paths from the repo root, wherever the config file lives."""

from pathlib import Path

from secondthought.config import load_settings

REPO = Path(__file__).resolve().parents[1]


def test_extension_config_resolves_model_dirs_from_the_repo_root():
    settings = load_settings(REPO / "extension/api/config.toml")

    assert settings.backend == "t5"
    assert settings.project_root == REPO
    assert [step.model_dir for step in settings.t5_steps] == [REPO / "models/both-t5"] * 2
    assert [step.prefix for step in settings.t5_steps] == ["detoxify: ", "formalize: "]


def test_openai_config_still_finds_its_prompt():
    settings = load_settings(REPO / "config/default.toml")

    assert settings.project_root == REPO
    assert settings.prompt_path == REPO / "prompts/constrained.txt"
    assert settings.prompt_path.is_file()


def test_project_root_can_be_overridden_for_containers(tmp_path, monkeypatch):
    monkeypatch.setenv("SECONDTHOUGHT_ROOT", str(tmp_path))

    settings = load_settings(REPO / "extension/api/config.toml")

    assert settings.project_root == tmp_path.resolve()
    assert settings.t5_steps[0].model_dir == tmp_path.resolve() / "models/both-t5"


def test_config_outside_any_project_keeps_the_old_grandparent_rule(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    config = nested / "standalone.toml"
    config.write_text(
        '[rewriter]\nbackend = "t5"\n\n[[t5.steps]]\nname = "x"\nmodel_dir = "m"\nprefix = "p: "\n',
        encoding="utf-8",
    )

    settings = load_settings(config)

    assert settings.project_root == (tmp_path / "a").resolve()
