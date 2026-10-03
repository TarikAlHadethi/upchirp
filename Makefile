.PHONY: setup sim replay score up down ui live deploy test evals lint

# Windows venvs put scripts in Scripts/, everything else in bin/
ifeq ($(OS),Windows_NT)
PYTHON ?= py -3.12
BIN := .venv/Scripts
else
PYTHON ?= python3.12
BIN := .venv/bin
endif

setup:
	$(PYTHON) -m venv .venv
	$(BIN)/python -m pip install -e ".[dev,agent,platform]"

sim:
	$(BIN)/upchirp sim --scene default

replay:
	$(BIN)/upchirp replay --session latest

score:
	$(BIN)/upchirp score --session latest

# Redpanda, PostgreSQL (Timescale + pgvector) and Ollama, on localhost only
up:
	docker compose up -d
	docker exec upchirp-ollama ollama pull qwen2.5:7b-instruct
	docker exec upchirp-ollama ollama pull nomic-embed-text
	$(BIN)/upchirp index-docs

down:
	docker compose down

ui:
	cd ui && npm ci && npm run build

# Whole platform on a looping replay; open http://127.0.0.1:8000
live:
	$(BIN)/upchirp live --session latest

# Public demo (step 6): ship committed code to the server. See infra/.
deploy:
	bash deploy/demo/deploy.sh

test:
	$(BIN)/pytest tests

evals:
	$(BIN)/pytest evals

lint:
	$(BIN)/ruff check .
	$(BIN)/mypy src
