"""Tests unitaires pour MoodleService et _to_float (mock du repository HTTP)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.moodle.models.schemas import (
    LearnerLevel,
    LearnerProfile,
    MoodleAssignment,
    MoodleCompletion,
    MoodleCourse,
    MoodleGradeItem,
    MoodleQuizAttempt,
)
from src.modules.moodle.repositories.moodle_repository import MoodleAPIException
from src.modules.moodle.services.moodle_service import (
    MoodleService,
    _build_activity_log,
    _classify_level,
    _compute_learner_level,
    _state_to_correct,
    _to_float,
)

# ============================================================================
# Helpers
# ============================================================================


def _repo(**call_return):
    """Cree un MoodleRepository factice dont call() renvoie call_return."""
    repo = MagicMock()
    repo.call = AsyncMock(return_value=call_return.get("return_value", []))
    return repo


def _svc(repo=None):
    """Cree un MoodleService avec un repository factice."""
    return MoodleService(repository=repo or _repo())


# ============================================================================
# _to_float
# ============================================================================


def test_to_float_none():
    assert _to_float(None) is None


def test_to_float_string_valid():
    assert _to_float("14.5") == 14.5


def test_to_float_string_invalid():
    assert _to_float("abc") is None


def test_to_float_int():
    assert _to_float(10) == 10.0


def test_to_float_zero():
    assert _to_float(0) == 0.0


# ============================================================================
# get_site_info
# ============================================================================


async def test_get_site_info():
    repo = _repo(return_value={"release": "4.3", "siteurl": "http://moodle.test"})
    result = await _svc(repo).get_site_info()
    assert result["release"] == "4.3"
    repo.call.assert_awaited_once_with("core_webservice_get_site_info")


# ============================================================================
# _get_user
# ============================================================================


async def test_get_user_success():
    repo = _repo(
        return_value=[
            {"id": 5, "username": "alice", "fullname": "Alice", "email": "a@test.com"}
        ]
    )
    user = await _svc(repo)._get_user(5)
    assert user["username"] == "alice"


async def test_get_user_not_found():
    repo = _repo(return_value=[])
    with pytest.raises(MoodleAPIException):
        await _svc(repo)._get_user(999)


async def test_get_user_non_list_response():
    repo = _repo(return_value=None)
    with pytest.raises(MoodleAPIException):
        await _svc(repo)._get_user(1)


# ============================================================================
# _get_courses
# ============================================================================


async def test_get_courses_success():
    repo = _repo(
        return_value=[
            {"id": 101, "fullname": "Python", "shortname": "PY101", "progress": 50.0}
        ]
    )
    courses = await _svc(repo)._get_courses(5)
    assert len(courses) == 1
    assert courses[0].shortname == "PY101"
    assert courses[0].progress == 50.0


async def test_get_courses_empty():
    repo = _repo(return_value=[])
    assert await _svc(repo)._get_courses(5) == []


async def test_get_courses_no_lastaccess():
    repo = _repo(
        return_value=[{"id": 1, "fullname": "F", "shortname": "S", "lastaccess": 0}]
    )
    courses = await _svc(repo)._get_courses(5)
    assert courses[0].lastaccess is None


# ============================================================================
# _get_overview_grades
# ============================================================================


async def test_get_overview_grades_dict_response():
    repo = _repo(
        return_value={"grades": [{"courseid": 101, "grade": "15.00", "rawgrade": "15"}]}
    )
    grades = await _svc(repo)._get_overview_grades(5)
    assert len(grades) == 1
    assert grades[0].grade == "15.00"
    assert grades[0].rawgrade == 15.0


async def test_get_overview_grades_list_response():
    repo = _repo(return_value=[{"courseid": 101, "grade": "12.00"}])
    grades = await _svc(repo)._get_overview_grades(5)
    assert len(grades) == 1


async def test_get_overview_grades_empty():
    repo = _repo(return_value={"grades": []})
    assert await _svc(repo)._get_overview_grades(5) == []


# ============================================================================
# _get_grade_items
# ============================================================================


async def test_get_grade_items_dict_response():
    repo = _repo(
        return_value={
            "usergrades": [
                {
                    "gradeitems": [
                        {
                            "itemname": "Quiz 1",
                            "itemmodule": "quiz",
                            "graderaw": "8",
                            "grademax": "10",
                            "gradeformatted": "8.00",
                            "feedback": "Bien",
                        }
                    ]
                }
            ]
        }
    )
    items = await _svc(repo)._get_grade_items(5, 101)
    assert len(items) == 1
    assert items[0].itemname == "Quiz 1"
    assert items[0].graderaw == 8.0
    assert items[0].feedback == "Bien"


async def test_get_grade_items_list_response():
    repo = _repo(
        return_value=[{"itemname": "Devoir", "itemmodule": "assign", "graderaw": "14"}]
    )
    items = await _svc(repo)._get_grade_items(5, 101)
    assert len(items) == 1


async def test_get_grade_items_exception_returns_empty():
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Interdit"))
    assert await _svc(repo)._get_grade_items(5, 101) == []


# ============================================================================
# _get_completion
# ============================================================================


async def test_get_completion_dict_response():
    repo = _repo(
        return_value={"statuses": [{"cmid": 1, "modname": "quiz", "state": 1}]}
    )
    completions = await _svc(repo)._get_completion(5, 101)
    assert len(completions) == 1
    assert completions[0].state == 1


async def test_get_completion_list_response():
    repo = _repo(return_value=[{"cmid": 2, "modname": "page", "state": 0}])
    completions = await _svc(repo)._get_completion(5, 101)
    assert len(completions) == 1


async def test_get_completion_exception_returns_empty():
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Erreur"))
    assert await _svc(repo)._get_completion(5, 101) == []


# ============================================================================
# _get_quiz_attempts
# ============================================================================


async def test_get_quiz_attempts_no_quizzes():
    repo = _repo(return_value={"quizzes": []})
    assert await _svc(repo)._get_quiz_attempts(5, 101) == []


async def test_get_quiz_attempts_exception_returns_empty():
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Erreur"))
    assert await _svc(repo)._get_quiz_attempts(5, 101) == []


async def test_get_quiz_attempts_with_quizzes():
    """Verifie l'orchestration quiz → attempts."""
    repo = MagicMock()
    # Premier appel : liste de quizzes
    # Deuxieme appel : attempts pour le quiz
    repo.call = AsyncMock(
        side_effect=[
            {"quizzes": [{"id": 7}]},
            {"attempts": [{"attempt": 1, "state": "finished", "sumgrades": "9"}]},
        ]
    )
    attempts = await _svc(repo)._get_quiz_attempts(5, 101)
    assert len(attempts) == 1
    assert attempts[0].quizid == 7
    assert attempts[0].sumgrades == 9.0


# ============================================================================
# _get_attempts_for_quiz
# ============================================================================


async def test_get_attempts_for_quiz_success():
    repo = _repo(
        return_value={
            "attempts": [{"attempt": 2, "state": "finished", "sumgrades": "8.5"}]
        }
    )
    attempts = await _svc(repo)._get_attempts_for_quiz(5, 42)
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 2
    assert attempts[0].sumgrades == 8.5


async def test_get_attempts_for_quiz_exception_returns_empty():
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Erreur"))
    assert await _svc(repo)._get_attempts_for_quiz(5, 42) == []


async def test_get_attempts_for_quiz_list_response():
    repo = _repo(return_value=[{"attempt": 1, "state": "inprogress", "timefinish": 0}])
    attempts = await _svc(repo)._get_attempts_for_quiz(5, 42)
    assert len(attempts) == 1
    assert attempts[0].timefinish is None


# ============================================================================
# _get_assignments
# ============================================================================


async def test_get_assignments_exception_returns_empty():
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Erreur"))
    assert await _svc(repo)._get_assignments(5, 101) == []


async def test_get_assignments_with_courses():
    """Verifie la collecte des devoirs via mod_assign_get_assignments."""
    repo = MagicMock()
    repo.call = AsyncMock(
        side_effect=[
            # mod_assign_get_assignments
            {
                "courses": [
                    {"assignments": [{"id": 10, "name": "Devoir 1", "duedate": 0}]}
                ]
            },
            # mod_assign_get_submission_status
            {
                "lastattempt": {
                    "submission": {"status": "submitted"},
                    "gradingstatus": "graded",
                },
                "feedback": {"gradefordisplay": "14.00"},
            },
        ]
    )
    assigns = await _svc(repo)._get_assignments(5, 101)
    assert len(assigns) == 1
    assert assigns[0].name == "Devoir 1"
    assert assigns[0].status == "submitted"


async def test_get_assignments_empty_courses():
    repo = _repo(return_value={"courses": []})
    assert await _svc(repo)._get_assignments(5, 101) == []


# ============================================================================
# _get_submission_status
# ============================================================================


async def test_get_submission_status_exception_fallback():
    """Verifie le fallback minimal quand get_submission_status echoue."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Interdit"))
    assign = {"id": 10, "name": "Devoir fallback", "duedate": 1700000000}
    result = await _svc(repo)._get_submission_status(5, assign)
    assert result.assignid == 10
    assert result.name == "Devoir fallback"
    assert result.status is None
    assert result.grade is None


async def test_get_submission_status_full():
    repo = _repo(
        return_value={
            "lastattempt": {
                "submission": {"status": "submitted"},
                "gradingstatus": "graded",
            },
            "feedback": {"gradefordisplay": "15.00"},
        }
    )
    assign = {"id": 5, "name": "Devoir final", "duedate": 0}
    result = await _svc(repo)._get_submission_status(5, assign)
    assert result.status == "submitted"
    assert result.gradingstatus == "graded"
    assert result.grade == 15.0


# ============================================================================
# _get_course_detail (methode d'orchestration)
# ============================================================================


async def test_get_course_detail():
    """Verifie que _get_course_detail orchestre toutes les sous-methodes."""
    repo = MagicMock()
    # Reponses dans l'ordre des appels asyncio.gather :
    # grade_items, completion, quiz_attempts, assignments, resources, calendar_events, forum_posts
    repo.call = AsyncMock(
        side_effect=[
            # _get_grade_items
            {"usergrades": [{"gradeitems": []}]},
            # _get_completion
            {"statuses": []},
            # _get_quiz_attempts
            {"quizzes": []},
            # _get_assignments
            {"courses": []},
            # _get_course_resources
            [],
            # _get_calendar_events
            {"events": []},
            # _get_forum_posts : get_forums puis get_posts
            [],  # mod_forum_get_forums_by_courses → pas de forum
        ]
    )
    course = MoodleCourse(id=101, fullname="Python", shortname="PY")
    (
        course_id,
        grades,
        completions,
        attempts,
        assigns,
        resources,
        cal_events,
        f_posts,
    ) = await _svc(repo)._get_course_detail(5, course)
    assert course_id == 101
    assert grades == []
    assert completions == []
    assert attempts == []
    assert assigns == []
    assert resources == []
    assert cal_events == []
    assert f_posts == []


# ============================================================================
# _get_course_resources
# ============================================================================


async def test_get_course_resources_success():
    """Verifie la construction de MoodleResource depuis core_course_get_contents."""
    repo = _repo(
        return_value=[
            {
                "name": "Introduction",
                "modules": [
                    {
                        "id": 10,
                        "name": "Slides Python",
                        "modname": "resource",
                        "url": "https://moodle.test/mod/resource/view.php?id=10",
                        "description": "<p>Supports de cours</p>",
                    },
                    {
                        "id": 11,
                        "name": "Quiz 1",
                        "modname": "quiz",
                        "url": None,
                        "description": "",
                    },
                ],
            }
        ]
    )
    resources = await _svc(repo)._get_course_resources(101)
    assert len(resources) == 2
    assert resources[0].name == "Slides Python"
    assert resources[0].modname == "resource"
    assert resources[0].section_name == "Introduction"
    assert resources[0].description == "Supports de cours"


async def test_get_course_resources_skips_labels():
    """Verifie que les modules de type 'label' sont ignores."""
    repo = _repo(
        return_value=[
            {
                "name": "Section 1",
                "modules": [
                    {"id": 1, "name": "Titre decoratif", "modname": "label"},
                    {"id": 2, "name": "Page intro", "modname": "page"},
                ],
            }
        ]
    )
    resources = await _svc(repo)._get_course_resources(101)
    assert len(resources) == 1
    assert resources[0].modname == "page"


async def test_get_course_resources_api_error_returns_empty():
    """Verifie que les erreurs API retournent une liste vide."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Interdit"))
    resources = await _svc(repo)._get_course_resources(101)
    assert resources == []


# ============================================================================
# _build_activity_log
# ============================================================================


def test_build_activity_log_quiz_abandoned():
    """Detecte un quiz abandonne."""
    attempts = [MoodleQuizAttempt(quizid=5, attempt_number=1, state="abandoned")]
    events = _build_activity_log([], attempts, [], {})
    types = [e.event_type for e in events]
    assert "quiz_abandoned" in types


def test_build_activity_log_quiz_retried():
    """Detecte les quiz tentes plusieurs fois."""
    attempts = [
        MoodleQuizAttempt(quizid=5, attempt_number=1, state="finished"),
        MoodleQuizAttempt(quizid=5, attempt_number=2, state="finished"),
    ]
    events = _build_activity_log([], attempts, [], {})
    types = [e.event_type for e in events]
    assert "quiz_retried" in types


def test_build_activity_log_assignment_late():
    """Detecte un devoir en retard."""
    past_ts = 1_000_000  # 1970 — clairement passe
    assigns = [
        MoodleAssignment(assignid=1, name="Devoir Python", duedate=past_ts, status=None)
    ]
    events = _build_activity_log([], [], assigns, {})
    types = [e.event_type for e in events]
    assert "assignment_late" in types


def test_build_activity_log_course_inactive():
    """Detecte une inactivite prolongee sur un cours."""
    old_ts = 1_000_000  # 1970 — plus de 7 jours
    course = MoodleCourse(id=1, fullname="Python", shortname="PY", lastaccess=old_ts)
    events = _build_activity_log([course], [], [], {})
    types = [e.event_type for e in events]
    assert "course_inactive" in types


def test_build_activity_log_incomplete_activities():
    """Detecte les cours avec majorite d'activites incompletes (>= 3 et >= 50%)."""
    completions = {
        1: [
            MoodleCompletion(cmid=1, modname="quiz", state=0),
            MoodleCompletion(cmid=2, modname="page", state=0),
            MoodleCompletion(cmid=3, modname="assign", state=0),
            MoodleCompletion(cmid=4, modname="page", state=1),
        ]
    }
    events = _build_activity_log([], [], [], completions)
    types = [e.event_type for e in events]
    assert "incomplete_activities" in types


def test_build_activity_log_no_events_when_clean():
    """Retourne liste vide quand tout va bien."""
    course = MoodleCourse(id=1, fullname="Python", shortname="PY", lastaccess=None)
    events = _build_activity_log([course], [], [], {})
    assert events == []


def test_build_activity_log_warnings_sorted_first():
    """Verifie que les warnings apparaissent avant les evenements info."""
    attempts = [
        MoodleQuizAttempt(quizid=5, attempt_number=1, state="finished"),
        MoodleQuizAttempt(quizid=5, attempt_number=2, state="finished"),
        MoodleQuizAttempt(quizid=5, attempt_number=1, state="abandoned"),
    ]
    events = _build_activity_log([], attempts, [], {})
    severities = [e.severity for e in events]
    # Le premier evenement doit etre "warning"
    assert severities[0] == "warning"


# ============================================================================
# get_learner_profile (smoke test via mocks imbriques)
# ============================================================================


async def test_get_learner_profile_minimal():
    """Verifie que get_learner_profile retourne un LearnerProfile valide."""
    repo = MagicMock()
    call_responses = [
        # _get_user
        [{"id": 7, "username": "alice", "fullname": "Alice", "email": "a@t.com"}],
        # _get_courses
        [],
        # _get_overview_grades
        {"grades": []},
        # _get_badges
        {"badges": []},
        # _get_user_preferences
        {"preferences": []},
    ]
    repo.call = AsyncMock(side_effect=call_responses)
    profile = await _svc(repo).get_learner_profile(7)
    assert isinstance(profile, LearnerProfile)
    assert profile.moodle_userid == 7
    assert profile.username == "alice"
    assert profile.courses == []


# ============================================================================
# Cache Redis
# ============================================================================

_CACHED_PROFILE = LearnerProfile(
    moodle_userid=42,
    username="bob",
    fullname="Bob",
    email="bob@t.com",
)

_CACHE_ENTRY = json.dumps(
    {"profile": _CACHED_PROFILE.model_dump(), "cached_at": 1700000000}
)


async def test_get_learner_profile_cache_hit():
    """Cache hit sans mise a jour Moodle : le repository n'est pas appele."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=_CACHE_ENTRY)
    repo = MagicMock()
    repo.call = AsyncMock()

    svc = MoodleService(repository=repo, redis=redis, cache_ttl=300)
    profile = await svc.get_learner_profile(42)

    assert profile.moodle_userid == 42
    assert profile.username == "bob"
    # Aucun appel WS : pas de cours donc _courses_have_updates court-circuite
    repo.call.assert_not_called()


async def test_get_learner_profile_cache_miss_stores_result():
    """Cache miss : le profil est construit puis stocke dans Redis."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()

    repo = MagicMock()
    repo.call = AsyncMock(
        side_effect=[
            [{"id": 42, "username": "bob", "fullname": "Bob", "email": "bob@t.com"}],
            [],
            {"grades": []},
            {"badges": []},
            {"preferences": []},
        ]
    )

    svc = MoodleService(repository=repo, redis=redis, cache_ttl=300)
    profile = await svc.get_learner_profile(42)

    assert profile.moodle_userid == 42
    redis.setex.assert_awaited_once()
    key, ttl, raw = redis.setex.call_args.args
    assert key == "moodle:learner:42"
    assert ttl == 300
    stored = json.loads(raw)
    assert "profile" in stored
    assert "cached_at" in stored


async def test_get_learner_profile_delta_sync_triggers_rebuild():
    """Delta sync : si Moodle signale des mises a jour, le cache est invalide et reconstruit."""
    profile_with_course = LearnerProfile(
        moodle_userid=42,
        username="bob",
        fullname="Bob",
        email="bob@t.com",
        courses=[MoodleCourse(id=10, fullname="Cours A", shortname="CA")],
    )
    cache_entry = json.dumps(
        {"profile": profile_with_course.model_dump(), "cached_at": 1700000000}
    )

    redis = MagicMock()
    redis.get = AsyncMock(return_value=cache_entry)
    redis.delete = AsyncMock()
    redis.setex = AsyncMock()

    repo = MagicMock()
    repo.call = AsyncMock(
        side_effect=[
            # _course_has_updates -> instances non vide = mise a jour detectee
            {"instances": [{"contextlevel": "module", "id": 5}]},
            # _build_learner_profile : _get_user, _get_courses, _get_overview_grades, badges, prefs
            [{"id": 42, "username": "bob", "fullname": "Bob", "email": "bob@t.com"}],
            [],
            {"grades": []},
            {"badges": []},
            {"preferences": []},
        ]
    )

    svc = MoodleService(repository=repo, redis=redis, cache_ttl=300)
    await svc.get_learner_profile(42)

    redis.delete.assert_awaited_once_with("moodle:learner:42")
    redis.setex.assert_awaited_once()


async def test_get_learner_profile_delta_sync_no_update_serves_cache():
    """Delta sync : pas de mise a jour Moodle -> le cache est servi sans rebuild."""
    profile_with_course = LearnerProfile(
        moodle_userid=42,
        username="bob",
        fullname="Bob",
        email="bob@t.com",
        courses=[MoodleCourse(id=10, fullname="Cours A", shortname="CA")],
    )
    cache_entry = json.dumps(
        {"profile": profile_with_course.model_dump(), "cached_at": 1700000000}
    )

    redis = MagicMock()
    redis.get = AsyncMock(return_value=cache_entry)
    redis.delete = AsyncMock()

    repo = MagicMock()
    # _course_has_updates -> instances vide = pas de mise a jour
    repo.call = AsyncMock(return_value={"instances": []})

    svc = MoodleService(repository=repo, redis=redis, cache_ttl=300)
    profile = await svc.get_learner_profile(42)

    assert profile.username == "bob"
    redis.delete.assert_not_called()
    # Un seul appel WS : core_course_get_updates_since
    repo.call.assert_awaited_once()


async def test_get_learner_profile_cache_disabled():
    """TTL=0 : Redis n'est pas consulte meme si disponible."""
    redis = MagicMock()
    redis.get = AsyncMock()

    repo = MagicMock()
    repo.call = AsyncMock(
        side_effect=[
            [{"id": 42, "username": "bob", "fullname": "Bob", "email": "bob@t.com"}],
            [],
            {"grades": []},
            {"badges": []},
            {"preferences": []},
        ]
    )

    svc = MoodleService(repository=repo, redis=redis, cache_ttl=0)
    await svc.get_learner_profile(42)

    redis.get.assert_not_called()


async def test_invalidate_learner_cache():
    """invalidate_learner_cache supprime la bonne cle Redis."""
    redis = MagicMock()
    redis.delete = AsyncMock()

    svc = MoodleService(repository=MagicMock(), redis=redis, cache_ttl=300)
    await svc.invalidate_learner_cache(42)

    redis.delete.assert_awaited_once_with("moodle:learner:42")


# ============================================================================
# Badges et preferences
# ============================================================================


async def test_get_badges_returns_list():
    """_get_badges parse correctement la reponse Moodle."""
    repo = _repo(
        return_value={
            "badges": [{"id": 1, "name": "Premier pas", "dateissued": 1700000000}]
        }
    )
    svc = _svc(repo)
    badges = await svc._get_badges(42)
    assert len(badges) == 1
    assert badges[0].name == "Premier pas"
    assert badges[0].dateissued == 1700000000


async def test_get_badges_graceful_on_error():
    """_get_badges retourne une liste vide si Moodle leve une exception."""
    from src.modules.moodle.repositories.moodle_repository import MoodleAPIException

    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException())
    assert await _svc(repo)._get_badges(42) == []


async def test_get_user_preferences_returns_list():
    """_get_user_preferences parse correctement la reponse Moodle."""
    repo = _repo(
        return_value={
            "preferences": [
                {"name": "lang", "value": "fr"},
                {"name": "timezone", "value": "Europe/Paris"},
            ]
        }
    )
    prefs = await _svc(repo)._get_user_preferences(42)
    assert len(prefs) == 2
    assert prefs[0].name == "lang"
    assert prefs[0].value == "fr"


async def test_get_user_preferences_graceful_on_error():
    """_get_user_preferences retourne une liste vide si Moodle leve une exception."""
    from src.modules.moodle.repositories.moodle_repository import MoodleAPIException

    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException())
    assert await _svc(repo)._get_user_preferences(42) == []


async def test_learner_profile_includes_badges_and_preferences():
    """get_learner_profile integre badges et preferences dans le profil."""
    repo = MagicMock()
    repo.call = AsyncMock(
        side_effect=[
            [{"id": 7, "username": "alice", "fullname": "Alice", "email": "a@t.com"}],
            [],
            {"grades": []},
            {"badges": [{"id": 5, "name": "Expert"}]},
            {"preferences": [{"name": "lang", "value": "fr"}]},
        ]
    )
    profile = await _svc(repo).get_learner_profile(7)
    assert len(profile.badges) == 1
    assert profile.badges[0].name == "Expert"
    assert len(profile.preferences) == 1
    assert profile.preferences[0].value == "fr"


# ============================================================================
# _get_calendar_events
# ============================================================================


async def test_get_calendar_events_success():
    """_get_calendar_events parse correctement la reponse Moodle."""
    repo = _repo(
        return_value={
            "events": [
                {
                    "id": 10,
                    "name": "Quiz: Introduction",
                    "description": "<p>Deadline quiz</p>",
                    "courseid": 101,
                    "timestart": 1700100000,
                    "timeduration": 0,
                    "modulename": "quiz",
                    "instance": 5,
                }
            ]
        }
    )
    events = await _svc(repo)._get_calendar_events(101)
    assert len(events) == 1
    assert events[0].name == "Quiz: Introduction"
    assert events[0].modulename == "quiz"
    assert events[0].description == "Deadline quiz"
    assert events[0].courseid == 101


async def test_get_calendar_events_list_response():
    """_get_calendar_events accepte une reponse en liste directe."""
    repo = _repo(
        return_value=[
            {"id": 11, "name": "Devoir", "timestart": 1700200000, "timeduration": 0}
        ]
    )
    events = await _svc(repo)._get_calendar_events(101)
    assert len(events) == 1
    assert events[0].id == 11


async def test_get_calendar_events_graceful_on_error():
    """_get_calendar_events retourne une liste vide si Moodle echoue."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Non autorise"))
    assert await _svc(repo)._get_calendar_events(101) == []


async def test_get_calendar_events_empty():
    """_get_calendar_events retourne une liste vide si aucun evenement."""
    repo = _repo(return_value={"events": []})
    assert await _svc(repo)._get_calendar_events(101) == []


# ============================================================================
# _get_forum_posts
# ============================================================================


async def test_get_forum_posts_success():
    """_get_forum_posts parse correctement la reponse Moodle."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=[
        # mod_forum_get_forums_by_courses
        [{"cmid": 10, "id": 1, "name": "Forum"}],
        # mod_forum_get_discussion_posts_by_userid (cmid=10)
        {
            "posts": [
                {
                    "id": 20,
                    "subject": "Question sur le cours",
                    "message": "<p>Est-ce que...</p>",
                    "created": 1700000000,
                    "discussion": 7,
                }
            ]
        },
    ])
    posts = await _svc(repo)._get_forum_posts(5, 101)
    assert len(posts) == 1
    assert posts[0].subject == "Question sur le cours"
    assert posts[0].message == "Est-ce que..."
    assert posts[0].courseid == 101
    assert posts[0].discussion_id == 7


async def test_get_forum_posts_list_response():
    """_get_forum_posts accepte une reponse en liste directe pour les posts."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=[
        [{"cmid": 10}],
        [{"id": 21, "subject": "Aide", "created": 1700000001, "discussion": 8}],
    ])
    posts = await _svc(repo)._get_forum_posts(5, 101)
    assert len(posts) == 1
    assert posts[0].id == 21


async def test_get_forum_posts_graceful_on_error():
    """_get_forum_posts retourne une liste vide si la recuperation des forums echoue."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Non autorise"))
    assert await _svc(repo)._get_forum_posts(5, 101) == []


async def test_get_forum_posts_empty():
    """_get_forum_posts retourne une liste vide si aucun post."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=[
        [{"cmid": 10}],
        {"posts": []},
    ])
    assert await _svc(repo)._get_forum_posts(5, 101) == []


async def test_get_forum_posts_no_forums():
    """_get_forum_posts retourne une liste vide si le cours n'a pas de forum."""
    repo = _repo(return_value=[])
    assert await _svc(repo)._get_forum_posts(5, 101) == []


# ============================================================================
# get_quiz_attempt_review
# ============================================================================


async def test_get_quiz_attempt_review_success():
    """get_quiz_attempt_review parse correctement la reponse Moodle."""
    repo = _repo(
        return_value={
            "attempt": {"id": 1, "quiz": 5},
            "questions": [
                {
                    "slot": 1,
                    "html": "<p>Quelle est la capitale ?</p>",
                    "responseSummary": "Paris",
                    "state": "gradedright",
                    "mark": "1.0",
                    "maxmark": "1.0",
                },
                {
                    "slot": 2,
                    "html": "<p>Combien font 2+2 ?</p>",
                    "responseSummary": "5",
                    "state": "gradedwrong",
                    "mark": "0.0",
                    "maxmark": "1.0",
                },
            ],
        }
    )
    review = await _svc(repo).get_quiz_attempt_review(1)
    assert review.attemptid == 1
    assert review.quizid == 5
    assert len(review.questions) == 2
    assert review.questions[0].correct is True
    assert review.questions[0].mark == 1.0
    assert review.questions[1].correct is False
    assert review.questions[1].student_answer == "5"


async def test_get_quiz_attempt_review_partial_state():
    """_state_to_correct retourne None pour les etats non binaires."""
    assert _state_to_correct("gradedright") is True
    assert _state_to_correct("gradedwrong") is False
    assert _state_to_correct("gradedpartial") is None
    assert _state_to_correct("notanswered") is None
    assert _state_to_correct(None) is None


async def test_get_quiz_attempt_review_empty_questions():
    """get_quiz_attempt_review gere les tentatives sans questions."""
    repo = _repo(return_value={"attempt": {"id": 3, "quiz": 9}, "questions": []})
    review = await _svc(repo).get_quiz_attempt_review(3)
    assert review.quizid == 9
    assert review.questions == []


async def test_get_quiz_attempt_review_propagates_exception():
    """get_quiz_attempt_review propage l'exception MoodleAPIException."""
    repo = MagicMock()
    repo.call = AsyncMock(side_effect=MoodleAPIException("Tentative introuvable"))
    with pytest.raises(MoodleAPIException):
        await _svc(repo).get_quiz_attempt_review(999)


# ============================================================================
# LearnerProfile integre calendar_events et forum_posts
# ============================================================================


async def test_learner_profile_includes_calendar_and_forum():
    """get_learner_profile integre calendar_events et forum_posts via _get_course_detail."""
    repo = MagicMock()
    repo.call = AsyncMock(
        side_effect=[
            # _get_user
            [{"id": 7, "username": "alice", "fullname": "Alice", "email": "a@t.com"}],
            # _get_courses : un cours pour declencher _get_course_detail
            [{"id": 101, "fullname": "Python", "shortname": "PY"}],
            # _get_overview_grades
            {"grades": []},
            # _get_badges
            {"badges": []},
            # _get_user_preferences
            {"preferences": []},
            # --- _get_course_detail pour cours 101 ---
            # _get_grade_items
            {"usergrades": [{"gradeitems": []}]},
            # _get_completion
            {"statuses": []},
            # _get_quiz_attempts
            {"quizzes": []},
            # _get_assignments
            {"courses": []},
            # _get_course_resources
            [],
            # _get_calendar_events
            {
                "events": [
                    {
                        "id": 10,
                        "name": "Quiz deadline",
                        "timestart": 1700100000,
                        "timeduration": 0,
                    }
                ]
            },
            # _get_forum_posts : get_forums puis get_posts
            [{"cmid": 10, "id": 1}],
            {
                "posts": [
                    {
                        "id": 20,
                        "subject": "Ma question",
                        "created": 1700000000,
                        "discussion": 3,
                    }
                ]
            },
        ]
    )
    profile = await _svc(repo).get_learner_profile(7)
    assert len(profile.calendar_events) == 1
    assert profile.calendar_events[0].name == "Quiz deadline"
    assert len(profile.forum_posts) == 1
    assert profile.forum_posts[0].subject == "Ma question"
    assert profile.forum_posts[0].courseid == 101


# ============================================================================
# _classify_level / _compute_learner_level
# ============================================================================


def test_classify_level_none_returns_unknown():
    assert _classify_level(None) == LearnerLevel.UNKNOWN


def test_classify_level_advanced():
    assert _classify_level(0.85) == LearnerLevel.ADVANCED
    assert _classify_level(0.70) == LearnerLevel.ADVANCED


def test_classify_level_intermediate():
    assert _classify_level(0.55) == LearnerLevel.INTERMEDIATE
    assert _classify_level(0.40) == LearnerLevel.INTERMEDIATE


def test_classify_level_beginner():
    assert _classify_level(0.39) == LearnerLevel.BEGINNER
    assert _classify_level(0.0) == LearnerLevel.BEGINNER


def test_compute_learner_level_no_data_returns_unknown():
    level, by_course = _compute_learner_level(courses=[], grades_by_course={}, completion_by_course={})
    assert level == LearnerLevel.UNKNOWN
    assert by_course == {}


def test_compute_learner_level_course_without_signals_is_unknown():
    courses = [MoodleCourse(id=1, fullname="C", shortname="C", progress=None)]
    level, by_course = _compute_learner_level(
        courses=courses,
        grades_by_course={},
        completion_by_course={},
    )
    assert level == LearnerLevel.UNKNOWN
    assert by_course == {1: LearnerLevel.UNKNOWN}


def test_compute_learner_level_high_grades_advanced():
    courses = [MoodleCourse(id=1, fullname="C", shortname="C", progress=90.0)]
    grades = {
        1: [
            MoodleGradeItem(itemname="Q1", graderaw=18.0, grademax=20.0),
            MoodleGradeItem(itemname="Q2", graderaw=16.0, grademax=20.0),
        ]
    }
    completions = {
        1: [
            MoodleCompletion(cmid=1, modname="quiz", state=1),
            MoodleCompletion(cmid=2, modname="assign", state=1),
        ]
    }
    level, by_course = _compute_learner_level(
        courses=courses, grades_by_course=grades, completion_by_course=completions
    )
    assert level == LearnerLevel.ADVANCED
    assert by_course[1] == LearnerLevel.ADVANCED


def test_compute_learner_level_low_grades_beginner():
    courses = [MoodleCourse(id=1, fullname="C", shortname="C", progress=15.0)]
    grades = {
        1: [
            MoodleGradeItem(itemname="Q1", graderaw=4.0, grademax=20.0),
            MoodleGradeItem(itemname="Q2", graderaw=6.0, grademax=20.0),
        ]
    }
    completions = {
        1: [
            MoodleCompletion(cmid=1, modname="quiz", state=0),
            MoodleCompletion(cmid=2, modname="assign", state=0),
        ]
    }
    level, by_course = _compute_learner_level(
        courses=courses, grades_by_course=grades, completion_by_course=completions
    )
    assert level == LearnerLevel.BEGINNER
    assert by_course[1] == LearnerLevel.BEGINNER


def test_compute_learner_level_mixed_grades_intermediate():
    courses = [MoodleCourse(id=1, fullname="C", shortname="C", progress=50.0)]
    grades = {
        1: [
            MoodleGradeItem(itemname="Q1", graderaw=10.0, grademax=20.0),
            MoodleGradeItem(itemname="Q2", graderaw=12.0, grademax=20.0),
        ]
    }
    completions = {1: [MoodleCompletion(cmid=1, modname="quiz", state=1)]}
    level, by_course = _compute_learner_level(
        courses=courses, grades_by_course=grades, completion_by_course=completions
    )
    assert level == LearnerLevel.INTERMEDIATE
    assert by_course[1] == LearnerLevel.INTERMEDIATE


def test_compute_learner_level_distinct_per_course():
    courses = [
        MoodleCourse(id=1, fullname="Strong", shortname="S", progress=95.0),
        MoodleCourse(id=2, fullname="Weak", shortname="W", progress=10.0),
    ]
    grades = {
        1: [MoodleGradeItem(itemname="Q1", graderaw=19.0, grademax=20.0)],
        2: [MoodleGradeItem(itemname="Q1", graderaw=3.0, grademax=20.0)],
    }
    completions = {
        1: [MoodleCompletion(cmid=1, modname="quiz", state=1)],
        2: [MoodleCompletion(cmid=2, modname="quiz", state=0)],
    }
    _, by_course = _compute_learner_level(
        courses=courses, grades_by_course=grades, completion_by_course=completions
    )
    assert by_course[1] == LearnerLevel.ADVANCED
    assert by_course[2] == LearnerLevel.BEGINNER


def test_compute_learner_level_grades_only_no_progress_no_completion():
    courses = [MoodleCourse(id=1, fullname="C", shortname="C", progress=None)]
    grades = {1: [MoodleGradeItem(itemname="Q1", graderaw=18.0, grademax=20.0)]}
    level, by_course = _compute_learner_level(
        courses=courses, grades_by_course=grades, completion_by_course={}
    )
    # Avec uniquement les notes (poids renormalise a 1.0), on doit obtenir ADVANCED
    assert level == LearnerLevel.ADVANCED
    assert by_course[1] == LearnerLevel.ADVANCED


# ============================================================================
# get_related_profiles — formateur sans fallback sur profil propre
# ============================================================================


async def test_get_related_profiles_no_children_returns_none():
    """Sans apprenants lies, get_related_profiles retourne None."""
    repo = _repo()
    repo.get_related_learners = AsyncMock(return_value=[])
    svc = _svc(repo)
    result = await svc.get_related_profiles(99)
    assert result is None


async def test_get_related_profiles_with_children():
    """Avec des apprenants lies, retourne leurs profils."""
    repo = _repo()
    repo.get_related_learners = AsyncMock(return_value=[{"id": 10}])
    svc = _svc(repo)
    # Mock _build_learner_profile pour eviter les appels WS
    svc._build_learner_profile = AsyncMock(
        return_value=LearnerProfile(
            moodle_userid=10, username="child", fullname="Child", email="c@x.com"
        )
    )
    result = await svc.get_related_profiles(99)
    assert result is not None
    assert len(result) == 1
    assert result[0].moodle_userid == 10


async def test_get_related_profiles_api_error_returns_none():
    """En cas d'erreur WS, retourne None au lieu de construire le profil propre."""
    repo = _repo()
    repo.get_related_learners = AsyncMock(
        side_effect=MoodleAPIException(detail="WS error")
    )
    svc = _svc(repo)
    result = await svc.get_related_profiles(99)
    assert result is None


# ============================================================================
# get_enrolled_learner_ids — liste des apprenants inscrits (formateurs exclus)
# ============================================================================


async def test_get_enrolled_learner_ids_filters_trainers():
    """Les formateurs sont exclus, seuls les apprenants sont retournes."""
    repo = _repo()
    repo.call = AsyncMock(side_effect=[
        # core_course_get_courses
        [{"id": 2, "fullname": "Cours A"}],
        # core_enrol_get_enrolled_users pour le cours 2
        [
            {"id": 10, "roles": [{"shortname": "student"}]},
            {"id": 20, "roles": [{"shortname": "editingteacher"}]},
            {"id": 30, "roles": [{"shortname": "student"}]},
        ],
    ])
    svc = _svc(repo)
    result = await svc.get_enrolled_learner_ids()
    assert result == {10, 30}


async def test_get_enrolled_learner_ids_excludes_site_course():
    """Le cours site (id=1) est ignore."""
    repo = _repo()
    repo.call = AsyncMock(side_effect=[
        [{"id": 1, "fullname": "Site"}, {"id": 3, "fullname": "Cours B"}],
        # core_enrol_get_enrolled_users pour le cours 3 uniquement
        [{"id": 42, "roles": [{"shortname": "student"}]}],
    ])
    svc = _svc(repo)
    result = await svc.get_enrolled_learner_ids()
    assert result == {42}
    # 2 appels : get_courses + enrolled pour cours 3 (pas pour cours 1)
    assert repo.call.await_count == 2


async def test_get_enrolled_learner_ids_empty_courses():
    """Sans cours, retourne un set vide."""
    repo = _repo()
    repo.call = AsyncMock(return_value=[])
    svc = _svc(repo)
    result = await svc.get_enrolled_learner_ids()
    assert result == set()


async def test_get_enrolled_learner_ids_api_error_on_course():
    """Erreur WS sur un cours : le cours est ignore, les autres sont traites."""
    repo = _repo()
    repo.call = AsyncMock(side_effect=[
        [{"id": 2, "fullname": "A"}, {"id": 3, "fullname": "B"}],
        MoodleAPIException(detail="WS error"),  # cours 2 echoue
        [{"id": 50, "roles": [{"shortname": "student"}]}],  # cours 3 ok
    ])
    svc = _svc(repo)
    result = await svc.get_enrolled_learner_ids()
    assert result == {50}
