.PHONY: setup data portals test lint demo evals ui
setup:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && playwright install chromium
data:
	python -m company_env.data.make_data
portals:
	python -m ai_operator.portals
test:
	pytest -q
lint:
	ruff check .
demo: data
	python -m ai_operator.run "Reimburse Priya's Mumbai trip" --files company_env/data/receipts/mumbai --start-portals
evals: data
	python -m evals.run_evals --runs 5
ui: data
	python -m ai_operator.ui.server
