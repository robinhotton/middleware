# CLAUDE.conventions.md - Conventions de code

## SQLModel + SQLAlchemy async

- **Modeles et schemas** : `SQLModel` uniquement (jamais `BaseModel`) ; `Field`, `Relationship`, `select` depuis `sqlmodel`
- **Pattern requetes** : `(await session.execute(select(Model))).scalars().all()` — jamais `session.exec()`
- **`IntegrityError`** : import depuis `src/exceptions.py` uniquement — jamais depuis `sqlalchemy.exc`
- **Drivers** : `aiosqlite` (SQLite dev/test) + `asyncpg` (PostgreSQL prod)

## Schemas (pattern par entite)

| Schema | Usage | Champs |
|---|---|---|
| `Base(SQLModel)` | Champs communs | Champs partages |
| `Post(Base)` | Creation POST | + champs requis |
| `Patch(SQLModel)` | Mise a jour PATCH | Tous optionnels |
| `ReadMinimal(SQLModel)` | Imbrication | id + quelques champs |
| `Read(Base)` | Reponse API | + id + relations |
| `Model(Base, table=True)` | Table DB | + id PK |

`email` : `EmailStr` sur les schemas Pydantic, `str` sur le modele DB.
`password` : `PasswordStr` (min 12, 1 maj, 1 min, 1 chiffre, 1 special) sur les schemas de creation/reset.

## Repository (CRUD pur)

- `create(model)` : recoit un objet modele deja construit
- `update(model, data: dict)` : recoit un dict
- `delete(model)` : supprime l'objet
- Pas de logique metier, pas de `model_dump()`

## Service (logique metier)

- Conversion schema modele : `Model.model_validate(schema)` ou construction manuelle
- PATCH : `schema.model_dump(exclude_unset=True)`
- Leve `NotFoundException`, `ConflictException`, etc.
- Catch `IntegrityError` — re-raise en `ConflictException`
- Settings : `self.settings = get_settings()` dans `__init__`

## Routes (HTTP pur)

- Pas de try/except, pas de logique metier
- `response_model=SchemaRead` filtre les champs sensibles
- Tag OpenAPI : defini sur l'endpoint ou dans `include_router(tags=[...])`
- Endpoints "health" : `tags=["health"]` (pas le tag du domaine)

## Configuration (`settings.py`)

Toute valeur metier ou operationnelle ici — jamais de magic numbers dans les services.

- **DB** : `DB_DRIVER`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- **Auth** : `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `JWT_ALGORITHM` (RS256), `JWT_EXPIRATION_MINUTES`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_PSEUDO` (obligatoire, min 12 en prod/staging)
- **Brute-force** : `FAILED_LOGIN_THRESHOLD` (defaut 5), `LOCKOUT_DURATIONS_MINUTES` (defaut [5, 30, 120])
- **Tokens** : `EMAIL_VERIFICATION_EXPIRY_MINUTES`, `RESET_TOKEN_EXPIRY_MINUTES`, `TOKEN_BYTES`
- **Mail** : `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_STARTTLS`, `MAIL_SSL_TLS`, `MAIL_SUPPRESS_SEND`
- **LLM** : `MISTRAL_API_KEY`, `MISTRAL_MODEL`, `MISTRAL_BASE_URL`
- **Moodle** : `MOODLE_BASE_URL`, `MOODLE_ADMIN_TOKEN`, `MOODLE_SERVICE_NAME`, `MOODLE_WEBHOOK_SECRET`, `MOODLE_CACHE_TTL_SECONDS`
- **Logs** : `LOG_LEVEL`, `LOG_DIR`

## Mails transactionnels

`fastapi-mail` + `BackgroundTasks`. Tokens transmis dans le **corps JSON** (jamais dans l'URL d'appel API).

| Evenement | Methode EmailService |
|---|---|
| `POST /auth/register` | `send_verification_link(to, token)` |
| `POST /auth/reset-password` | `send_reset_link(to, token)` |

Dev : Mailpit intercepte tous les mails (SMTP :1025, UI :8025).

## Migrations DB (`src/conf/migrations.py`)

Idempotentes, appelees apres `create_all()` dans le lifespan.
Une instruction SQL par `await conn.execute()` — asyncpg interdit plusieurs commandes dans un seul appel.

## Regles pour les modifications futures

1. **Nouveau endpoint** : dependance d'auth appropriee + `responses={...}` pour Swagger
2. **Nouveau schema** : dans `src/modules/<domaine>/models/`, heriter `SQLModel`, ajouter `Field(description=...)`
3. **Nouvelle exception** : dans `src/exceptions.py`, heriter `AppException`
4. **Nouveau repository** : CRUD pur, recoit `Model` et `dict`, pas de schemas Pydantic
5. **Nouveau service** : logique metier, conversion schema modele, catch `IntegrityError` depuis `src/exceptions`
6. **Nouvelle colonne DB** : champ sur le modele + entree dans `src/conf/migrations.py`
7. **Date/heure UTC** : `utcnow()` depuis `src/conf/utils.py` — jamais `datetime.now(timezone.utc).replace(tzinfo=None)`
8. **Config** : dans `settings.py`, jamais en dur
9. **Import SQLAlchemy** : centraliser dans `src/exceptions.py` ou `src/conf/`
10. **Nouveau mail** : methode dans `EmailService` + `background_tasks.add_task()` dans la route + mock dans `NullEmailService.__init__`
