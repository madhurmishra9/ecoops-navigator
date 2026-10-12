.PHONY: install test lint demo app api verify docker

install:
	pip install -e ".[app,api,dev]"

test:
	pytest -q

lint:
	ruff check src tests app

demo:
	ecoops generate --out data
	ecoops analyse --data data --out reports

verify:
	ecoops verify --all

app:
	streamlit run app/streamlit_app.py

api:
	uvicorn ecoops.api:app --reload

docker:
	docker build -t ecoops-navigator . && docker run --rm -p 8080:8080 ecoops-navigator
