## Commands

- run: `./run.sh <appid|url|name>`
- test: `python3 -m pytest -q`
- test-changed: `scripts/test_changed.sh`
- lint: `pre-commit run --all-files`
- coverage: `python3 -m pytest -q --cov --cov-branch --cov-report=xml`
- coverage-gaps: `coverage-gaps coverage.xml`
