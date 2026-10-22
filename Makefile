# Comandos habituales. Cada línea se puede ejecutar a mano.
COMPOSE = docker compose -f deploy/docker-compose.yml --env-file .env
-include .env
export

.PHONY: help
help: ## Lista los comandos
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Crea .env e instala dependencias para desarrollo local
	@test -f .env || cp .env.example .env
	uv sync
	pnpm --dir web install

.PHONY: up
up: ## Levanta base, API y consola con Docker
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Detiene (conserva los datos)
	$(COMPOSE) down

.PHONY: reset
reset: ## Detiene y BORRA los datos del agente
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Logs de la API y la consola
	$(COMPOSE) logs -f api web

.PHONY: init
init: ## Crea la empresa y el primer usuario; se enrola si hay ENROLL_TOKEN
	$(COMPOSE) run --rm api agente init --empresa "$(EMPRESA)" --admin "$(ADMIN_EMAIL)" \
		$(if $(ENROLL_TOKEN),--plataforma "$(PLATAFORMA_URL)" --enroll "$(ENROLL_TOKEN)",)

.PHONY: enroll
enroll: ## Conecta al portal: make enroll ENROLL_TOKEN=ge_…
	$(COMPOSE) run --rm api agente enroll --plataforma "$(PLATAFORMA_URL)" --token "$(ENROLL_TOKEN)"

.PHONY: demo-traffic
demo-traffic: ## Genera 30 conversaciones de prueba
	$(COMPOSE) run --rm api agente demo-traffic --conversations 30

.PHONY: reminders
reminders: ## El agente redacta recordatorios para la bandeja de aprobación
	$(COMPOSE) run --rm api agente prepare-reminders --limit 10

.PHONY: payments
payments: ## SIMULACIÓN: avanza 15 días (plazo máximo de una promesa) y registra pagos
	$(COMPOSE) run --rm api agente simulate-payments --days 15

.PHONY: dev-api
dev-api: ## API con recarga automática (requiere Postgres en 5433: make up)
	uv run uvicorn agente.api.app:app --reload --port 8100

.PHONY: dev-web
dev-web: ## Consola con recarga automática
	pnpm --dir web dev

.PHONY: lint
lint: ## Estilo y tipos
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src
	pnpm --dir web typecheck
	pnpm --dir web lint

.PHONY: test
test: ## Pruebas (necesitan Postgres: TEST_DATABASE_URL)
	uv run pytest

.PHONY: vendor-sdk
vendor-sdk: ## Reconstruye la rueda del SDK desde el repo del portal (PORTAL=../gobernance-app)
	uv build --wheel -o vendor $(or $(PORTAL),../gobernance-app)/packages/sdk
	uv lock
