#!/bin/sh
set -eu
python -m website.api.check_setup
python -c 'import os, torch; device=os.getenv("SECONDTHOUGHT_WEBSITE_DEVICE", "cpu"); assert device != "cuda" or torch.cuda.is_available(), "CUDA requested but unavailable: check the PyTorch build, NVIDIA driver and container GPU access"'
exec "$@"
