SHELL := /bin/bash
PROJECT := westfield-agent-back-python
PKG := westfield_agent_back_python

.PHONY: install run-api run-worker format lint test precommit docker-up docker-down docker-logs docker-build

install:
	poetry install

run-api:
	poetry run python -m $(PKG).main_api

run-worker:
	poetry run python -m $(PKG).main_worker

format:
	poetry run ruff format .
	poetry run ruff check . --fix

lint:
	poetry run ruff check .

test:
	poetry run pytest -v

precommit:
	poetry run pre-commit install

docker-build:
	docker build -t $(PROJECT):latest .

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

docker-logs:
	docker compose logs -f
