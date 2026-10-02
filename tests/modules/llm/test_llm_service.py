"""Tests unitaires pour LLMService et _profile_to_text."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.exceptions import TooManyRequestsException
from src.modules.llm.models.log import LLMLog
from src.modules.llm.models.schemas import LearnerAnalysis, MoodleChatResponse
from src.modules.llm.repositories.llm_repository import LLMCompletion
from src.modules.llm.services.llm_service import (
    LLMService,
    _build_chat_profiles_context,
    _build_learner_context,
    _is_simple_query,
    _profile_to_chat_text,
    _profile_to_text,
)
from src.modules.moodle.models.schemas import (
    LearnerLevel,
    LearnerProfile,
    MoodleActivityEvent,
    MoodleAssignment,
    MoodleCompletion,
    MoodleCourse,
    MoodleCourseGrade,
    MoodleGradeItem,
    MoodleQuizAttempt,
    MoodleResource,
)

# ============================================================================
# Helpers
# ============================================================================


def _completion(**kwargs) -> LLMCompletion:
    return LLMCompletion(
        text=kwargs.get("text", "Reponse factice"),
        prompt_tokens=kwargs.get("prompt_tokens", 10),
        completion_tokens=kwargs.get("completion_tokens", 20),
        duration_ms=kwargs.get("duration_ms", 500),
    )


def _llm_repo(text: str = "Reponse factice") -> MagicMock:
    repo = MagicMock()
    repo._model = "mistral-small-latest"
    repo.chat_completion = AsyncMock(return_value=_completion(text=text))
    return repo


def _log_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert = AsyncMock()
    return repo


def _log_repo_with_tokens(used: int = 0) -> MagicMock:
    repo = MagicMock()
    repo.insert = AsyncMock()
    repo.sum_tokens_for_user_since = AsyncMock(return_value=used)
    return repo


def _svc(llm_repo=None, log_repo=None) -> LLMService:
    return LLMService(
        repository=llm_repo or _llm_repo(),
        log_repository=log_repo or _log_repo(),
    )


def _minimal_profile(**kwargs) -> LearnerProfile:
    return LearnerProfile(
        moodle_userid=kwargs.get("moodle_userid", 1),
        username=kwargs.get("username", "bob"),
        fullname=kwargs.get("fullname", "Bob Dupont"),
        email=kwargs.get("email", "bob@test.com"),
    )


# ============================================================================
# chat
# ============================================================================


async def test_chat_simple_message():
    """Verifie la reponse normale sans profil ni userid."""
    lr = _llm_repo("Super reponse")
    lo = _log_repo()
    result = await _svc(lr, lo).chat(message="Question ?")
    assert isinstance(result, MoodleChatResponse)
    assert result.response == "Super reponse"
    lo.insert.assert_awaited_once()


async def test_chat_message_included_in_user_content():
    """Verifie que le message est inclus dans le contenu utilisateur."""
    lr = _llm_repo()
    await _svc(lr).chat(message="Ma question")
    messages = lr.chat_completion.call_args[0][0]
    user_msg = next(m["content"] for m in messages if m["role"] == "user")
    assert "Ma question" in user_msg


async def test_chat_with_profile_includes_learner_context():
    """Verifie que le profil apprenant enrichit le contenu utilisateur."""
    lr = _llm_repo()
    profile = _minimal_profile(fullname="Alice Martin")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    await _svc(lr).chat(message="Aide-moi", profiles=[profile])
    messages = lr.chat_completion.call_args[0][0]
    user_msg = next(m["content"] for m in messages if m["role"] == "user")
    assert "Alice Martin" in user_msg


async def test_chat_with_multiple_profiles_includes_all_learners():
    """Verifie que plusieurs profils enfants enrichissent le contenu utilisateur."""
    lr = _llm_repo()
    profile_a = _minimal_profile(fullname="Alice Martin")
    profile_a.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile_b = _minimal_profile(moodle_userid=2, fullname="Bob Martin", username="bob")
    profile_b.courses = [
        MoodleCourse(id=2, fullname="SQL", shortname="SQL", progress=20.0)
    ]

    await _svc(lr).chat(message="Qui doit etre aide ?", profiles=[profile_a, profile_b])

    messages = lr.chat_completion.call_args[0][0]
    user_msg = next(m["content"] for m in messages if m["role"] == "user")
    assert "Alice Martin" in user_msg
    assert "Bob Martin" in user_msg


async def test_chat_logs_moodle_userid():
    """Verifie que moodle_userid est passe au log."""
    lo = _log_repo()
    await _svc(log_repo=lo).chat(message="Q", moodle_userid=42)
    log_entry: LLMLog = lo.insert.call_args[0][0]
    assert log_entry.moodle_userid == 42


async def test_chat_logs_without_userid():
    """Verifie que moodle_userid est None quand absent."""
    lo = _log_repo()
    await _svc(log_repo=lo).chat(message="Q")
    log_entry: LLMLog = lo.insert.call_args[0][0]
    assert log_entry.moodle_userid is None


# ============================================================================
# _build_learner_context
# ============================================================================


def test_build_learner_context_empty_profile():
    """Retourne chaine vide si aucun element significatif."""
    profile = _minimal_profile()
    result = _build_learner_context(profile)
    assert result == ""


def test_build_learner_context_good_progress():
    """Detecte les bonnes progressions (>= 70%)."""
    profile = _minimal_profile(fullname="Bob")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    result = _build_learner_context(profile)
    assert "Bonne progression" in result
    assert "Python" in result


def test_build_learner_context_low_progress():
    """Detecte les faibles progressions (< 30%) et propose une action."""
    profile = _minimal_profile()
    profile.courses = [
        MoodleCourse(id=1, fullname="SQL", shortname="SQL", progress=10.0)
    ]
    result = _build_learner_context(profile)
    assert "Points d'attention" in result
    assert "Actions prioritaires" in result
    assert "SQL" in result


def test_build_learner_context_abandoned_quiz():
    """Detecte les quiz abandonnes."""
    profile = _minimal_profile()
    profile.quiz_attempts = [
        MoodleQuizAttempt(quizid=7, attempt_number=1, state="abandoned", sumgrades=None)
    ]
    result = _build_learner_context(profile)
    assert "abandonn" in result.lower() or "Terminer" in result


def test_build_learner_context_with_activity_log():
    """Verifie que les evenements warning de activity_log apparaissent dans le contexte."""
    profile = _minimal_profile(fullname="Eve")
    profile.activity_log = [
        MoodleActivityEvent(
            event_type="assignment_late",
            description="Devoir 'TP Docker' en retard",
            severity="warning",
        ),
        MoodleActivityEvent(
            event_type="quiz_retried",
            description="Quiz 5 tente 3 fois",
            severity="info",
        ),
    ]
    result = _build_learner_context(profile)
    assert "Journal d'activite" in result
    # Seul le warning doit apparaitre (info exclu si filtrage severity)
    assert "TP Docker" in result


def test_build_learner_context_includes_estimated_level():
    """Le niveau estime doit apparaitre dans la synthese si renseigne."""
    profile = _minimal_profile(fullname="Mia")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.level = LearnerLevel.ADVANCED
    result = _build_learner_context(profile)
    assert "Niveau estime" in result
    assert "avance" in result


def test_build_learner_context_unknown_level_is_omitted():
    """UNKNOWN ne doit pas etre injecte dans la synthese."""
    profile = _minimal_profile(fullname="Mia")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.level = LearnerLevel.UNKNOWN
    result = _build_learner_context(profile)
    assert "Niveau estime" not in result


def test_profile_to_text_includes_course_level():
    """Le niveau par cours doit apparaitre dans la liste des cours inscrits."""
    profile = _minimal_profile(fullname="Tom")
    profile.courses = [
        MoodleCourse(id=42, fullname="Algebre", shortname="ALG", progress=55.0)
    ]
    profile.level = LearnerLevel.INTERMEDIATE
    profile.level_by_course = {42: LearnerLevel.INTERMEDIATE}
    result = _profile_to_text(profile)
    assert "Niveau estime : intermediaire" in result
    assert "niveau : intermediaire" in result


def test_build_learner_context_with_resources():
    """Verifie que l'index de ressources apparait dans le contexte."""
    profile = _minimal_profile()
    profile.courses = [MoodleCourse(id=1, fullname="Python avance", shortname="PY")]
    profile.resources_by_course = {
        1: [
            MoodleResource(
                cmid=10, name="Slides intro", modname="resource", section_name="Intro"
            ),
            MoodleResource(
                cmid=11, name="Quiz 1", modname="quiz", section_name="Evaluation"
            ),
        ]
    }
    result = _build_learner_context(profile)
    assert "Ressources disponibles" in result
    assert "Slides intro" in result
    assert "Quiz 1" in result


def test_build_profiles_context_multiple_profiles():
    """Verifie l'agregation de plusieurs profils dans le contexte chat."""
    profile_a = _minimal_profile(fullname="Alice Martin")
    profile_a.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile_b = _minimal_profile(moodle_userid=2, fullname="Bob Martin", username="bob")
    profile_b.courses = [
        MoodleCourse(id=2, fullname="SQL", shortname="SQL", progress=20.0)
    ]

    result = _build_chat_profiles_context([profile_a, profile_b])

    assert "Profils des apprenants rattaches" in result
    assert "Alice Martin" in result
    assert "Bob Martin" in result


def test_profile_to_chat_text_uses_compact_overview():
    """Le chat injecte un apercu cours compact (cours + notes globales),
    pas le dossier Moodle detaille (notes par activite, completion...)."""
    profile = _minimal_profile(fullname="Alice Martin")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.overview_grades = [
        MoodleCourseGrade(courseid=1, grade="15.00 / 20", rawgrade=15.0)
    ]
    profile.grades_by_course = {
        1: [
            MoodleGradeItem(
                itemname="Quiz 1",
                itemmodule="quiz",
                graderaw=8.0,
                grademax=10.0,
                gradeformatted="8.00",
            )
        ]
    }
    profile.resources_by_course = {
        1: [
            MoodleResource(
                cmid=10, name="Slides intro", modname="resource", section_name="Intro"
            ),
        ]
    }

    result = _profile_to_chat_text(profile)

    # Apercu compact present : cours + note globale + ressources
    assert "Apercu cours" in result
    assert "Python" in result
    assert "15.00 / 20" in result
    assert "=== Ressources disponibles ===" in result
    # Le dossier detaille n'est PAS injecte dans le chat
    assert "Donnees Moodle detaillees" not in result
    # Le format detaille "Quiz 1 (quiz) : 8.00/10.0" n'apparait pas
    # (le nom "Quiz 1" peut figurer dans la synthese sous "Bonne note en 'Quiz 1'")
    assert "(quiz) : 8.00" not in result
    assert "8.00/10.0" not in result


def test_profile_to_chat_text_compact_mode_drops_extras():
    """compact=True : ne garde que la synthese + l'apercu cours."""
    profile = _minimal_profile(fullname="Alice Martin")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.resources_by_course = {
        1: [
            MoodleResource(
                cmid=10, name="Slides intro", modname="resource", section_name="Intro"
            ),
        ]
    }

    result = _profile_to_chat_text(profile, compact=True)

    assert "Apercu cours" in result
    # En mode compact, on n'injecte pas la section detaillee dediee aux ressources
    # (la sous-section ressources de la synthese pedagogique reste OK)
    assert "=== Ressources disponibles ===" not in result
    assert "=== Badges ===" not in result
    assert "=== Evenements a venir ===" not in result
    assert "Donnees Moodle detaillees" not in result


# ============================================================================
# analyse_learner
# ============================================================================


async def test_analyse_learner_returns_analysis():
    """Verifie la structure de retour de analyse_learner."""
    lr = _llm_repo("Bilan pedagogique.")
    lo = _log_repo()
    profile = _minimal_profile(moodle_userid=7, fullname="Alice Martin")
    result = await _svc(lr, lo).analyse_learner(profile)
    assert isinstance(result, LearnerAnalysis)
    assert result.moodle_userid == 7
    assert result.fullname == "Alice Martin"
    assert result.model_used == "mistral-small-latest"
    assert result.analysis == "Bilan pedagogique."
    lo.insert.assert_awaited_once()


async def test_analyse_learner_logs_userid():
    """Verifie que le moodle_userid du profil est logue."""
    lo = _log_repo()
    profile = _minimal_profile(moodle_userid=99)
    await _svc(log_repo=lo).analyse_learner(profile)
    log_entry: LLMLog = lo.insert.call_args[0][0]
    assert log_entry.moodle_userid == 99


# ============================================================================
# _log — echec silencieux
# ============================================================================


async def test_log_does_not_raise_on_exception():
    """Verifie que _log avale l'exception sans la propager."""
    lo = _log_repo()
    lo.insert.side_effect = Exception("DB indisponible")
    svc = _svc(log_repo=lo)
    await svc._log(10, 20, 500, None)  # ne doit pas lever


async def test_log_stores_correct_metrics():
    """Verifie que _log passe les bonnes metriques au repository."""
    lo = _log_repo()
    svc = _svc(log_repo=lo)
    await svc._log(
        prompt_tokens=15, completion_tokens=30, duration_ms=750, moodle_userid=5
    )
    log_entry: LLMLog = lo.insert.call_args[0][0]
    assert log_entry.prompt_tokens == 15
    assert log_entry.completion_tokens == 30
    assert log_entry.duration_ms == 750
    assert log_entry.moodle_userid == 5


# ============================================================================
# _profile_to_text
# ============================================================================


def test_profile_to_text_minimal():
    profile = _minimal_profile(fullname="Bob Dupont", username="bob", email="bob@t.com")
    text = _profile_to_text(profile)
    assert "Bob Dupont" in text
    assert "bob" in text
    assert "bob@t.com" in text


def test_profile_to_text_with_course_progress():
    course = MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    profile = _minimal_profile()
    profile.courses = [course]
    text = _profile_to_text(profile)
    assert "Python" in text
    assert "80%" in text


def test_profile_to_text_course_no_progress():
    course = MoodleCourse(id=1, fullname="Python", shortname="PY", progress=None)
    profile = _minimal_profile()
    profile.courses = [course]
    text = _profile_to_text(profile)
    assert "progression non suivie" in text


def test_profile_to_text_with_overview_grades():
    profile = _minimal_profile()
    profile.overview_grades = [
        MoodleCourseGrade(courseid=1, grade="15.00", rawgrade=15.0)
    ]
    text = _profile_to_text(profile)
    assert "15.00" in text


def test_profile_to_text_with_grade_items():
    profile = _minimal_profile()
    profile.grades_by_course = {
        1: [
            MoodleGradeItem(
                itemname="Quiz 1",
                itemmodule="quiz",
                graderaw=8.0,
                grademax=10.0,
                gradeformatted="8.00",
            )
        ]
    }
    text = _profile_to_text(profile)
    assert "Quiz 1" in text
    assert "8.00" in text


def test_profile_to_text_grade_item_no_graderaw_excluded():
    """Les activites sans note brute ne doivent pas apparaitre."""
    profile = _minimal_profile()
    profile.grades_by_course = {
        1: [MoodleGradeItem(itemname="Page", itemmodule="page", graderaw=None)]
    }
    text = _profile_to_text(profile)
    assert "Page" not in text


def test_profile_to_text_grade_item_with_feedback():
    profile = _minimal_profile()
    profile.grades_by_course = {
        1: [
            MoodleGradeItem(
                itemname="Devoir",
                itemmodule="assign",
                graderaw=12.0,
                gradeformatted="12.00",
                feedback="Bon travail",
            )
        ]
    }
    text = _profile_to_text(profile)
    assert "Bon travail" in text


def test_profile_to_text_with_completion():
    profile = _minimal_profile()
    profile.courses = [MoodleCourse(id=1, fullname="Cours A", shortname="CA")]
    profile.completion_by_course = {
        1: [
            MoodleCompletion(cmid=1, modname="quiz", state=1),
            MoodleCompletion(cmid=2, modname="page", state=0),
        ]
    }
    text = _profile_to_text(profile)
    assert "1/2" in text
    assert "Cours A" in text


def test_profile_to_text_with_quiz_attempts():
    profile = _minimal_profile()
    profile.quiz_attempts = [
        MoodleQuizAttempt(quizid=5, attempt_number=1, state="finished", sumgrades=9.5)
    ]
    text = _profile_to_text(profile)
    assert "Quiz 5" in text
    assert "9.5 pts" in text


def test_profile_to_text_quiz_no_score():
    profile = _minimal_profile()
    profile.quiz_attempts = [
        MoodleQuizAttempt(
            quizid=3, attempt_number=1, state="inprogress", sumgrades=None
        )
    ]
    text = _profile_to_text(profile)
    assert "score non disponible" in text


def test_profile_to_text_with_assignments():
    profile = _minimal_profile()
    profile.assignments = [
        MoodleAssignment(
            assignid=10, name="Devoir final", status="submitted", grade=14.0
        )
    ]
    text = _profile_to_text(profile)
    assert "Devoir final" in text
    assert "submitted" in text
    assert "14.0" in text


def test_profile_to_text_assignment_not_submitted():
    profile = _minimal_profile()
    profile.assignments = [
        MoodleAssignment(assignid=1, name="Devoir", status=None, grade=None)
    ]
    text = _profile_to_text(profile)
    assert "non soumis" in text


# ============================================================================
# _is_simple_query — routage modele
# ============================================================================


def test_is_simple_query_short_no_profile():
    """Message court sans profil → modele leger."""
    assert _is_simple_query("aide-moi", has_profile=False) is True


def test_is_simple_query_long_no_profile():
    """Message long sans profil → modele lourd malgre l'absence de profil."""
    long_msg = " ".join(["mot"] * 30)
    assert _is_simple_query(long_msg, has_profile=False) is False


def test_is_simple_query_with_profile():
    """Presence d'un profil → toujours modele lourd."""
    assert _is_simple_query("aide-moi", has_profile=True) is False


# ============================================================================
# cache Redis
# ============================================================================


async def test_chat_returns_cached_response():
    """Un hit cache retourne la reponse sans appeler le LLM."""
    import json
    from unittest.mock import AsyncMock

    cached_data = {"response": "Reponse en cache"}
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=json.dumps(cached_data))
    cache.set = AsyncMock()

    lr = _llm_repo()
    svc = LLMService(repository=lr, log_repository=_log_repo(), cache=cache)
    result = await svc.chat(message="aide-moi")

    assert result.response == "Reponse en cache"
    lr.chat_completion.assert_not_awaited()  # LLM non appele


async def test_chat_stores_response_in_cache():
    """Une reponse fraiche est mise en cache apres l'appel LLM."""
    from unittest.mock import AsyncMock

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)  # cache vide
    cache.set = AsyncMock()

    svc = LLMService(repository=_llm_repo(), log_repository=_log_repo(), cache=cache)
    await svc.chat(message="aide-moi")

    cache.set.assert_awaited_once()
    key, value = cache.set.call_args[0][:2]
    assert key.startswith("llm:chat:")


async def test_chat_no_cache_still_works():
    """Sans cache (None), le service fonctionne normalement."""
    lr = _llm_repo("Reponse normale")
    svc = LLMService(repository=lr, log_repository=_log_repo(), cache=None)
    result = await svc.chat(message="aide-moi")
    assert result.response == "Reponse normale"
    lr.chat_completion.assert_awaited_once()


async def test_chat_uses_light_model_for_simple_query():
    """Question courte sans profil → model_light passe au repository."""
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        model_light="open-mistral-7b",
    )
    await svc.chat(message="aide-moi")
    _, call_kwargs = lr.chat_completion.call_args
    assert call_kwargs.get("model") == "open-mistral-7b"


async def test_chat_uses_heavy_model_with_profile():
    """Profil present → modele lourd (repository._model)."""
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        model_light="open-mistral-7b",
    )
    profile = _minimal_profile()
    await svc.chat(message="aide-moi", profiles=[profile])
    _, call_kwargs = lr.chat_completion.call_args
    assert call_kwargs.get("model") == "mistral-small-latest"


# ============================================================================
# Limite quotidienne de tokens
# ============================================================================


async def test_chat_under_daily_limit_passes():
    """Tokens consommes < limite -> appel autorise."""
    lo = _log_repo_with_tokens(used=500)
    svc = LLMService(
        repository=_llm_repo(),
        log_repository=lo,
        daily_token_limit=1000,
    )
    result = await svc.chat(message="Q", moodle_userid=42)
    assert isinstance(result, MoodleChatResponse)


async def test_chat_over_daily_limit_raises_429():
    """Tokens consommes >= limite -> TooManyRequestsException, LLM non appele."""
    lo = _log_repo_with_tokens(used=1500)
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=lo,
        daily_token_limit=1000,
    )
    with pytest.raises(TooManyRequestsException) as exc:
        await svc.chat(message="Q", moodle_userid=42)
    assert exc.value.status_code == 429
    lr.chat_completion.assert_not_awaited()


async def test_chat_limit_disabled_when_zero():
    """daily_token_limit=0 -> aucun check, sum_tokens_for_user_since pas appele."""
    lo = _log_repo_with_tokens(used=999999)
    svc = LLMService(
        repository=_llm_repo(),
        log_repository=lo,
        daily_token_limit=0,
    )
    await svc.chat(message="Q", moodle_userid=42)
    lo.sum_tokens_for_user_since.assert_not_awaited()


async def test_chat_no_userid_skips_limit_check():
    """moodle_userid=None -> pas de check de limite."""
    lo = _log_repo_with_tokens(used=999999)
    svc = LLMService(
        repository=_llm_repo(),
        log_repository=lo,
        daily_token_limit=1000,
    )
    await svc.chat(message="Q", moodle_userid=None)
    lo.sum_tokens_for_user_since.assert_not_awaited()


async def test_chat_cache_hit_skips_limit_check():
    """Un hit cache court-circuite le check limite (pas de tokens reels consommes)."""
    import json

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=json.dumps({"response": "cached"}))
    cache.set = AsyncMock()

    lo = _log_repo_with_tokens(used=999999)
    svc = LLMService(
        repository=_llm_repo(),
        log_repository=lo,
        cache=cache,
        daily_token_limit=1000,
    )
    result = await svc.chat(message="Q", moodle_userid=42)
    assert result.response == "cached"
    lo.sum_tokens_for_user_since.assert_not_awaited()


async def test_analyse_learner_over_daily_limit_raises_429():
    """analyse_learner respecte aussi la limite quotidienne."""
    lo = _log_repo_with_tokens(used=1500)
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=lo,
        daily_token_limit=1000,
    )
    profile = _minimal_profile(moodle_userid=42)
    with pytest.raises(TooManyRequestsException):
        await svc.analyse_learner(profile)
    lr.chat_completion.assert_not_awaited()


# ============================================================================
# Garde-fou tokens : troncature en mode compact si depassement
# ============================================================================


async def test_chat_truncates_oversized_context_to_compact():
    """Si le prompt depasse max_prompt_tokens, on injecte la version compacte."""
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        max_prompt_tokens=100,  # tres bas pour forcer la troncature
    )
    profile = _minimal_profile(fullname="Alice Martin")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.resources_by_course = {
        1: [
            MoodleResource(
                cmid=i,
                name=f"Ressource {i} avec un nom volontairement tres long " * 5,
                modname="resource",
                section_name="S",
            )
            for i in range(20)
        ]
    }

    await svc.chat(message="Aide", profiles=[profile])

    messages = lr.chat_completion.call_args[0][0]
    user_msg = next(m["content"] for m in messages if m["role"] == "user")
    # En mode compact, la section dediee "=== Ressources disponibles ===" est retiree
    assert "=== Ressources disponibles ===" not in user_msg
    # La synthese / apercu cours reste injectee
    assert "Alice Martin" in user_msg


async def test_chat_keeps_full_context_under_budget():
    """Si l'estimation reste sous le budget, on injecte le contexte complet."""
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        max_prompt_tokens=100000,  # tres haut, ne se declenche jamais
    )
    profile = _minimal_profile(fullname="Alice Martin")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.resources_by_course = {
        1: [
            MoodleResource(
                cmid=10, name="Slides intro", modname="resource", section_name="Intro"
            ),
        ]
    }

    await svc.chat(message="Aide", profiles=[profile])

    messages = lr.chat_completion.call_args[0][0]
    user_msg = next(m["content"] for m in messages if m["role"] == "user")
    # Section dediee preservee (en plus de la sous-section dans la synthese)
    assert "=== Ressources disponibles ===" in user_msg


async def test_chat_no_budget_set_keeps_full_context():
    """max_prompt_tokens=0 -> garde-fou desactive."""
    lr = _llm_repo()
    svc = LLMService(
        repository=lr,
        log_repository=_log_repo(),
        max_prompt_tokens=0,
    )
    profile = _minimal_profile(fullname="Alice Martin")
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.resources_by_course = {
        1: [
            MoodleResource(
                cmid=10, name="Slides intro", modname="resource", section_name="Intro"
            ),
        ]
    }

    await svc.chat(message="Aide", profiles=[profile])

    messages = lr.chat_completion.call_args[0][0]
    user_msg = next(m["content"] for m in messages if m["role"] == "user")
    assert "=== Ressources disponibles ===" in user_msg


# ============================================================================
# Apercu cours compact
# ============================================================================


def test_profile_to_chat_overview_lists_courses_with_progress():
    """L'apercu compact liste les cours avec leur progression."""
    from src.modules.llm.services.llm_service import _profile_to_chat_overview

    profile = _minimal_profile()
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0),
        MoodleCourse(id=2, fullname="SQL", shortname="SQL", progress=None),
    ]
    result = _profile_to_chat_overview(profile)
    assert "Cours inscrits (2)" in result
    assert "Python : 80%" in result
    assert "SQL : n/a" in result


def test_profile_to_chat_overview_includes_overview_grades():
    """L'apercu compact inclut les notes globales par cours."""
    from src.modules.llm.services.llm_service import _profile_to_chat_overview

    profile = _minimal_profile()
    profile.courses = [
        MoodleCourse(id=1, fullname="Python", shortname="PY", progress=80.0)
    ]
    profile.overview_grades = [
        MoodleCourseGrade(courseid=1, grade="15.00 / 20", rawgrade=15.0)
    ]
    result = _profile_to_chat_overview(profile)
    assert "Notes globales" in result
    assert "Python : 15.00 / 20" in result


def test_profile_to_chat_overview_empty_profile():
    """Profil vide -> chaine vide."""
    from src.modules.llm.services.llm_service import _profile_to_chat_overview

    profile = _minimal_profile()
    assert _profile_to_chat_overview(profile) == ""


# ============================================================================
# _estimate_tokens
# ============================================================================


def test_estimate_tokens_heuristic_4_chars_per_token():
    """4 caracteres = 1 token approximativement."""
    from src.modules.llm.services.llm_service import _estimate_tokens

    assert _estimate_tokens("") == 0
    assert _estimate_tokens("abcd") == 1
    assert _estimate_tokens("a" * 400) == 100
