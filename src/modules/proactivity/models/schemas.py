"""Schemas et modele SQL pour le domaine proactivite."""

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON, Text
from sqlmodel import Field, SQLModel

from ....conf.utils import utcnow


class ProactivityEvent(SQLModel, table=True):
    """Evenement de proactivite enregistre pour eviter les doublons.

    Types : reminder | suggestion | suggestion_check
    """

    __tablename__ = "proactivity_event"
    __table_args__ = (
        Index(
            "ix_proactivity_event_user_type_created",
            "moodle_userid",
            "event_type",
            "created_at",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    moodle_userid: int = Field(index=True, description="Identifiant Moodle de l'utilisateur")
    event_type: str = Field(
        max_length=50,
        description="Type d'evenement : reminder | suggestion | suggestion_check",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="Donnees supplementaires (ex: module_id pour suggestion)",
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        description="Date de creation de l'evenement (UTC)",
    )


class ProactivitySettings(SQLModel):
    """Configuration proactivite retournee par proactivity_settings.php."""

    reminder_enabled: bool = Field(description="Rappel d'inactivite active")
    reminder_delay_hours: int = Field(
        description="Heures d'inactivite avant rappel"
    )
    reminder_cron: str = Field(description="Expression cron du job de rappel")
    suggestion_enabled: bool = Field(description="Suggestion post-module activee")
    suggestion_cron: str = Field(description="Expression cron du job de suggestion")
    notification_channel: str = Field(
        description="Canal de notification : moodle | email | both"
    )
    target_roles: list[str] = Field(
        default_factory=list,
        description="Roles Moodle eligibles aux notifications",
    )
    moodle_base_url: str = Field(description="URL de base du site Moodle")
    chat_url: str = Field(description="URL du chat DigilearnIA")
    recommendations_url: str = Field(description="URL des recommandations")


class ProactivitySettingsRecord(SQLModel, table=True):
    """Persistance de la configuration proactivite recuperee depuis Moodle.

    Permet de demarrer avec la derniere config connue si Moodle est injoignable.
    """

    __tablename__ = "proactivity_settings_record"

    id: int | None = Field(default=None, primary_key=True)
    reminder_enabled: bool = Field(description="Rappel d'inactivite active")
    reminder_delay_hours: int = Field(description="Heures d'inactivite avant rappel")
    reminder_cron: str = Field(max_length=100, description="Expression cron du job de rappel")
    suggestion_enabled: bool = Field(description="Suggestion post-module activee")
    suggestion_cron: str = Field(max_length=100, description="Expression cron du job de suggestion")
    notification_channel: str = Field(
        max_length=20, description="Canal de notification : moodle | email | both"
    )
    target_roles: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="Roles Moodle eligibles aux notifications",
    )
    moodle_base_url: str = Field(
        sa_column=Column(Text, nullable=False),
        description="URL de base du site Moodle",
    )
    chat_url: str = Field(
        sa_column=Column(Text, nullable=False),
        description="URL du chat DigilearnIA",
    )
    recommendations_url: str = Field(
        sa_column=Column(Text, nullable=False),
        description="URL des recommandations",
    )
    fetched_at: datetime = Field(
        default_factory=utcnow,
        description="Date de recuperation depuis Moodle (UTC)",
    )

    def to_settings(self) -> "ProactivitySettings":
        """Convertit l'enregistrement SQL en schema ProactivitySettings."""
        return ProactivitySettings(
            reminder_enabled=self.reminder_enabled,
            reminder_delay_hours=self.reminder_delay_hours,
            reminder_cron=self.reminder_cron,
            suggestion_enabled=self.suggestion_enabled,
            suggestion_cron=self.suggestion_cron,
            notification_channel=self.notification_channel,
            target_roles=self.target_roles,
            moodle_base_url=self.moodle_base_url,
            chat_url=self.chat_url,
            recommendations_url=self.recommendations_url,
        )

    @staticmethod
    def from_settings(settings: "ProactivitySettings") -> "ProactivitySettingsRecord":
        """Cree un enregistrement SQL depuis un schema ProactivitySettings."""
        return ProactivitySettingsRecord(
            reminder_enabled=settings.reminder_enabled,
            reminder_delay_hours=settings.reminder_delay_hours,
            reminder_cron=settings.reminder_cron,
            suggestion_enabled=settings.suggestion_enabled,
            suggestion_cron=settings.suggestion_cron,
            notification_channel=settings.notification_channel,
            target_roles=settings.target_roles,
            moodle_base_url=settings.moodle_base_url,
            chat_url=settings.chat_url,
            recommendations_url=settings.recommendations_url,
        )


class ProactivityEventRead(SQLModel):
    """Schema de lecture d'un ProactivityEvent."""

    id: int
    moodle_userid: int
    event_type: str
    payload: dict[str, Any] | None
    created_at: datetime


class ProactivityJobInfo(SQLModel):
    """Informations sur un job APScheduler."""

    id: str = Field(description="Identifiant du job")
    next_run: datetime | None = Field(description="Prochaine execution (UTC)")
    trigger: str = Field(description="Description du trigger")
    running: bool = Field(description="Job actif (True) ou en pause (False)")


class ProactivityStatusResponse(SQLModel):
    """Reponse de l'endpoint GET /proactivity/status."""

    scheduler_running: bool = Field(description="Scheduler APScheduler actif")
    jobs: list[ProactivityJobInfo] = Field(description="Etat des jobs enregistres")
