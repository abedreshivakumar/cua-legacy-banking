.PHONY: setup app test lint demo-offline discover evidence

setup:
	uv sync
	uv run playwright install chromium

app:
	uv run uvicorn target_app.app:app --port $${COREBANK_PORT:-8800} --reload

test:
	uv run pytest -q

lint:
	uv run ruff check src/ tests/ target_app/ --fix
	uv run ruff format src/ tests/ target_app/

demo-offline:
	uv run pytest -q -m "not live"

discover:
	uv run cua discover --target corebank-local --goal "$${GOAL}"

evidence:
	uv run python scripts/produce_evidence.py
