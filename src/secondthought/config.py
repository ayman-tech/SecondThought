"""Runtime configuration loaded from TOML with environment overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .t5_rewriter import T5Step


@dataclass(frozen=True)
class Settings:
    model: str
    prompt_path: Path
    max_output_tokens: int
    project_root: Path
    # "openai" (default) or "t5"; the T5 fields are only used by "t5".
    backend: str = "openai"
    t5_steps: tuple[T5Step, ...] = ()
    t5_max_input_tokens: int = 128
    t5_max_new_tokens: int = 128
    t5_num_beams: int = 4
    t5_facts_guard: bool = True


def _resolve(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _find_project_root(config_file: Path) -> Path:
    """Where relative paths in a config (model_dir, the prompt path) are resolved from.

    SECONDTHOUGHT_ROOT wins when set, which suits a container that has no pyproject.toml.
    Otherwise it is the nearest ancestor of the config file holding pyproject.toml, so a config
    can live anywhere in the repo (config/, extension/api/, ...). The last resort is the old
    rule: the config file's grandparent.
    """
    override = os.getenv("SECONDTHOUGHT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    for parent in config_file.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return config_file.parent.parent


def load_settings(config_path: str | Path = "config/default.toml") -> Settings:
    config_file = Path(config_path).resolve()
    with config_file.open("rb") as handle:
        raw = tomllib.load(handle)

    project_root = _find_project_root(config_file)
    backend = raw.get("rewriter", {}).get("backend", "openai")
    if backend not in ("openai", "t5"):
        raise ValueError(f"Unknown rewriter backend {backend!r}; use 'openai' or 't5'")

    if backend == "t5":
        t5 = raw.get("t5", {})
        steps = tuple(
            T5Step(
                name=step["name"],
                model_dir=_resolve(project_root, step["model_dir"]),
                prefix=step["prefix"],
            )
            for step in t5.get("steps", [])
        )
        if not steps:
            raise ValueError(f"{config_file} sets backend = 't5' but has no [[t5.steps]]")
        return Settings(
            model="",
            prompt_path=Path(),
            max_output_tokens=0,
            project_root=project_root,
            backend=backend,
            t5_steps=steps,
            t5_max_input_tokens=int(t5.get("max_input_tokens", 128)),
            t5_max_new_tokens=int(t5.get("max_new_tokens", 128)),
            t5_num_beams=int(t5.get("num_beams", 4)),
            t5_facts_guard=bool(t5.get("facts_guard", True)),
        )

    prompt_value = os.getenv("SECONDTHOUGHT_PROMPT", raw["prompt"]["path"])

    return Settings(
        model=os.getenv("SECONDTHOUGHT_MODEL", raw["openai"]["model"]),
        prompt_path=_resolve(project_root, prompt_value),
        max_output_tokens=int(raw["openai"].get("max_output_tokens", 300)),
        project_root=project_root,
    )
