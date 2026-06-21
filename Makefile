.PHONY: up down test migrate migrations health lint format shell db-rollback

up:
	docker compose up -d

down:
	docker compose down

test:
	docker compose run --rm app pytest

migrate:
	docker compose run --rm app alembic upgrade head

db-rollback:
	docker compose run --rm app alembic downgrade -1

migrations:
	docker compose run --rm app alembic revision --autogenerate -m "migration"

health:
	docker compose run --rm app python -m opener.cli.health

lint:
	docker compose run --rm app ruff check src tests
	docker compose run --rm app mypy src tests

format:
	docker compose run --rm app black src tests
	docker compose run --rm app ruff check --fix src tests

shell:
	docker compose run --rm app python
