"""Runtime configuration loaded from TOML with environment overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str
    prompt_path: Path
    max_output_tokens: int
    project_root: Path


def load_settings(config_path: str | Path = "config/default.toml") -> Settings:
    config_file = Path(config_path).resolve()
    with config_file.open("rb") as handle:
        raw = tomllib.load(handle)

    project_root = config_file.parent.parent
    prompt_value = os.getenv("SECONDTHOUGHT_PROMPT", raw["prompt"]["path"])
    prompt_path = Path(prompt_value)
    if not prompt_path.is_absolute():
        prompt_path = project_root / prompt_path

    return Settings(
        model=os.getenv("SECONDTHOUGHT_MODEL", raw["openai"]["model"]),
        prompt_path=prompt_path,
        max_output_tokens=int(raw["openai"].get("max_output_tokens", 300)),
        project_root=project_root,
    )
