.PHONY: all format format-backend format-frontend lint check check-backend check-frontend test test-backend test-frontend

all: check test

format-backend:
	black backend/app backend/tests
	isort backend/app backend/tests

format-frontend:
	npm --prefix frontend run format

format: format-frontend format-backend

lint-backend:
	ruff check backend/app backend/tests
	mypy backend/app

lint-frontend:
	npm --prefix frontend run lint

lint: lint-frontend lint-backend

check-backend:
	black --check backend/app backend/tests
	isort --check-only backend/app backend/tests
	ruff check backend/app backend/tests
	mypy backend/app

check-frontend:
	npm --prefix frontend run format:check
	npm --prefix frontend run typecheck
	npm --prefix frontend run lint

check: check-frontend check-backend

test-backend:
	pytest backend/tests

test-frontend:
	npm --prefix frontend run typecheck

test: test-backend test-frontend
