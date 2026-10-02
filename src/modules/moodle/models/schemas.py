"""Schemas Pydantic pour le profil apprenant Moodle (aucune table SQL)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class MoodleUserRole(StrEnum):
    """Role pedagogique deduit depuis le profil Moodle de l'utilisateur."""

    STUDENT = "student"   # Apprenant
    TRAINER = "trainer"   # Formateur / Enseignant
    UNKNOWN = "unknown"   # Role non determine


class LearnerLevel(StrEnum):
    """Niveau de maitrise de l'apprenant calcule a partir du profil Moodle.

    Derive d'une moyenne ponderee : 50% ratio des notes, 30% progression cours,
    20% taux de completion des activites. Recalcule a chaque construction du profil.
    """

    UNKNOWN = "unknown"            # Donnees insuffisantes pour estimer le niveau
    BEGINNER = "beginner"          # Score < 0.40
    INTERMEDIATE = "intermediate"  # 0.40 <= score < 0.70
    ADVANCED = "advanced"          # Score >= 0.70


class MoodleCourse(BaseModel):
    """Cours dans lequel l'apprenant est inscrit."""

    id: int = Field(description="Identifiant interne Moodle du cours")
    fullname: str = Field(description="Nom complet du cours")
    shortname: str = Field(description="Nom court du cours")
    progress: float | None = Field(
        default=None,
        description="Progression de l'apprenant dans le cours (0-100 %)",
    )
    lastaccess: int | None = Field(
        default=None,
        description="Timestamp epoch du dernier acces de l'apprenant",
    )


class MoodleCourseGrade(BaseModel):
    """Note finale de l'apprenant pour un cours."""

    courseid: int = Field(description="Identifiant du cours")
    grade: str = Field(
        description="Note formatee (ex: '13.50 / 20')",
        examples=["13.50 / 20"],
    )
    rawgrade: float | None = Field(
        default=None, description="Valeur numerique brute de la note"
    )


class MoodleGradeItem(BaseModel):
    """Note pour une activite individuelle (devoir, quiz, etc.)."""

    itemname: str | None = Field(default=None, description="Nom de l'activite notee")
    itemmodule: str | None = Field(
        default=None,
        description="Type de module Moodle (assign, quiz, forum...)",
        examples=["assign", "quiz"],
    )
    graderaw: float | None = Field(default=None, description="Note brute obtenue")
    grademin: float | None = Field(default=None, description="Note minimale possible")
    grademax: float | None = Field(default=None, description="Note maximale possible")
    gradeformatted: str | None = Field(
        default=None,
        description="Note formatee pour l'affichage",
        examples=["14.00"],
    )
    feedback: str | None = Field(
        default=None, description="Commentaire de l'enseignant"
    )


class MoodleCompletion(BaseModel):
    """Etat de completion d'une activite par l'apprenant."""

    cmid: int = Field(description="Course Module ID (identifiant de l'activite)")
    modname: str = Field(
        description="Type de module Moodle",
        examples=["assign", "quiz", "page"],
    )
    state: int = Field(
        description=(
            "Etat de completion : 0=incomplete, 1=complete, "
            "2=complete avec condition, 3=complete avec echec"
        ),
        ge=0,
        le=3,
    )
    timecompleted: int | None = Field(
        default=None,
        description="Timestamp epoch de la completion (None si pas complete)",
    )


class MoodleQuizAttempt(BaseModel):
    """Tentative de quiz par l'apprenant."""

    quizid: int = Field(description="Identifiant du quiz")
    attempt_number: int = Field(
        description="Numero de la tentative (commence a 1)", ge=1
    )
    state: str = Field(
        description="Etat de la tentative",
        examples=["finished", "inprogress", "abandoned"],
    )
    sumgrades: float | None = Field(
        default=None, description="Score total obtenu pour la tentative"
    )
    timestart: int | None = Field(
        default=None,
        description="Timestamp epoch du debut de la tentative",
    )
    timefinish: int | None = Field(
        default=None,
        description="Timestamp epoch de la fin de la tentative (0 si pas terminee)",
    )


class MoodleAssignment(BaseModel):
    """Devoir avec statut de rendu et note."""

    assignid: int = Field(description="Identifiant du devoir")
    name: str = Field(description="Titre du devoir")
    duedate: int | None = Field(
        default=None,
        description="Timestamp epoch de la date limite (0 si pas de limite)",
    )
    status: str | None = Field(
        default=None,
        description="Statut du rendu de l'apprenant",
        examples=["submitted", "new", "draft"],
    )
    gradingstatus: str | None = Field(
        default=None,
        description="Statut de la correction",
        examples=["graded", "notgraded"],
    )
    grade: float | None = Field(
        default=None, description="Note obtenue (None si pas encore note)"
    )


class MoodleActivityEvent(BaseModel):
    """Evenement comportemental derive du journal d'activite de l'apprenant."""

    event_type: str = Field(
        description=(
            "Type d'evenement : quiz_abandoned | quiz_retried | assignment_late | "
            "assignment_due_soon | course_inactive | incomplete_activities"
        )
    )
    description: str = Field(description="Description lisible de l'evenement")
    course_id: int | None = Field(
        default=None, description="Cours concerne (None si transversal)"
    )
    severity: str = Field(
        description="Gravite : 'warning' | 'info' | 'positive'",
        examples=["warning", "info", "positive"],
    )


class MoodleResource(BaseModel):
    """Ressource ou activite d'un cours (page, fichier, devoir, quiz, url...)."""

    cmid: int = Field(description="Course Module ID")
    name: str = Field(description="Nom de la ressource")
    modname: str = Field(
        description="Type de module Moodle",
        examples=["page", "resource", "quiz", "assign", "url"],
    )
    section_name: str = Field(description="Nom de la section contenant la ressource")
    url: str | None = Field(
        default=None, description="URL d'acces direct a la ressource"
    )
    description: str | None = Field(
        default=None, description="Description/intro de la ressource (HTML nettoye)"
    )


class MoodleBadge(BaseModel):
    """Badge Moodle obtenu par l'apprenant."""

    id: int = Field(description="Identifiant du badge")
    name: str = Field(description="Nom du badge")
    description: str | None = Field(default=None, description="Description du badge")
    dateissued: int | None = Field(
        default=None, description="Timestamp epoch d'obtention"
    )
    badgeurl: str | None = Field(default=None, description="URL de l'image du badge")


class MoodleUserPreference(BaseModel):
    """Preference Moodle d'un utilisateur (langue, fuseau horaire...)."""

    name: str = Field(description="Cle de la preference", examples=["lang", "timezone"])
    value: str = Field(description="Valeur de la preference")


class MoodleCalendarEvent(BaseModel):
    """Evenement calendrier Moodle (deadline quiz, cours live, rappel...)."""

    id: int = Field(description="Identifiant de l'evenement")
    name: str = Field(description="Titre de l'evenement")
    description: str | None = Field(
        default=None, description="Description (HTML nettoye)"
    )
    courseid: int | None = Field(
        default=None, description="Identifiant du cours concerne"
    )
    timestart: int = Field(description="Timestamp epoch de debut de l'evenement")
    timeduration: int = Field(default=0, description="Duree en secondes (0 = ponctuel)")
    modulename: str | None = Field(
        default=None,
        description="Type de module Moodle concerne",
        examples=["quiz", "assign", "lesson"],
    )
    instance: int | None = Field(
        default=None, description="Identifiant de l'instance du module"
    )


class MoodleForumPost(BaseModel):
    """Post de forum redige par l'apprenant dans un cours."""

    id: int = Field(description="Identifiant du post")
    subject: str = Field(description="Sujet du post")
    message: str | None = Field(
        default=None, description="Corps du message (HTML nettoye)"
    )
    created: int = Field(description="Timestamp epoch de creation du post")
    courseid: int = Field(description="Identifiant du cours")
    discussion_id: int = Field(description="Identifiant de la discussion parente")


class MoodleQuizQuestion(BaseModel):
    """Question d'une tentative de quiz avec la reponse de l'apprenant."""

    slot: int = Field(
        description="Numero de la question dans la tentative (commence a 1)"
    )
    question_text: str | None = Field(
        default=None,
        description="Enonce de la question (HTML nettoye, tronque a 500 chars)",
    )
    student_answer: str | None = Field(
        default=None, description="Resume de la reponse fournie par l'apprenant"
    )
    correct: bool | None = Field(
        default=None,
        description="True=reponse juste, False=reponse fausse, None=indetermine",
    )
    mark: float | None = Field(
        default=None, description="Points obtenus pour cette question"
    )
    maxmark: float | None = Field(
        default=None, description="Points maximaux pour cette question"
    )
    feedback: str | None = Field(
        default=None, description="Feedback specifique a la reponse (si disponible)"
    )


class MoodleQuizReview(BaseModel):
    """Revue detaillee d'une tentative de quiz (question par question)."""

    attemptid: int = Field(description="Identifiant de la tentative")
    quizid: int = Field(description="Identifiant du quiz")
    questions: list[MoodleQuizQuestion] = Field(
        default_factory=list, description="Questions avec reponses et scores"
    )


class MoodleHealthResponse(BaseModel):
    """Reponse de l'endpoint de sante Moodle."""

    status: str = Field(description="Statut de la connexion Moodle", examples=["ok"])
    moodle_version: str = Field(
        description="Version Moodle", examples=["Moodle 4.3.2+"]
    )
    site_url: str = Field(description="URL du site Moodle")
    username: str = Field(description="Nom d'utilisateur du token web service")


class LearnerProfile(BaseModel):
    """Profil apprenant agrege — consommable directement par un LLM."""

    moodle_userid: int = Field(description="Identifiant Moodle de l'apprenant")
    username: str = Field(description="Nom d'utilisateur Moodle")
    fullname: str = Field(description="Nom complet de l'apprenant")
    email: str = Field(description="Adresse email de l'apprenant")
    courses: list[MoodleCourse] = Field(
        default_factory=list,
        description="Cours dans lesquels l'apprenant est inscrit",
    )
    overview_grades: list[MoodleCourseGrade] = Field(
        default_factory=list,
        description="Note finale par cours",
    )
    grades_by_course: dict[int, list[MoodleGradeItem]] = Field(
        default_factory=dict,
        description="Notes par activite indexees par courseid",
    )
    completion_by_course: dict[int, list[MoodleCompletion]] = Field(
        default_factory=dict,
        description="Etat de completion par activite indexe par courseid",
    )
    quiz_attempts: list[MoodleQuizAttempt] = Field(
        default_factory=list,
        description="Toutes les tentatives de quiz de l'apprenant",
    )
    assignments: list[MoodleAssignment] = Field(
        default_factory=list,
        description="Devoirs avec statut de rendu et note",
    )
    activity_log: list[MoodleActivityEvent] = Field(
        default_factory=list,
        description="Journal comportemental derive (abandons, retards, inactivite...)",
    )
    resources_by_course: dict[int, list[MoodleResource]] = Field(
        default_factory=dict,
        description="Ressources et activites disponibles par cours",
    )
    badges: list[MoodleBadge] = Field(
        default_factory=list,
        description="Badges obtenus par l'apprenant",
    )
    preferences: list[MoodleUserPreference] = Field(
        default_factory=list,
        description="Preferences Moodle de l'apprenant (langue, fuseau horaire...)",
    )
    calendar_events: list[MoodleCalendarEvent] = Field(
        default_factory=list,
        description="Evenements calendrier des 30 prochains jours (toutes activites)",
    )
    forum_posts: list[MoodleForumPost] = Field(
        default_factory=list,
        description="Posts de forum rediges par l'apprenant (par cours)",
    )
    level: LearnerLevel = Field(
        default=LearnerLevel.UNKNOWN,
        description="Niveau global estime de l'apprenant (calcule)",
    )
    level_by_course: dict[int, LearnerLevel] = Field(
        default_factory=dict,
        description="Niveau estime par cours, indexe par courseid (calcule)",
    )
