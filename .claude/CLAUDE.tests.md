# CLAUDE.tests.md — Tests

234 tests, SQLite in-memory isolee par test, `asyncio_mode = "auto"`.

## Quand lancer les tests

Ne PAS relancer `make test` / `pytest` apres chaque modification. Les tests prennent ~90s.

- Lancer uniquement quand le code est consideré terminé pour une tâche
- Cibler les tests pertinents en premier : `pytest tests/modules/llm/ -q`
- Suite complete (`pytest tests/ -q`) uniquement pour valider avant commit

## Structure des tests

```
tests/
├── conftest.py              # Fixtures et helpers partages
├── test_health.py           # GET /health
├── modules/
│   ├── auth/                # test_auth.py, test_role.py, test_user.py, test_user_roles.py
│   ├── llm/                 # test_llm.py (routes), test_llm_service.py (unitaires)
│   └── moodle/              # test_moodle.py (routes), test_moodle_service.py (unitaires)
└── unit/                    # test_brute_force.py, test_validators.py, test_utils.py
```

## Fixtures (`tests/conftest.py`)

| Fixture | Description |
|---|---|
| `null_email_service` | `NullEmailService` (AsyncMock par methode) |
| `client` | `TestClient` SQLite in-memory + overrides |
| `admin_headers` | Cree admin + role via `AsyncSession`, retourne headers JWT |
| `user_and_headers` | Cree user via API (register+verify+login), retourne `(user_data, headers)` |

Asserter sur les mails : `null_email_service.send_verification_link.assert_awaited_once()`.

Acces direct a la base dans les tests : `AsyncSession(engine_test)`.

## Pattern de test integration

```python
async def test_exemple(client: TestClient, admin_headers: dict):
    user = create_user(client, email="test@example.com")
    response = client.get(f"{API_PREFIX}/users/{user['id']}", headers=admin_headers)
    assert response.status_code == 200
```

- `admin_headers` pour les endpoints proteges par role admin
- `user_and_headers` pour tester les permissions self
- `null_email_service` pour asserter sur les envois de mails
- Toujours tester : 401 sans token, 403 sans role, 200 avec le bon role/self

## Pattern mock service LLM / Moodle

Surcharger les dependances FastAPI pour les routes LLM et Moodle :

```python
@pytest.fixture(name="llm_client")
def llm_client_fixture(client: TestClient):
    from src.modules.auth import get_current_user
    from src.modules.auth.models.user import User
    mock_user = User(id=1, email="llm@test.com", pseudo="LLMUser", is_active=True, is_email_verified=True)
    mock_moodle = MagicMock()
    mock_moodle.get_learner_profile = AsyncMock(return_value=...)
    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=...)
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_moodle_service] = lambda: mock_moodle
    app.dependency_overrides[get_llm_service] = lambda: mock_llm
    yield client, mock_moodle, mock_llm
    # dependency_overrides vide par la fixture parente `client`
```

## Nouveau mail a mock a ajouter

Ajouter la methode mock dans `NullEmailService.__init__` (meme pattern que les existants).

## Helpers partages (`tests/conftest.py`)

| Fonction | Description |
|---|---|
| `create_user(client, email, password, ...)` | POST /auth/register, retourne `user_data` |
| `create_role(client, admin_headers, name, ...)` | POST /roles/, retourne `role_data` |
| `verify_email_for_user(client, user_id)` | Recupere token en base et appelle /auth/verify-email |

## Politique mot de passe (PasswordStr)

`min_length=12`, 1 maj, 1 min, 1 chiffre, 1 special. Tous les mots de passe de test respectent ces criteres (ex: `"Testpassword1!"`).
