"""Migrations manuelles pour les colonnes ajoutees apres la creation initiale.

Executees uniquement en production (BDD persistante).
En developpement, create_all() recrée le schema depuis les modeles SQLModel.

Patron a reproduire pour chaque changement de schema :

    if dialect == "postgresql":
        await conn.execute(text(
            'ALTER TABLE "user" '
            'ADD COLUMN IF NOT EXISTS nouvelle_colonne INTEGER NOT NULL DEFAULT 0'
        ))
    else:
        result = await conn.execute(text("PRAGMA table_info(user)"))
        if "nouvelle_colonne" not in {row[1] for row in result}:
            await conn.execute(text(
                "ALTER TABLE user "
                "ADD COLUMN nouvelle_colonne INTEGER NOT NULL DEFAULT 0"
            ))
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def run_migrations(conn: AsyncConnection) -> None:
    """Applique les migrations incrementales sur la BDD de production.

    Idempotent : peut etre appele plusieurs fois sans effet.
    """
    dialect = conn.engine.dialect.name

    # --- proactivity_event (M1-008 / M1-009) ---
    if dialect == "postgresql":
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS proactivity_event (
                id          SERIAL PRIMARY KEY,
                moodle_userid INTEGER NOT NULL,
                event_type  VARCHAR(50) NOT NULL,
                payload     JSON,
                created_at  TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        ))
        await conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_proactivity_event_user_type_created
            ON proactivity_event (moodle_userid, event_type, created_at)
            """
        ))
        await conn.execute(text(
            """
            CREATE INDEX IF NOT EXISTS ix_proactivity_event_moodle_userid
            ON proactivity_event (moodle_userid)
            """
        ))
    else:
        # SQLite : verifier l'existence de la table avant de creer
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proactivity_event'"
        ))
        if result.fetchone() is None:
            await conn.execute(text(
                """
                CREATE TABLE proactivity_event (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    moodle_userid INTEGER NOT NULL,
                    event_type  VARCHAR(50) NOT NULL,
                    payload     JSON,
                    created_at  DATETIME NOT NULL
                )
                """
            ))
            await conn.execute(text(
                """
                CREATE INDEX ix_proactivity_event_user_type_created
                ON proactivity_event (moodle_userid, event_type, created_at)
                """
            ))
            await conn.execute(text(
                """
                CREATE INDEX ix_proactivity_event_moodle_userid
                ON proactivity_event (moodle_userid)
                """
            ))

    # --- proactivity_settings_record ---
    if dialect == "postgresql":
        await conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS proactivity_settings_record (
                id                  SERIAL PRIMARY KEY,
                reminder_enabled    BOOLEAN NOT NULL,
                reminder_delay_hours INTEGER NOT NULL,
                reminder_cron       VARCHAR(100) NOT NULL,
                suggestion_enabled  BOOLEAN NOT NULL,
                suggestion_cron     VARCHAR(100) NOT NULL,
                notification_channel VARCHAR(20) NOT NULL,
                target_roles        JSON NOT NULL DEFAULT '[]',
                moodle_base_url     TEXT NOT NULL,
                chat_url            TEXT NOT NULL,
                recommendations_url TEXT NOT NULL,
                fetched_at          TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        ))
    else:
        # SQLite
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='proactivity_settings_record'"
        ))
        if result.fetchone() is None:
            await conn.execute(text(
                """
                CREATE TABLE proactivity_settings_record (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    reminder_enabled    BOOLEAN NOT NULL,
                    reminder_delay_hours INTEGER NOT NULL,
                    reminder_cron       VARCHAR(100) NOT NULL,
                    suggestion_enabled  BOOLEAN NOT NULL,
                    suggestion_cron     VARCHAR(100) NOT NULL,
                    notification_channel VARCHAR(20) NOT NULL,
                    target_roles        JSON NOT NULL DEFAULT '[]',
                    moodle_base_url     TEXT NOT NULL,
                    chat_url            TEXT NOT NULL,
                    recommendations_url TEXT NOT NULL,
                    fetched_at          DATETIME NOT NULL
                )
                """
            ))

    # --- chat_session + chat_turn (sessions conversationnelles LLM) ---
    # Migration deja appliquee en production — commentee pour eviter tout effet
    # de bord lors des prochains deploiements. A reactiver si re-creation
    # necessaire sur une nouvelle BDD.
    # if dialect == "postgresql":
    #     await conn.execute(text(
    #         """
    #         CREATE TABLE IF NOT EXISTS chat_session (
    #             id              SERIAL PRIMARY KEY,
    #             moodle_userid   INTEGER NOT NULL,
    #             profile_summary TEXT NOT NULL DEFAULT '',
    #             summary         TEXT NOT NULL DEFAULT '',
    #             created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    #             last_active_at  TIMESTAMP NOT NULL DEFAULT NOW()
    #         )
    #         """
    #     ))
    #     await conn.execute(text(
    #         """
    #         CREATE INDEX IF NOT EXISTS ix_chat_session_moodle_userid
    #         ON chat_session (moodle_userid)
    #         """
    #     ))
    #     await conn.execute(text(
    #         """
    #         CREATE INDEX IF NOT EXISTS ix_chat_session_last_active_at
    #         ON chat_session (last_active_at)
    #         """
    #     ))
    #     await conn.execute(text(
    #         """
    #         CREATE TABLE IF NOT EXISTS chat_turn (
    #             id                 SERIAL PRIMARY KEY,
    #             session_id         INTEGER NOT NULL REFERENCES chat_session(id),
    #             turn_num           INTEGER NOT NULL,
    #             user_message       TEXT NOT NULL,
    #             assistant_response TEXT NOT NULL,
    #             is_compacted       BOOLEAN NOT NULL DEFAULT FALSE,
    #             created_at         TIMESTAMP NOT NULL DEFAULT NOW()
    #         )
    #         """
    #     ))
    #     await conn.execute(text(
    #         """
    #         CREATE INDEX IF NOT EXISTS ix_chat_turn_session_id
    #         ON chat_turn (session_id)
    #         """
    #     ))
    # else:
    #     # SQLite
    #     result = await conn.execute(text(
    #         "SELECT name FROM sqlite_master "
    #         "WHERE type='table' AND name='chat_session'"
    #     ))
    #     if result.fetchone() is None:
    #         await conn.execute(text(
    #             """
    #             CREATE TABLE chat_session (
    #                 id              INTEGER PRIMARY KEY AUTOINCREMENT,
    #                 moodle_userid   INTEGER NOT NULL,
    #                 profile_summary TEXT NOT NULL DEFAULT '',
    #                 summary         TEXT NOT NULL DEFAULT '',
    #                 created_at      DATETIME NOT NULL,
    #                 last_active_at  DATETIME NOT NULL
    #             )
    #             """
    #         ))
    #         await conn.execute(text(
    #             """
    #             CREATE INDEX ix_chat_session_moodle_userid
    #             ON chat_session (moodle_userid)
    #             """
    #         ))
    #         await conn.execute(text(
    #             """
    #             CREATE INDEX ix_chat_session_last_active_at
    #             ON chat_session (last_active_at)
    #             """
    #         ))
    #     result = await conn.execute(text(
    #         "SELECT name FROM sqlite_master "
    #         "WHERE type='table' AND name='chat_turn'"
    #     ))
    #     if result.fetchone() is None:
    #         await conn.execute(text(
    #             """
    #             CREATE TABLE chat_turn (
    #                 id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    #                 session_id         INTEGER NOT NULL REFERENCES chat_session(id),
    #                 turn_num           INTEGER NOT NULL,
    #                 user_message       TEXT NOT NULL,
    #                 assistant_response TEXT NOT NULL,
    #                 is_compacted       BOOLEAN NOT NULL DEFAULT 0,
    #                 created_at         DATETIME NOT NULL
    #             )
    #             """
    #         ))
    #         await conn.execute(text(
    #             """
    #             CREATE INDEX ix_chat_turn_session_id
    #             ON chat_turn (session_id)
    #             """
    #         ))
