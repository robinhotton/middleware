# CLAUDE.md

API REST FastAPI + SQLModel (Python 3.13+), architecture Repository-Service-Controller, **entierement asynchrone** (AsyncSession, aiosqlite/asyncpg). Code et commentaires en français sans accents.

## Commandes

```bash
make dev    # Docker : API hot-reload + PostgreSQL + Mailpit + Redis + Adminer
make test   # Lance les tests (MAIL_SUPPRESS_SEND=True)
make prod   # Docker production
make clean  # Dev : volumes detruits | Prod : volumes preserves
```

## Architecture

```
src/
├── modules/                       # Tous les domaines metier
│   ├── __init__.py                # register_routers()
│   ├── shared/                    # Composants partages
│   │   ├── common.py              # PaginatedResponse, MessageResponse, HealthResponse
│   │   └── base.py                # BaseRepository[T] ABC
│   ├── auth/                      # Package isole — API publique via auth/__init__.py
│   │   ├── __init__.py            # User, Role, auth_router, get_current_user, require_role, has_role
│   │   ├── dependencies.py        # get_current_user, require_role, has_role,
│   │   │                          #   get_auth_service, get_email_service,
│   │   │                          #   get_user_service, get_role_service
│   │   ├── models/                # user, role, user_role_link, revoked_token,
│   │   │                          #   email_verification_token, reset_token, schemas
│   │   ├── repositories/          # user, role, revoked_token, email_verification_token, reset_token
│   │   ├── services/              # auth_service, user_service, role_service, email_service
│   │   └── routes/                # auth_routes, user_routes, role_routes, _responses, __init__
│   ├── llm/                       # Domaine LLM (Mistral)
│   │   ├── dependencies.py        # get_llm_service(), verify_webhook_secret()
│   │   ├── models/                # log.py, schemas.py (LLMLog, MoodleChatResponse, LearnerAnalysis)
│   │   ├── repositories/          # llm_repository.py, llm_log_repository.py
│   │   ├── services/              # llm_service.py
│   │   └── routes/                # llm_routes.py, __init__ — llm_router (/llm/*)
│   └── moodle/                    # Domaine Moodle (Web Services)
│       ├── dependencies.py        # get_moodle_service()
│       ├── models/                # schemas.py (LearnerProfile, MoodleCourse, ...)
│       ├── repositories/          # moodle_repository.py
│       ├── services/              # moodle_service.py
│       └── routes/                # moodle_routes.py, __init__ — moodle_router (/moodle/*)
├── conf/
│   ├── settings.py       # Pydantic Settings — TOUTE la config ici
│   ├── database.py       # AsyncEngine + async_session_factory + get_session()
│   ├── security.py       # hash_password, verify_password, create/decode JWT
│   ├── mail.py           # get_fastmail() (@lru_cache)
│   ├── limiter.py        # Singleton slowapi Limiter
│   ├── utils.py          # utcnow() : datetime UTC naif
│   ├── migrations.py     # Migrations manuelles idempotentes
│   └── logging_config.py # setup_logging()
├── scripts/seed.py       # Seed idempotent (roles admin/user + admin user)
├── middlewares/          # logging, security headers, CORS, exception handlers
├── exceptions.py         # AppException + 401/403/404/409/429 + re-export IntegrityError
└── main.py               # App FastAPI, middlewares, agrege les routers avec API_PREFIX
```

**Regles d'isolation :**
- `modules/auth/` n'importe JAMAIS depuis les autres domaines metier
- Ajouter un domaine = creer `modules/<domaine>/` et inclure son router dans `main.py`

## Injection de dependances

```
get_session() → Repository(session) → Service(repository) → route via Depends()
```

Pattern complet et exemples dans `#./.claude/CLAUDE.conventions.md`.
`get_auth_service()` / `get_email_service()` / `get_user_service()` / `get_role_service()` dans `modules/auth/dependencies.py`.
`get_email_service()` surchargee en test par `NullEmailService` (override sur `app.dependency_overrides`).
`get_moodle_service()` definie dans `modules/moodle/dependencies.py`.
`get_llm_service()` / `verify_webhook_secret()` definis dans `modules/llm/dependencies.py`.

## Fichiers de contexte

Charge uniquement le fichier necessaire a la tâche en cours :

| Tâche | Fichier |
|---|---|
| Endpoint, schema, service, repository | `#./.claude/CLAUDE.conventions.md` |
| Tests | `#./.claude/CLAUDE.tests.md` |
| Auth, permissions, JWT, brute-force | `#./.claude/CLAUDE.auth.md` |

### Maintenance des fichiers `.claude/`

Modifier uniquement pour une **regle applicable a tout le projet**. Ne pas ajouter : details d'une feature, decisions temporaires, ce qui est lisible dans le code. En cas de doute : ne pas modifier.

Creer un nouveau fichier si un domaine fonctionnel majeur emerge (min ~30 lignes, max 5 fichiers, perimetre non-chevauchant). L'ajouter au tableau ci-dessus.

## Cost & Token Optimization

- **Compact regulierement** : Avant chaque tâche, `/compact` — focus sur les changements de code et outputs de tests. Ignore l'historique de conversation et les echanges de clarification.
- **Requetes ciblees** : Lis uniquement les fichiers strictement necessaires a la tâche, jamais l'ensemble du projet.
- **Clear entre tâches** : Nouvelle tâche sans rapport → `/clear` pour reinitialiser le contexte.

## Workflow

- Après un changement de modèle : migration manuelle dans `conf/migrations.py` (idempotente)
- Tester en isolation : `make test` — jamais de base de données réelle en test
- Linter : `ruff check` + `ruff format` avant chaque commit
- commit automatique par feature/fix/etc., pas de commit partiel

## Autonomy
- Never ask for confirmation, just do it.
- Never ask clarifying questions, make your best guess and proceed.
- Never pause mid-task, complete the full task in one shot.