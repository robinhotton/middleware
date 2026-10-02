# DigiLearnia — Middleware API

API REST FastAPI pour la plateforme DigiLearnia : authentification JWT RS256, gestion des roles, integration Moodle et LLM (Mistral).

## Stack

| Composant | Technologie |
|---|---|
| Framework | FastAPI + Uvicorn (ASGI) |
| ORM | SQLModel (Pydantic v2 + SQLAlchemy async) |
| Base de donnees | PostgreSQL (Docker) / SQLite (tests) |
| Auth | JWT RS256 asymetrique (PyJWT + cryptography) |
| Rate limiting | slowapi + Redis (ou in-memory) |
| Mails | fastapi-mail (SMTP standard) |
| Dev mail | Mailpit (intercepteur SMTP local) |
| LLM | Mistral AI (via HTTP, compatible OpenAI) |
| Moodle | Web Services REST (token admin) |
| Configuration | Pydantic Settings (.env) |
| Tests | Pytest + pytest-asyncio + HTTPX |
| CI | GitLab CI (`.gitlab-ci.yml`) |

## Quickstart

```bash
# 1. Cloner le depot
git clone <url-du-repo> && cd middleware

# 2. Creer les secrets (jamais commites — lus automatiquement au demarrage)
mkdir -p secrets

# Cles JWT RS256 (obligatoires)
openssl genrsa -out secrets/jwt_private_key.txt 2048
openssl rsa -in secrets/jwt_private_key.txt -pubout -out secrets/jwt_public_key.txt

# Mot de passe admin (obligatoire — min 12 car., 1 maj, 1 chiffre, 1 symbole)
echo "VotreMotDePasse!2024" > secrets/admin_password.txt

# Secrets optionnels en dev (laisser vide desactive la fonctionnalite)
echo "sk-..."        > secrets/mistral_api_key.txt       # https://console.mistral.ai/api-keys/
echo "..."           > secrets/moodle_admin_token.txt    # Moodle > Admin > Web services > Tokens
python3 -c "import secrets; print(secrets.token_hex(32))" > secrets/moodle_webhook_secret.txt
echo "xsmtp-..."    > secrets/brevo_smtp_key.txt         # Brevo > Settings > SMTP Keys (prod)

# 3. Lancer la stack de developpement
# (.env genere automatiquement depuis .env.base + .env.dev)
make dev
```

`make dev` demarre via Docker Compose : API en hot-reload, PostgreSQL, Mailpit (UI http://localhost:8025), Redis et Adminer.

> **Secrets** — charges automatiquement depuis `secrets/<nom>.txt` (dev) ou `/run/secrets/<nom>` (Docker prod). Ne jamais ecrire les secrets directement dans `.env`.
>
> | Fichier | Description | Env |
> |---|---|---|
> | `secrets/jwt_private_key.txt` | Cle privee RS256 | dev + prod |
> | `secrets/jwt_public_key.txt` | Cle publique RS256 | dev + prod |
> | `secrets/admin_password.txt` | Mot de passe compte admin | dev + prod |
> | `secrets/db_password.txt` | Mot de passe PostgreSQL | prod |
> | `secrets/db_readonly_password.txt` | Mot de passe user read-only | prod |
> | `secrets/mistral_api_key.txt` | Cle API Mistral | dev + prod |
> | `secrets/moodle_admin_token.txt` | Token admin Moodle Web Services | dev + prod |
> | `secrets/moodle_webhook_secret.txt` | Secret webhook Moodle → API | dev + prod |
> | `secrets/brevo_smtp_key.txt` | Cle SMTP Brevo (prod) | prod |

## Architecture

```
src/
├── modules/
│   ├── shared/            # PaginatedResponse, MessageResponse, BaseRepository
│   ├── auth/              # JWT, roles, brute-force, email verification, reset password
│   ├── llm/               # Webhook chat + analyse pedagogique (Mistral)
│   └── moodle/            # Agregation profil apprenant (Moodle Web Services)
├── conf/
│   ├── settings.py        # Pydantic Settings — TOUTE la config
│   ├── database.py        # AsyncEngine + get_session()
│   ├── security.py        # hash_password, JWT create/decode
│   ├── migrations.py      # Migrations manuelles idempotentes
│   └── ...
├── scripts/seed.py        # Seed idempotent (roles + admin)
├── middlewares/           # logging, security headers, CORS, exception handlers
└── main.py                # App FastAPI, /health, agregation des routers
```

Injection de dependances :
```
get_session() → Repository(session) → Service(repository) → route via Depends()
```

## Ajouter un module metier

1. Creer `src/modules/mon_module/` avec `models/`, `repositories/`, `services/`, `routes/`
2. Brancher le router dans `main.py` :

```python
from .modules.mon_module.routes import mon_module_router
app.include_router(mon_module_router, prefix=_prefix)
```

3. Si un changement de schema est necessaire, ajouter une migration idempotente dans `src/conf/migrations.py` (une instruction par `conn.execute()`)

## Acces aux services internes sur un serveur distant

Adminer, PostgreSQL (dev) et Redis (dev) sont bindes sur `127.0.0.1` uniquement — inaccessibles depuis l'exterieur par construction. Pour y acceder depuis ta machine :

```bash
# Adminer (interface web PostgreSQL)
ssh -L 8080:localhost:8080 user@serveur
# puis ouvrir http://localhost:8080

# PostgreSQL directement
ssh -L 5432:localhost:5432 user@serveur

# Redis
ssh -L 6379:localhost:6379 user@serveur
```

> C'est intentionnel : ces services ne doivent jamais etre exposes publiquement.

## Commandes

| Commande | Description |
|---|---|
| `make dev` | Stack developpement Docker (hot-reload + PostgreSQL + Mailpit + Redis + Adminer) |
| `make test` | 208 tests (venv auto ou Docker si Python < 3.13, SQLite in-memory) |
| `make coverage` | Tests avec rapport de couverture (seuil 80%) |
| `make prod` | Stack production Docker (API + PostgreSQL + Redis) |
| `make clean` | Arrete les conteneurs, supprime venv et caches |

## Configuration

Toutes les variables sont dans `.env`.

> Voir `.env.dev` et `.env.prod` pour la liste complete et les exemples.

## Fonctionnalites

### Auth & Securite
- Inscription + verification par email (token 10 min)
- Login JWT RS256 + logout avec revocation JTI (blocklist persistee)
- Reset de mot de passe par email (token 10 min)
- Protection anti brute-force progressive : 5 echecs → 5 min / 30 min / 2h / blocage definitif
- Rate limiting par IP : login 5/min, register 10/min, reset 5/min
- Politique mot de passe : min 12 car., 1 maj, 1 min, 1 chiffre, 1 special
- En-tetes de securite : HSTS, CSP, X-Frame-Options, X-Content-Type-Options

### Gestion des utilisateurs et roles
- CRUD utilisateurs avec pagination (`GET /api/v1/users/`)
- Gestion des roles (admin uniquement) avec pagination
- Controle d'acces : `require_role`, `require_role(allow_self=True)`
- Soft delete (desactivation de compte)

### Integration Moodle
- `GET /api/v1/moodle/learner/{id}` — profil apprenant agrege : cours, notes, completion, quiz, devoirs, badges, preferences, niveau estime global et par cours (admin)
- `GET /api/v1/moodle/learner/{id}/quiz/{attemptid}/review` — detail d'une tentative quiz (admin)
- Cache Redis du `LearnerProfile` (TTL configurable) avec delta sync via `core_course_get_updates_since` — invalide le cache uniquement si le contenu Moodle a change

### Integration LLM (Mistral)
- `POST /api/v1/llm/chat` — authentifie par JWT (utilisateur connecte), repond a une question avec contexte apprenant optionnel (30 req/min)
- `GET /api/v1/llm/learner/{id}` — analyse pedagogique generee par LLM (admin)
- Adaptation du prompt STUDENT au niveau estime de l'apprenant (debutant / intermediaire / avance) injecte dans le contexte
- Logging des metriques (tokens, duree, userid Moodle) en base
- Cache Redis des reponses LLM (TTL 1h) pour eviter les appels redondants
- Routage automatique vers `MISTRAL_MODEL_LIGHT` pour les questions courtes sans profil
- Keepalive LLM toutes les 4 minutes pour eviter le cold start Mistral (~2 160 tokens/jour, < $0.001)

### Qualite
- 234 tests (integration + unitaires), couverture > 80%
- Ruff (lint + format), mypy, bandit en pre-commit
- Pipeline CI GitLab (`.gitlab-ci.yml`)
