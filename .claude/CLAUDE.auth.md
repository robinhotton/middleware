# CLAUDE.auth.md — Authentification & Autorisation

## JWT

- POST /auth/login → {"access_token": "...", "token_type": "bearer"}
- Payload {"sub": "<user_id>", "exp": ..., "jti": "<uuid>"} signe **RS256** (asymetrique, cles dans JWT_PRIVATE_KEY / JWT_PUBLIC_KEY)
- Duree : JWT_EXPIRATION_MINUTES (defaut 480 min). Pas de refresh token.
- Revocation immediate via is_active=False (verifie a chaque requete dans get_current_user)
- Revocation explicite (logout) via **JTI blocklist** : RevokedToken en base, nettoye au demarrage (cleanup_expired())

## Politique de mot de passe (PasswordStr)

`min_length=12`, max 72 (limite bcrypt), 1 maj + 1 min + 1 chiffre + 1 special (via `_validate_password_strength`).
Appliquee sur les schemas `UserPost` et `ConfirmResetRequest`.
`ADMIN_PASSWORD` : meme regles verifiees en production/staging par `validate_admin_password`.

## Anti brute-force (dans AuthService.login())

Champs sur User : failed_login_attempts, locked_until, lockout_count

| lockout_count | Duree |
|---|---|
| 1 | 5 min |
| 2 | 30 min |
| 3 | 2h |
| > 3 | Blocage definitif |

Deblocage definitif : reset password OU admin PATCH /users/{id} avec {"locked_until": null, "lockout_count": 0}.
locked_until et lockout_count filtres dans UserPatch pour les non-admins.
Tous les compteurs se reinitialisent a la connexion reussie.

## Dependances d'autorisation (src/modules/auth/dependencies.py)

| Dependance | Usage |
|---|---|
| get_current_user | Decode JWT, verifie JTI non revoque + existence + is_active |
| require_role("admin") | Verifie le role (multi-roles supporte) |
| require_role(allow_self=True) | user_id == current user OU role admin |

## Authentification POST /llm/chat

`POST /llm/chat` protege par `get_current_user` : JWT RS256 standard (header `Authorization: Bearer <token>`).
Rate limit : 30 req/min.

## Soft delete

DELETE /users/{id} → is_active=False. Login et tokens existants refuses immediatement.

## Rate limiting (slowapi, par IP, in-memory, 1 worker)

| Endpoint | Limite |
|---|---|
| POST /auth/register | 10 req/min |
| POST /auth/login | 5 req/min |
| POST /auth/reset-password | 5 req/min |
| POST /auth/verify-email | 10 req/min |
| POST /auth/confirm-reset | 10 req/min |

En tests : limiter.enabled = False

## Matrice des permissions

| Endpoint | Anonyme | User (self) | Admin |
|---|---|---|---|
| GET /health | ✓ | ✓ | ✓ |
| POST /auth/* (register, login, verify, reset) | ✓ | ✓ | ✓ |
| POST /auth/logout | 401 | ✓ | ✓ |
| GET /users/ | 401 | 403 | ✓ |
| GET /users/{id} | 401 | ✓ (self) | ✓ |
| PATCH /users/{id} | 401 | ✓ (self, sans is_active/locked_until/lockout_count) | ✓ |
| DELETE /users/{id} | 401 | ✓ (self) | ✓ |
| POST\|DELETE /users/{id}/roles/{role_id} | 401 | 403 | ✓ |
| Tous les /roles/ | 401 | 403 | ✓ |
| POST /llm/chat | 401 | ✓ | ✓ |
| GET /llm/learner/{id} | 401 | 403 | ✓ |
| GET /moodle/learner/{id}/quiz/{attemptid}/review | 401 | 403 | ✓ |
| GET /moodle/learner/{id} | 401 | 403 | ✓ |
