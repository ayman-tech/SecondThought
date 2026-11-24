"""Download the rewriting model into models/both-t5.

The installers run this with `uv run python scripts/get_model.py`. It tries
Hugging Face first, then a both-t5.zip attached to the latest GitHub release,
and prints a short message instead of a traceback when neither has it.

  SECONDTHOUGHT_MODEL_REPO  the Hugging Face repo (default below)
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile

HF_REPO = os.getenv("SECONDTHOUGHT_MODEL_REPO", "SAI-RAHUL-M/secondthought-both-t5")
RELEASE_ZIP = "https://github.com/ayman-tech/SecondThought/releases/latest/download/both-t5.zip"
MODELS = Path(__file__).resolve().parents[1] / "models"
TARGET = MODELS / "both-t5"


def ready() -> bool:
    return (TARGET / "model.safetensors").is_file()


def from_hugging_face() -> None:
    from huggingface_hub import snapshot_download

    print(f"    Downloading the model from Hugging Face ({HF_REPO}, about 240 MB)...", flush=True)
    snapshot_download(HF_REPO, local_dir=TARGET,
                      allow_patterns=["*.json", "*.safetensors", "*.model"])


def from_release() -> None:
    print("    Trying the GitHub release instead...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "both-t5.zip"
        with urllib.request.urlopen(RELEASE_ZIP, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        MODELS.mkdir(exist_ok=True)
        zipfile.ZipFile(archive).extractall(MODELS)


def main() -> int:
    if ready():
        print("    Found models/both-t5.")
        return 0
    for source in (from_hugging_face, from_release):
        try:
            source()
        except Exception as error:  # a missing repo, no internet, an old release...
            print(f"    Not there ({type(error).__name__}).")
        if ready():
            print("    Downloaded the model into models/both-t5.")
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
