"""Modeles de session conversationnelle persistante.

Une `ChatSession` regroupe un fil d'echanges pour un `moodle_userid` donne.
Les `ChatTurn` portent les paires user/assistant successives. Au-dela de
`_COMPACT_AFTER_TURNS` tours non compactes, les plus anciens sont fusionnes
en un resume textuel stocke dans `ChatSession.summary` (compact LLM).
"""

from datetime import datetime

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from ....conf.utils import utcnow


class ChatSession(SQLModel, table=True):
    """Fil de conversation persistant pour un utilisateur Moodle."""

    __tablename__ = "chat_session"

    id: int | None = SQLField(default=None, primary_key=True)
    moodle_userid: int = SQLField(index=True)
    profile_summary: str = SQLField(default="")
    summary: str = SQLField(default="")
    created_at: datetime = SQLField(default_factory=utcnow)
    last_active_at: datetime = SQLField(default_factory=utcnow, index=True)


class ChatTurn(SQLModel, table=True):
    """Tour user/assistant rattache a une session."""

    __tablename__ = "chat_turn"

    id: int | None = SQLField(default=None, primary_key=True)
    session_id: int = SQLField(foreign_key="chat_session.id", index=True)
    turn_num: int
    user_message: str
    assistant_response: str
    is_compacted: bool = SQLField(default=False)
    created_at: datetime = SQLField(default_factory=utcnow)
