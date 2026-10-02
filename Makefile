SHELL := bash
.PHONY: dev test coverage prod clean help env-dev env-prod

VENV      = .venv
PYTHON    = $(VENV)/bin/python
PIP       = $(VENV)/bin/pip
PYTHON_OK = $(shell python3 -c "import sys; print(int(sys.version_info >= (3,13)))" 2>/dev/null)

COMPOSE_PROD = docker compose -f docker-compose.yml
COMPOSE_DEV = ${COMPOSE_PROD} -f docker-compose.dev.yml

# Commande pytest : venv local si Python >=3.13 disponible, sinon Docker
ifeq ($(PYTHON_OK),1)
PYTEST_CMD = $(VENV)/bin/activate
define run_pytest
	MAIL_SUPPRESS_SEND=True $(PYTHON) -m pytest tests/ -v $(1)
endef
else
PYTEST_CMD =
define run_pytest
	docker run --rm -v "$(CURDIR):/app" -w /app -e MAIL_SUPPRESS_SEND=True \
		python:3.13-slim bash -c "pip install -e '.[dev]' -q && python -m pytest tests/ -v $(1)"
endef
endif

# ============================================================================
# Aide
# ============================================================================

help:
	@echo "Commandes principales :"
	@echo ""
	@echo "  make dev      Lance l'API en developpement (Docker : hot-reload + Mailpit)"
	@echo "  make test     Lance les tests (venv si Python>=3.13, sinon Docker)"
	@echo "  make coverage Lance les tests avec rapport de couverture (seuil 80%)"
	@echo "  make prod     Lance en production via Docker Compose"
	@echo "  make clean    Detruit tous les environnements (venv + conteneurs)"
	@echo ""
	@echo "Gestion du .env :"
	@echo ""
	@echo "  make env-dev  Genere .env depuis .env.base + .env.dev  (dev sans Docker)"
	@echo "  make env-prod Genere .env depuis .env.base + .env.prod (prod sans Docker)"
	@echo ""

# ============================================================================
# Cible interne : venv + dependances (rejoue uniquement si le venv n'existe pas)
# ============================================================================

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

# ============================================================================
# Environnements
# ============================================================================

env-dev:
	@mkdir -p secrets
	@cat .env.base .env.dev > .env
	@echo ".env genere depuis .env.base + .env.dev"

env-prod:
	@mkdir -p secrets
	@cat .env.base .env.prod > .env
	@echo ".env genere depuis .env.base + .env.prod"

## dev: Lance la stack de developpement via Docker Compose
##      - API hot-reload       : http://localhost:8000  (docs : /docs)
##      - Mailpit (SMTP :1025) : http://localhost:8025
##      - Adminer              : http://localhost:8080
##      - PostgreSQL           : localhost:5432  (user: myapp | db: myapp)
##      - Redis                : localhost:6379
##      Logs : docker compose logs -f api
##      Stop : make clean
dev:
	@mkdir -p secrets
	@cat .env.base .env.dev > .env
	$(COMPOSE_DEV) up -d --build
	@. ./.env; \
	echo ""; \
	echo "API        : http://localhost:$${PORT}"; \
	echo "Docs       : http://localhost:$${PORT}/docs"; \
	echo "Mailpit    : http://localhost:8025  (SMTP: localhost:$${MAIL_PORT})"; \
	echo "Adminer    : http://localhost:8080"; \
	echo "PostgreSQL : localhost:$${DB_PORT}  (user: $${DB_USER} | db: $${DB_NAME})"; \
	echo "Redis      : localhost:6379"; \
	echo ""; \
	echo "Logs : docker compose logs -f api"; \
	echo "Stop : make clean"

## test: Lance les tests
##       - Python >=3.13 local : utilise le venv
##       - Sinon : utilise Docker python:3.13-slim (aucune installation requise)
##       - Aucun envoi SMTP reel (MAIL_SUPPRESS_SEND=True + mock conftest)
test: $(PYTEST_CMD)
	$(call run_pytest,)

## coverage: Lance les tests avec rapport de couverture de code (seuil 80%)
coverage: $(PYTEST_CMD)
	$(call run_pytest,--cov=src --cov-report=term-missing --cov-fail-under=80)

## prod: Lance en production via Docker Compose (API + PostgreSQL)
prod:
	@mkdir -p secrets
	@cat .env.base .env.prod > .env
	$(COMPOSE_PROD) up -d --build

# ============================================================================
# Destruction complete
# ============================================================================

## clean: Detruit tous les environnements
##        - Arrete les conteneurs dev (volumes inclus) et prod (sans volumes)
##        - Supprime le venv, les caches et la base SQLite
clean:
	@$(COMPOSE_DEV) down -v 2>/dev/null || true
	@$(COMPOSE_PROD) down 2>/dev/null || true
	rm -rf $(VENV)
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov build dist
	rm -f  .coverage .coverage.*
	find . -type d -name "__pycache__" -not -path "./.git/*" | xargs rm -rf
	find . -name "*.egg-info" -type d | xargs rm -rf
	rm -f  database.db .env
	@echo "✅ Tous les environnements ont ete detruits"
