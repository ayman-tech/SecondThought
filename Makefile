# Shortcuts for working on SecondThought. Run from the repo root.
#   make                        start the extension's local API (same as `make extension-api`)
#   make extension-api-health   check that a running extension API is up
#   make test                   run the test suite
#
# The website backend (website/api) is not built yet; it will get its own targets here.

# Use the project's virtualenv when it exists, otherwise whatever python3 is on PATH.
# Override with: make extension-api PYTHON=/path/to/python
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
EXTENSION_API_URL := http://127.0.0.1:8000

.PHONY: extension-api extension-api-health test
.DEFAULT_GOAL := extension-api

# Runs on 127.0.0.1:8000, which is where the Chrome extension looks for it. Ctrl+C stops it.
extension-api:
	$(PYTHON) -m extension.api.server

extension-api-health:
	@curl -fsS $(EXTENSION_API_URL)/health && echo || (echo "Server not reachable at $(EXTENSION_API_URL). Start it with: make extension-api" && exit 1)

test:
	$(PYTHON) -m pytest
