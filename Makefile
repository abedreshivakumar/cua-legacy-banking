.PHONY: setup app test lint discover-spike evidence

setup:
	uv sync
	uv run playwright install chromium

app:
	uv run uvicorn target_app.app:app --port $${COREBANK_PORT:-8800} --reload

test:
	uv run pytest -q

lint:
	uv run ruff check src/ tests/ target_app/ scripts/ --fix
	uv run ruff format src/ tests/ target_app/ scripts/
	uv run mypy src/

# Costs a small amount of real Anthropic API credit — a capped, 6-step live
# run. See docs/DECISIONS.md's "G0 spike" entry.
discover-spike:
	uv run python scripts/spike_g0.py

# Offline — ScriptedModelClient, zero model calls. Writes
# evidence/demo_member_inquiry/, clearly labeled as a demo run, not the
# real live-LLM evidence the brief asks for.
evidence:
	uv run python scripts/collect_evidence.py
