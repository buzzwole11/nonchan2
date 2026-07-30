.DEFAULT_GOAL := help
SHELL := /bin/bash

API := apps/api
UV := uv

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Install every dependency (Node workspaces + Python API)
	npm install
	cd $(API) && $(UV) venv --python 3.11 && $(UV) pip install -e ".[dev]"

.PHONY: db-up
db-up: ## Start PostgreSQL and Redis
	docker compose up -d db redis

.PHONY: db-down
db-down: ## Stop the containers (keeps the data volume)
	docker compose down

.PHONY: db-reset
db-reset: ## Destroy and recreate the database volume
	docker compose down -v
	docker compose up -d db redis

.PHONY: migrate
migrate: ## Apply migrations to the development database
	cd $(API) && $(UV) run alembic upgrade head

.PHONY: seed
seed: migrate ## Load the field taxonomy and the sample corpus
	cd $(API) && $(UV) run python -m papermatch_api.cli seed

.PHONY: fixtures
fixtures: ## Regenerate fixtures/papers.sample.json
	node scripts/generate-fixtures.mjs

.PHONY: api
api: ## Run the API with reload on :8000
	cd $(API) && $(UV) run uvicorn papermatch_api.main:app --reload --port 8000

.PHONY: mobile
mobile: ## Start the Expo dev server
	npm run start --workspace @papermatch/mobile

.PHONY: test
test: test-api test-ts ## Run every test suite

.PHONY: test-api
test-api: ## Run the Python tests (integration tests need a database)
	cd $(API) && $(UV) run pytest

.PHONY: test-unit
test-unit: ## Run only the tests that need no database
	cd $(API) && $(UV) run pytest -m "not integration and not e2e"

.PHONY: test-ts
test-ts: ## Run the TypeScript tests
	npm test

.PHONY: lint
lint: ## Lint and typecheck everything
	cd $(API) && $(UV) run ruff check . && $(UV) run ruff format --check . && $(UV) run mypy papermatch_api
	npm run typecheck

.PHONY: format
format: ## Autoformat the Python code
	cd $(API) && $(UV) run ruff format . && $(UV) run ruff check . --fix
