"""Modele de log des requetes LLM (metriques uniquement, pas le contenu)."""

from datetime import datetime

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from ....conf.utils import utcnow


class LLMLog(SQLModel, table=True):
    """Enregistrement d'un appel LLM — metriques uniquement, pas le contenu."""

    __tablename__ = "llm_log"
    id: int | None = SQLField(default=None, primary_key=True)
    moodle_userid: int | None = SQLField(default=None, index=True)
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int
    created_at: datetime = SQLField(default_factory=utcnow)
