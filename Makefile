# Simple make targets for development/testing
.PHONY: run venv docker-up docker-down logs setup

run: venv
	. .venv/bin/activate && python src/bot.py

venv:
	python -m venv .venv || true
	. .venv/bin/activate && pip install -r requirements.txt

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

logs:
	docker compose logs -f

setup:
	bash scripts/setup_env.sh
