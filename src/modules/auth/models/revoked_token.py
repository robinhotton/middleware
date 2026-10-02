"""Modele de blocklist JWT (JTI revoques)."""

from datetime import datetime

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class RevokedToken(SQLModel, table=True):
    """Table de blocklist JWT : stocke les JTI revoques jusqu'a leur expiration."""

    __tablename__ = "revoked_token"
    jti: str = SQLField(primary_key=True)
    expires_at: datetime
