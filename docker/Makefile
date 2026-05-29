.PHONY: build up down logs clean ps

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

clean:
	docker compose down -v --rmi local

ps:
	docker compose ps
