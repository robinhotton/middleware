"""Schemas Pydantic pour l'analyse LLM d'un profil apprenant."""

from datetime import datetime

from pydantic import BaseModel, Field


class MoodleChatRequest(BaseModel):
    """Requete envoyee par Moodle pour obtenir une reponse LLM."""

    message: str = Field(
        max_length=40000,
        description="Message ou question envoyee par Moodle (sert de prompt)",
        examples=["Explique les closures en Python en termes simples."],
    )
    moodle_userid: int | None = Field(
        default=None,
        description="Identifiant Moodle de l'apprenant — enrichit le contexte",
    )
    context: str | None = Field(
        default=None,
        max_length=40000,
        description="Contexte additionnel libre (nom du cours, activite, etc.)",
        examples=["Cours Python avance, module 3 — Programmation fonctionnelle"],
    )
    moodle_user_role: str | None = Field(
        default=None,
        description=(
            "Role Moodle de l'utilisateur courant "
            "(ex: student, editingteacher, teacher, manager). "
            "Permet de selectionner le prompt systeme adapte."
        ),
        examples=["editingteacher", "student"],
    )
    prompt_id: str | None = Field(
        default=None,
        description=(
            "Identifiant d'un prompt predefini du catalogue "
            "(ex: trainer_generate_qcm). "
            "Doit correspondre au role de l'utilisateur."
        ),
        examples=["trainer_generate_qcm", "trainer_generate_tp"],
    )
    session_id: int | None = Field(
        default=None,
        description=(
            "Identifiant d'une session conversationnelle existante. "
            "Si omis, une nouvelle session est ouverte et son id renvoye dans la "
            "reponse — le client doit le reutiliser aux tours suivants pour "
            "beneficier du fil conversationnel et des compacts automatiques."
        ),
        examples=[42],
    )


class MoodleChatResponse(BaseModel):
    """Reponse retournee a Moodle apres generation LLM."""

    response: str = Field(description="Reponse generee par le LLM")
    session_id: int | None = Field(
        default=None,
        description=(
            "Identifiant de la session conversationnelle utilisee ou creee. "
            "A renvoyer aux tours suivants pour conserver le fil."
        ),
        examples=[42],
    )


class LearnerAnalysis(BaseModel):
    """Bilan pedagogique genere par le LLM a partir du profil Moodle."""

    moodle_userid: int = Field(description="Identifiant Moodle de l'apprenant analyse")
    fullname: str = Field(description="Nom complet de l'apprenant")
    model_used: str = Field(
        description="Modele LLM utilise pour la generation",
        examples=["open-mistral-nemo"],
    )
    analysis: str = Field(
        description=(
            "Bilan pedagogique structure : situation globale, points forts, "
            "points d'attention, recommandations"
        )
    )


class LLMLogRead(BaseModel):
    """Schema de lecture d'un log LLM."""

    id: int = Field(description="Identifiant du log")
    moodle_userid: int | None = Field(description="Identifiant Moodle de l'apprenant")
    model_used: str = Field(description="Modele LLM utilise")
    prompt_tokens: int = Field(description="Tokens en entree")
    completion_tokens: int = Field(description="Tokens en sortie")
    duration_ms: int = Field(description="Duree de l'appel en ms")
    created_at: datetime = Field(description="Date de l'appel")


class PromptTemplateRead(BaseModel):
    """Prompt predefini — schema de lecture expose via l'API (sans system_prompt interne)."""

    id: str = Field(description="Identifiant unique du prompt")
    role: str = Field(
        description="Role cible : student ou trainer",
        examples=["trainer"],
    )
    name: str = Field(description="Nom affichable dans l'interface Moodle")
    description: str = Field(description="Description courte de l'usage")
    user_message_template: str | None = Field(
        default=None,
        description="Modele de message utilisateur avec placeholders {variable}",
    )


class PlatformSettingsResponse(BaseModel):
    """Parametres de la plateforme exposes a Moodle via l'API."""

    ai_name: str = Field(
        description="Nom de l'IA affiche dans les interfaces Moodle",
        examples=["DigilearnIA"],
    )


class LLMStatsResponse(BaseModel):
    """Statistiques agregees des appels LLM."""

    total_calls: int = Field(description="Nombre total d'appels")
    total_prompt_tokens: int = Field(description="Total tokens en entree")
    total_completion_tokens: int = Field(description="Total tokens en sortie")
    total_tokens: int = Field(description="Total tokens (entree + sortie)")
    avg_prompt_tokens: float = Field(description="Moyenne tokens entree par appel")
    avg_completion_tokens: float = Field(description="Moyenne tokens sortie par appel")
    avg_duration_ms: float = Field(description="Duree moyenne par appel en ms")
