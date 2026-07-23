.PHONY: format lint typecheck test check

format:
	black app tests
	ruff check app tests --fix

lint:
	ruff check app tests

typecheck:
	mypy app

test:
	pytest tests

check:
	black --check app tests
	ruff check app tests
	mypy app
	pytest tests
