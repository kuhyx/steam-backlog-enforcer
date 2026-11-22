## Commands

- run: `./run.sh <appid|url|name>`
- test: `python3 -m pytest -q`
- test-changed: `scripts/test_changed.sh`
- lint: `pre-commit run --all-files`
- coverage: `python3 -m pytest -q --cov --cov-branch --cov-report=xml`
- coverage-gaps: `coverage-gaps coverage.xml`
- deploy: `scripts/deploy.sh` (fast-forwards kuhy's checkout `~/src/steam-game-installer` to origin/main, refusing a dirty tree, reruns `./run.sh --deps-only`, then checks the CLI starts; idempotent, non-zero unless at origin/main and healthy; test: `tests/test_deploy.py`)
