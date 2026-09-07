.PHONY: install check live-check test lint smoke

install:
	python -m pip install -r requirements-dev.txt

lint:
	ruff check .

test:
	pytest -m "not live"

live-check:
	pytest -m live

smoke:
	CAME_DEV_MODE=1 python scripts/smoke_app.py

check: lint test smoke

