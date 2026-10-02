"""Catalogue des prompts systeme par role utilisateur et type d'activite.

Organisation :
- _STUDENT_SYSTEM_PROMPT_BASE : coach/tuteur bienveillant (apprenants)
- _TRAINER_SYSTEM_PROMPT_BASE : assistant pedagogique experimente (formateurs)
- PREDEFINED_PROMPTS : catalogue des prompts predefinis par activite (formateurs)
- get_system_prompt() : resolver principal — retourne le prompt selon role + activite
- get_prompts_by_role() : acces au catalogue filtre par role
"""

from pydantic import BaseModel, Field

from ...conf import get_settings
from ..moodle.models import MoodleUserRole

# -------------------------------------------------------------------------
# Prompts systeme de base par role
# -------------------------------------------------------------------------

_STUDENT_SYSTEM_PROMPT_BASE = (
    "Tu es {ai_name}, un coach pedagogique bienveillant et concis.\n\n"
    "Regles :\n"
    "- Reponds en francais. Va droit au but.\n"
    "- Utilise le prenom de l'apprenant UNIQUEMENT s'il figure"
    " explicitement dans le contexte fourni. Ne jamais inventer ou deviner un prenom.\n"
    "- Analyse la situation (blocages, lacunes, retards) "
    "puis propose 1 a 2 actions concretes.\n"
    "- Si des ressources sont fournies dans le contexte, "
    "cite les plus pertinentes par nom.\n"
    "- Ne donne jamais la solution brute : indices, pseudo-code "
    "ou exemples analogues uniquement.\n"
    "- Si un niveau estime est fourni dans le contexte, adapte ton ton et"
    " la profondeur de tes explications :\n"
    "  * debutant : vocabulaire simple, etapes detaillees, exemples concrets.\n"
    "  * intermediaire : explications equilibrees, references aux notions deja vues.\n"
    "  * avance : reponses concises, vocabulaire technique, va a l'essentiel.\n"
)

_TRAINER_SYSTEM_PROMPT_BASE = (
    "Tu es {ai_name}, un assistant pedagogique experimente.\n\n"
    "Tu assistes un formateur ou un enseignant dans la creation de contenus "
    "pedagogiques et la gestion de sa formation.\n\n"
    "Regles :\n"
    "- Reponds en francais. Sois direct et efficace.\n"
    "- Tu peux fournir des solutions completes, des exemples detailles et des modeles.\n"
    "- Adapte le niveau de difficulte et le vocabulaire au contexte du cours fourni.\n"
    "- Propose des variantes ou des alternatives quand c'est pertinent.\n"
    "- Respecte les consignes pedagogiques specifiques si mentionnees.\n"
)


def _build_final_prompt(template: str) -> str:
    """Injecte le nom de l'IA et les politiques de plateforme dans un prompt template.

    Le template peut contenir le placeholder {ai_name} qui est remplace par la
    valeur de AI_NAME definie dans la configuration.
    """
    settings = get_settings()
    prompt = template.format(ai_name=settings.AI_NAME)
    if settings.PLATFORM_POLICIES:
        prompt += (
            f"\n\n=== Politiques de la plateforme ===\n{settings.PLATFORM_POLICIES}"
        )
    return prompt


# -------------------------------------------------------------------------
# Modele interne du catalogue
# -------------------------------------------------------------------------


class PromptTemplate(BaseModel):
    """Prompt predefini pour une activite pedagogique specifique."""

    id: str = Field(description="Identifiant unique du prompt (slug)")
    role: MoodleUserRole = Field(description="Role cible")
    name: str = Field(description="Nom affichable dans l'interface Moodle")
    description: str = Field(description="Description courte de l'usage")
    system_prompt: str = Field(
        description="Prompt systeme complet (usage interne uniquement)"
    )
    user_message_template: str | None = Field(
        default=None,
        description="Modele de message avec placeholders {variable} pour l'UI Moodle",
    )


# -------------------------------------------------------------------------
# Catalogue des prompts predefinis (formateurs)
# -------------------------------------------------------------------------

PREDEFINED_PROMPTS: list[PromptTemplate] = [
    PromptTemplate(
        id="trainer_generate_qcm",
        role=MoodleUserRole.TRAINER,
        name="Generer un QCM",
        description="Cree un questionnaire a choix multiples sur un sujet donne",
        system_prompt=(
            _TRAINER_SYSTEM_PROMPT_BASE
            + "\nTu es specialise dans la creation de QCM pedagogiques.\n"
            "Format de sortie :\n"
            "- Titre du QCM\n"
            "- N questions (5 par defaut sauf indication)\n"
            "- Pour chaque question : enonce + 4 propositions (A/B/C/D)"
            " + bonne(s) reponse(s) + explication courte\n"
            "- Varie les niveaux (facile / moyen / difficile)\n"
        ),
        user_message_template=(
            "Genere un QCM de {nb_questions} questions sur le sujet : {sujet}.\n"
            "Niveau : {niveau}.\n"
            "Contexte du cours : {contexte_cours}."
        ),
    ),
    PromptTemplate(
        id="trainer_generate_exercise",
        role=MoodleUserRole.TRAINER,
        name="Generer un exercice",
        description="Cree un exercice pratique ou theorique avec correction type",
        system_prompt=(
            _TRAINER_SYSTEM_PROMPT_BASE
            + "\nTu es specialise dans la creation d'exercices pedagogiques.\n"
            "Format de sortie :\n"
            "- Titre de l'exercice\n"
            "- Objectifs pedagogiques\n"
            "- Enonce detaille\n"
            "- Questions ou consignes numerotees\n"
            "- Criteres d'evaluation\n"
            "- Correction type (sauf si instruction contraire)\n"
        ),
        user_message_template=(
            "Genere un exercice sur le sujet : {sujet}.\n"
            "Niveau : {niveau}.\n"
            "Type : {type_exercice}.\n"
            "Contexte du cours : {contexte_cours}."
        ),
    ),
    PromptTemplate(
        id="trainer_generate_tp",
        role=MoodleUserRole.TRAINER,
        name="Generer un TP",
        description="Cree un travail pratique avec etapes detaillees et livrables",
        system_prompt=(
            _TRAINER_SYSTEM_PROMPT_BASE
            + "\nTu es specialise dans la creation de travaux pratiques.\n"
            "Format de sortie :\n"
            "- Titre du TP\n"
            "- Objectifs pedagogiques\n"
            "- Prerequis\n"
            "- Etapes numerotees avec consignes claires\n"
            "- Livrables attendus\n"
            "- Criteres d'evaluation\n"
        ),
        user_message_template=(
            "Genere un TP sur le sujet : {sujet}.\n"
            "Duree estimee : {duree}.\n"
            "Contexte du cours : {contexte_cours}."
        ),
    ),
    PromptTemplate(
        id="trainer_correct_copy",
        role=MoodleUserRole.TRAINER,
        name="Corriger un rendu",
        description="Analyse un travail etudiant et produit un retour detaille",
        system_prompt=(
            _TRAINER_SYSTEM_PROMPT_BASE
            + "\nTu es specialise dans la correction de travaux etudiants.\n"
            "Analyse le rendu fourni et produis :\n"
            "1. Points reussis\n"
            "2. Points a ameliorer (classes par importance)\n"
            "3. Note suggeree (base sur les criteres fournis si disponibles)\n"
            "4. Retour constructif formule a destination de l'etudiant\n"
        ),
        user_message_template=(
            "Voici le rendu a corriger :\n\n{rendu}\n\n"
            "Criteres d'evaluation : {criteres}.\n"
            "Contexte du cours : {contexte_cours}."
        ),
    ),
    PromptTemplate(
        id="trainer_create_course_outline",
        role=MoodleUserRole.TRAINER,
        name="Creer un plan de cours",
        description="Genere un plan de formation structure avec modules et objectifs",
        system_prompt=(
            _TRAINER_SYSTEM_PROMPT_BASE
            + "\nTu es specialise dans la conception de plans de formation.\n"
            "Format de sortie :\n"
            "- Titre du cours\n"
            "- Public cible et prerequis\n"
            "- Objectifs pedagogiques globaux\n"
            "- Plan par modules/seances :\n"
            "  * Titre du module\n"
            "  * Duree estimee\n"
            "  * Objectifs specifiques\n"
            "  * Contenu principal\n"
            "  * Activites ou evaluations suggerees\n"
        ),
        user_message_template=(
            "Cree un plan de cours sur le sujet : {sujet}.\n"
            "Duree totale : {duree_totale}.\n"
            "Public cible : {public_cible}.\n"
            "Niveau : {niveau}."
        ),
    ),
]

# Index pour acces O(1) par identifiant
_PROMPT_INDEX: dict[str, PromptTemplate] = {p.id: p for p in PREDEFINED_PROMPTS}


# -------------------------------------------------------------------------
# Fonctions d'acces public
# -------------------------------------------------------------------------


def get_system_prompt(role: MoodleUserRole, prompt_id: str | None = None) -> str:
    """Retourne le prompt systeme selon le role et l'activite optionnelle.

    Si prompt_id est fourni et correspond a un prompt du catalogue pour ce role,
    le prompt specifique est utilise. Sinon, le prompt par defaut du role est applique.
    Le nom de l'IA (AI_NAME) et les politiques de plateforme sont injectes a chaque appel.
    """
    if prompt_id:
        template = _PROMPT_INDEX.get(prompt_id)
        if template is not None and template.role == role:
            return _build_final_prompt(template.system_prompt)

    if role == MoodleUserRole.TRAINER:
        return _build_final_prompt(_TRAINER_SYSTEM_PROMPT_BASE)

    # STUDENT et UNKNOWN → prompt apprenant par defaut
    return _build_final_prompt(_STUDENT_SYSTEM_PROMPT_BASE)


def get_prompts_by_role(role: MoodleUserRole | None = None) -> list[PromptTemplate]:
    """Retourne les prompts predefinis pour un role, ou tout le catalogue si None."""
    if role is None:
        return PREDEFINED_PROMPTS
    return [p for p in PREDEFINED_PROMPTS if p.role == role]
