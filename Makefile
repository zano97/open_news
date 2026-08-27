.PHONY: help install dev up down logs test test-e2e lint typecheck fmt check seed verify-feeds fonts migrate revision clean

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

help: ## Mostra questo aiuto
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Crea il venv e installa le dipendenze di sviluppo
	python3.12 -m venv .venv || python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

dev: up ## Avvia tutto lo stack in locale (alias di `up`)

up: ## docker compose up (build incluso)
	docker compose up --build -d
	@echo "API:  http://localhost:8000  ·  Caddy: http://localhost (https se dominio configurato)"

down: ## Ferma lo stack
	docker compose down

logs: ## Log dello stack
	docker compose logs -f --tail=100

test: ## Esegue i test (senza e2e) con coverage sul core
	$(PY) -m pytest --cov=core --cov-report=term-missing

test-e2e: ## Test end-to-end Playwright (richiede stack attivo o server locale)
	$(PY) -m pytest -m e2e --no-cov

lint: ## Ruff
	$(PY) -m ruff check core apps tests scripts

typecheck: ## Mypy strict
	$(PY) -m mypy core apps

fmt: ## Formatta con ruff
	$(PY) -m ruff format core apps tests scripts
	$(PY) -m ruff check --fix core apps tests scripts

check: lint typecheck test ## Tutti i controlli di qualità

migrate: ## Applica le migrazioni al DB configurato (DATABASE_URL)
	$(PY) -m alembic upgrade head

revision: ## Nuova migrazione: make revision m="messaggio"
	$(PY) -m alembic revision -m "$(m)"

seed: ## Popola il sistema: fonti dal catalogo + assetti proprietari + ~24h di dati
	$(PY) -m scripts.seed

verify-feeds: ## Verifica via HTTP reale tutti i feed in data/sources.yaml e aggiorna lo stato
	$(PY) -m scripts.verify_feeds

fonts: ## Scarica i font OFL self-hosted (Playfair Display, EB Garamond, Special Elite)
	$(PY) -m scripts.fetch_fonts

clean: ## Rimuove artefatti di build e cache
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
