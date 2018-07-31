.PHONY: install test lint format run seed up down

install:
	pip install -r requirements-dev.txt

test:
	pytest

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

run:
	DJANGO_DEBUG=1 python manage.py runserver

seed:
	python manage.py migrate
	python manage.py seed_demo

up:
	docker compose up --build

down:
	docker compose down
