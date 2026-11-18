# Shortcuts for working on SecondThought. Run from the repo root.
#   make                        start the extension's local API (same as `make extension-api`)
#   make extension-api-health   check that a running extension API is up
#   make test                   run the test suite
#
# The website runs independently at http://127.0.0.1:8001.

# Run Python commands in uv's project environment.
# Override the uv executable with: make website UV=/path/to/uv

EXTENSION_API_URL := http://127.0.0.1:8000

.PHONY: extension-api extension-api-health website website-health test website-test
.DEFAULT_GOAL := extension-api

# Runs on 127.0.0.1:8000, which is where the Chrome extension looks for it. Ctrl+C stops it.
extension-api:
	uv run python -m extension.api.server

extension-api-health:
	@curl -fsS $(EXTENSION_API_URL)/health && echo || (echo "Server not reachable at $(EXTENSION_API_URL). Start it with: make extension-api" && exit 1)

website:
	uv run python -m website.api.server

website-health:
	@curl -fsS http://127.0.0.1:8001/health/ready

website-test:
	uv run python -m pytest tests/website_api tests/lab -q
	cd website/frontend && node --test tests/*.test.js

test:
	uv run python -m pytest
