"""Couche de logique metier pour le domaine Moodle."""

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from ....exceptions import MoodleAPIException
from ..models import (
    LearnerLevel,
    LearnerProfile,
    MoodleActivityEvent,
    MoodleAssignment,
    MoodleBadge,
    MoodleCalendarEvent,
    MoodleCompletion,
    MoodleCourse,
    MoodleCourseGrade,
    MoodleForumPost,
    MoodleGradeItem,
    MoodleQuizAttempt,
    MoodleQuizQuestion,
    MoodleQuizReview,
    MoodleResource,
    MoodleUserPreference,
    MoodleUserRole,
)
from ..repositories import MoodleRepository

logger = logging.getLogger(__name__)

_INACTIVITY_THRESHOLD_DAYS = 7
_DUE_SOON_THRESHOLD_DAYS = 3
_INCOMPLETE_MIN_COUNT = 3
_INCOMPLETE_MIN_RATIO = 0.5

# Ponderation du score de niveau apprenant (somme = 1.0)
_LEVEL_WEIGHT_GRADES = 0.5
_LEVEL_WEIGHT_PROGRESS = 0.3
_LEVEL_WEIGHT_COMPLETION = 0.2
# Seuils de classification
_LEVEL_THRESHOLD_INTERMEDIATE = 0.40
_LEVEL_THRESHOLD_ADVANCED = 0.70
# Modules a ignorer dans l'index des ressources (navigation interne, labels vides)
_IGNORED_MODNAMES = {"label"}


_CACHE_KEY_PREFIX = "moodle:learner:"

_TRAINER_ROLE_SHORTNAMES = frozenset({
    "editingteacher", "teacher", "manager", "coursecreator",
    "formateur", "enseignant", "trainer",
})


class MoodleService:
    """Orchestre les appels Moodle WS pour construire un LearnerProfile complet."""

    def __init__(
        self,
        repository: MoodleRepository,
        redis: aioredis.Redis | None = None,
        cache_ttl: int = 300,
    ) -> None:
        self.repository = repository
        self._redis = redis
        self._cache_ttl = cache_ttl

    # -------------------------------------------------------------------------
    # API publique
    # -------------------------------------------------------------------------

    async def get_site_info(self) -> dict[str, Any]:
        """Retourne les infos du site Moodle (version, url, username du token)."""
        return await self.repository.call("core_webservice_get_site_info")

    async def get_learner_profile(self, moodle_userid: int) -> LearnerProfile:
        """Retourne le profil complet — cache Redis avec validation delta sync."""
        cache_key = f"{_CACHE_KEY_PREFIX}{moodle_userid}"

        if self._redis and self._cache_ttl > 0:
            raw = await self._redis.get(cache_key)
            if raw:
                try:
                    entry = json.loads(raw)
                    profile = LearnerProfile.model_validate(entry["profile"])
                    has_updates = await self._courses_have_updates(
                        profile.courses, entry["cached_at"]
                    )
                    if not has_updates:
                        logger.debug("Cache valide userid=%d", moodle_userid)
                        return profile
                    logger.debug(
                        "Delta sync: mise a jour detectee userid=%d", moodle_userid
                    )
                except Exception:
                    logger.warning("Cache Redis corrompu userid=%d — reconstruction", moodle_userid)
                await self._redis.delete(cache_key)

        profile = await self._build_learner_profile(moodle_userid)

        if self._redis and self._cache_ttl > 0:
            entry = json.dumps(
                {
                    "profile": profile.model_dump(),
                    "cached_at": int(datetime.now(UTC).timestamp()),
                }
            )
            await self._redis.setex(cache_key, self._cache_ttl, entry)

        return profile

    async def get_chat_profiles(self, moodle_userid: int) -> list[LearnerProfile]:
        """Retourne les profils a injecter dans le chat.

        Si l'utilisateur a des apprenants lies (ex: enfants), retourne les profils
        des apprenants lies. Sinon retourne le profil direct de l'utilisateur.
        """
        try:
            related = await self.repository.get_related_learners(moodle_userid)
        except MoodleAPIException as exc:
            logger.warning("related_learners userid=%d : %s", moodle_userid, exc.detail)
            related = []

        childids: list[int] = []
        for item in related:
            childid = item.get("id")
            if isinstance(childid, int) and childid > 0 and childid != moodle_userid:
                childids.append(childid)

        if not childids:
            return [await self.get_learner_profile(moodle_userid)]

        results = await asyncio.gather(
            *[self.get_learner_profile(childid) for childid in childids],
            return_exceptions=True,
        )

        profiles: list[LearnerProfile] = []
        for childid, result in zip(childids, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("profil enfant indisponible userid=%d : %s", childid, result)
                continue
            profiles.append(result)

        if profiles:
            return profiles

        return [await self.get_learner_profile(moodle_userid)]

    async def get_related_profiles(
        self, moodle_userid: int
    ) -> list[LearnerProfile] | None:
        """Retourne les profils des apprenants lies (enfants) sans fallback.

        Contrairement a get_chat_profiles, ne construit PAS le profil propre
        de l'utilisateur si aucun apprenant lie n'est trouve. Retourne None
        dans ce cas. Utilise pour les formateurs afin d'eviter de calculer
        un niveau apprenant sur leur propre profil.
        """
        try:
            related = await self.repository.get_related_learners(moodle_userid)
        except MoodleAPIException as exc:
            logger.warning("related_learners userid=%d : %s", moodle_userid, exc.detail)
            return None

        childids: list[int] = []
        for item in related:
            childid = item.get("id")
            if isinstance(childid, int) and childid > 0 and childid != moodle_userid:
                childids.append(childid)

        if not childids:
            return None

        results = await asyncio.gather(
            *[self.get_learner_profile(childid) for childid in childids],
            return_exceptions=True,
        )

        profiles: list[LearnerProfile] = []
        for childid, result in zip(childids, results, strict=False):
            if isinstance(result, Exception):
                logger.warning("profil enfant indisponible userid=%d : %s", childid, result)
                continue
            profiles.append(result)

        return profiles or None

    async def get_user_role(self, moodle_userid: int) -> MoodleUserRole:
        """Determine le role pedagogique d'un utilisateur depuis ses roles systeme Moodle.

        Inspecte le champ 'roles' retourne par core_user_get_users_by_field (token admin).
        Retourne TRAINER si un shortname formateur est reconnu, STUDENT sinon.
        En cas d'erreur WS : retourne UNKNOWN (echec silencieux).
        """
        try:
            user_data = await self._get_user(moodle_userid)
        except MoodleAPIException:
            return MoodleUserRole.UNKNOWN
        roles = user_data.get("roles", [])
        for role in roles if isinstance(roles, list) else []:
            if str(role.get("shortname", "")).lower() in _TRAINER_ROLE_SHORTNAMES:
                return MoodleUserRole.TRAINER
        return MoodleUserRole.STUDENT

    async def get_enrolled_learner_ids(self) -> set[int]:
        """Retourne les IDs des apprenants inscrits (formateurs exclus).

        Recupere tous les cours du site puis liste les inscrits par cours
        via core_enrol_get_enrolled_users. Exclut les utilisateurs dont le
        role Moodle correspond a un formateur (_TRAINER_ROLE_SHORTNAMES).

        Resultat cache en Redis (cle moodle:enrolled_learner_ids) ; ce cache
        est invalide par le cron refresh dans main.py.
        """
        cache_key = "moodle:enrolled_learner_ids"
        if self._redis:
            raw = await self._redis.get(cache_key)
            if raw:
                return set(json.loads(raw))

        courses_raw = await self.repository.call("core_course_get_courses")
        course_ids = [
            c["id"]
            for c in (courses_raw if isinstance(courses_raw, list) else [])
            if isinstance(c.get("id"), int) and c["id"] != 1
        ]

        learner_ids: set[int] = set()
        for cid in course_ids:
            try:
                enrolled = await self.repository.call(
                    "core_enrol_get_enrolled_users", courseid=str(cid)
                )
            except MoodleAPIException as exc:
                logger.warning("enrolled_users cours=%d : %s", cid, exc.detail)
                continue

            for user in enrolled if isinstance(enrolled, list) else []:
                uid = user.get("id")
                if not isinstance(uid, int) or uid <= 0:
                    continue
                roles = user.get("roles", [])
                is_trainer = any(
                    str(r.get("shortname", "")).lower() in _TRAINER_ROLE_SHORTNAMES
                    for r in (roles if isinstance(roles, list) else [])
                )
                if not is_trainer:
                    learner_ids.add(uid)

        if self._redis:
            await self._redis.setex(
                cache_key, self._cache_ttl, json.dumps(list(learner_ids))
            )

        return learner_ids

    async def invalidate_learner_cache(self, moodle_userid: int) -> None:
        """Supprime le cache Redis du profil apprenant."""
        if self._redis:
            await self._redis.delete(f"{_CACHE_KEY_PREFIX}{moodle_userid}")

    async def _courses_have_updates(
        self, courses: list[MoodleCourse], since_ts: int
    ) -> bool:
        """Retourne True si au moins un cours a ete modifie depuis since_ts."""
        if not courses:
            return False
        results = await asyncio.gather(
            *[self._course_has_updates(c.id, since_ts) for c in courses],
            return_exceptions=True,
        )
        return any(r is True for r in results)

    async def _course_has_updates(self, courseid: int, since_ts: int) -> bool:
        """Retourne True si le cours a des composants modifies depuis since_ts."""
        try:
            raw = await self.repository.call(
                "core_course_get_updates_since",
                courseid=str(courseid),
                since=str(since_ts),
            )
        except MoodleAPIException as exc:
            logger.warning("delta_sync cours=%d : %s", courseid, exc.detail)
            return True  # Forcer le refresh en cas d'erreur
        return bool(isinstance(raw, dict) and raw.get("instances"))

    async def _build_learner_profile(self, moodle_userid: int) -> LearnerProfile:
        """Construit le profil complet en orchestrant les WS Moodle (sans cache)."""
        user_data, courses, overview_grades, badges, preferences = await asyncio.gather(
            self._get_user(moodle_userid),
            self._get_courses(moodle_userid),
            self._get_overview_grades(moodle_userid),
            self._get_badges(moodle_userid),
            self._get_user_preferences(moodle_userid),
        )

        per_course_results = await asyncio.gather(
            *[self._get_course_detail(moodle_userid, course) for course in courses],
            return_exceptions=True,
        )

        grades_by_course: dict[int, list[MoodleGradeItem]] = {}
        completion_by_course: dict[int, list[MoodleCompletion]] = {}
        quiz_attempts: list[MoodleQuizAttempt] = []
        assignments: list[MoodleAssignment] = []
        resources_by_course: dict[int, list[MoodleResource]] = {}
        calendar_events: list[MoodleCalendarEvent] = []
        forum_posts: list[MoodleForumPost] = []

        for result in per_course_results:
            if isinstance(result, Exception):
                logger.warning("Erreur detail cours : %s", result)
                continue
            (
                course_id,
                grade_items,
                completions,
                attempts,
                assigns,
                resources,
                cal_events,
                f_posts,
            ) = result
            grades_by_course[course_id] = grade_items
            completion_by_course[course_id] = completions
            quiz_attempts.extend(attempts)
            assignments.extend(assigns)
            resources_by_course[course_id] = resources
            calendar_events.extend(cal_events)
            forum_posts.extend(f_posts)

        activity_log = _build_activity_log(
            courses=courses,
            quiz_attempts=quiz_attempts,
            assignments=assignments,
            completion_by_course=completion_by_course,
        )

        level, level_by_course = _compute_learner_level(
            courses=courses,
            grades_by_course=grades_by_course,
            completion_by_course=completion_by_course,
        )

        return LearnerProfile(
            moodle_userid=user_data.get("id", 0),
            username=user_data.get("username", ""),
            fullname=user_data.get("fullname", ""),
            email=user_data.get("email", ""),
            courses=courses,
            overview_grades=overview_grades,
            grades_by_course=grades_by_course,
            completion_by_course=completion_by_course,
            quiz_attempts=quiz_attempts,
            assignments=assignments,
            activity_log=activity_log,
            resources_by_course=resources_by_course,
            badges=badges,
            preferences=preferences,
            calendar_events=calendar_events,
            forum_posts=forum_posts,
            level=level,
            level_by_course=level_by_course,
        )

    # -------------------------------------------------------------------------
    # Methodes privees — niveau utilisateur
    # -------------------------------------------------------------------------

    async def _get_user(self, userid: int) -> dict[str, Any]:
        """Retourne le profil brut d'un utilisateur Moodle."""
        result = await self.repository.call(
            "core_user_get_users_by_field",
            **{"field": "id", "values[0]": str(userid)},
        )
        users: list[dict[str, Any]] = result if isinstance(result, list) else []
        if not users:
            raise MoodleAPIException(
                f"Utilisateur Moodle introuvable (userid={userid})"
            )
        return users[0]

    async def _get_courses(self, userid: int) -> list[MoodleCourse]:
        """Retourne les cours de l'apprenant avec le pourcentage de progression."""
        raw: list[dict[str, Any]] = await self.repository.call(
            "core_enrol_get_users_courses", userid=str(userid)
        )
        return [
            MoodleCourse(
                id=c.get("id", 0),
                fullname=c.get("fullname", ""),
                shortname=c.get("shortname", ""),
                progress=c.get("progress"),
                lastaccess=c.get("lastaccess") or None,
            )
            for c in (raw if isinstance(raw, list) else [])
        ]

    async def _get_overview_grades(self, userid: int) -> list[MoodleCourseGrade]:
        """Retourne la note finale de l'apprenant pour chaque cours."""
        try:
            raw = await self.repository.call(
                "gradereport_overview_get_course_grades", userid=str(userid)
            )
        except MoodleAPIException as exc:
            logger.warning("overview_grades userid=%d : %s", userid, exc.detail)
            return []
        grades: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            grades = raw.get("grades", [])
        elif isinstance(raw, list):
            grades = raw
        return [
            MoodleCourseGrade(
                courseid=g.get("courseid", 0),
                grade=g.get("grade", "-"),
                rawgrade=_to_float(g.get("rawgrade")),
            )
            for g in grades
        ]

    async def _get_badges(self, userid: int) -> list[MoodleBadge]:
        """Badges obtenus par l'apprenant (tous cours confondus)."""
        try:
            raw = await self.repository.call(
                "core_badges_get_user_badges", userid=str(userid), courseid="0"
            )
        except MoodleAPIException as exc:
            logger.warning("badges userid=%d : %s", userid, exc.detail)
            return []
        badges: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            badges = raw.get("badges", [])
        elif isinstance(raw, list):
            badges = raw
        return [
            MoodleBadge(
                id=b.get("id", 0),
                name=b.get("name", ""),
                description=b.get("description") or None,
                dateissued=b.get("dateissued") or None,
                badgeurl=b.get("badgeurl") or None,
            )
            for b in badges
        ]

    async def _get_user_preferences(self, userid: int) -> list[MoodleUserPreference]:
        """Preferences Moodle de l'apprenant (langue, fuseau horaire...)."""
        try:
            raw = await self.repository.call(
                "core_user_get_user_preferences", userid=str(userid), name=""
            )
        except MoodleAPIException as exc:
            logger.warning("preferences userid=%d : %s", userid, exc.detail)
            return []
        prefs: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            prefs = raw.get("preferences", [])
        elif isinstance(raw, list):
            prefs = raw
        return [
            MoodleUserPreference(name=p["name"], value=str(p.get("value", "")))
            for p in prefs
            if p.get("name")
        ]

    # -------------------------------------------------------------------------
    # Methodes privees — niveau cours
    # -------------------------------------------------------------------------

    async def _get_course_detail(
        self, userid: int, course: MoodleCourse
    ) -> tuple[
        int,
        list[MoodleGradeItem],
        list[MoodleCompletion],
        list[MoodleQuizAttempt],
        list[MoodleAssignment],
        list[MoodleResource],
        list[MoodleCalendarEvent],
        list[MoodleForumPost],
    ]:
        """Recupere toutes les donnees d'un cours pour un apprenant."""
        (
            grade_items,
            completions,
            attempts,
            assigns,
            resources,
            cal_events,
            f_posts,
        ) = await asyncio.gather(
            self._get_grade_items(userid, course.id),
            self._get_completion(userid, course.id),
            self._get_quiz_attempts(userid, course.id),
            self._get_assignments(userid, course.id),
            self._get_course_resources(course.id),
            self._get_calendar_events(course.id),
            self._get_forum_posts(userid, course.id),
        )
        return (
            course.id,
            grade_items,
            completions,
            attempts,
            assigns,
            resources,
            cal_events,
            f_posts,
        )

    async def _get_grade_items(
        self, userid: int, courseid: int
    ) -> list[MoodleGradeItem]:
        """Notes par activite pour un cours."""
        try:
            raw = await self.repository.call(
                "gradereport_user_get_grade_items",
                courseid=str(courseid),
                userid=str(userid),
            )
        except MoodleAPIException as exc:
            logger.warning("grade_items cours=%d : %s", courseid, exc.detail)
            return []
        items: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            usergrades = raw.get("usergrades", [])
            items = usergrades[0].get("gradeitems", []) if usergrades else []
        elif isinstance(raw, list):
            items = raw
        return [
            MoodleGradeItem(
                itemname=i.get("itemname"),
                itemmodule=i.get("itemmodule"),
                graderaw=_to_float(i.get("graderaw")),
                grademin=_to_float(i.get("grademin")),
                grademax=_to_float(i.get("grademax")),
                gradeformatted=i.get("gradeformatted"),
                feedback=i.get("feedback") or None,
            )
            for i in items
        ]

    async def _get_completion(
        self, userid: int, courseid: int
    ) -> list[MoodleCompletion]:
        """Etat de completion de chaque activite pour un cours."""
        try:
            raw = await self.repository.call(
                "core_completion_get_activities_completion_status",
                courseid=str(courseid),
                userid=str(userid),
            )
        except MoodleAPIException as exc:
            logger.warning("completion cours=%d : %s", courseid, exc.detail)
            return []
        statuses: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            statuses = raw.get("statuses", [])
        elif isinstance(raw, list):
            statuses = raw
        return [
            MoodleCompletion(
                cmid=s.get("cmid", 0),
                modname=s.get("modname", ""),
                state=s.get("state", 0),
                timecompleted=s.get("timecompleted") or None,
            )
            for s in statuses
        ]

    async def _get_quiz_attempts(
        self, userid: int, courseid: int
    ) -> list[MoodleQuizAttempt]:
        """Tentatives quiz pour un cours."""
        try:
            raw = await self.repository.call(
                "mod_quiz_get_quizzes_by_courses",
                **{"courseids[0]": str(courseid)},
            )
        except MoodleAPIException as exc:
            logger.warning("quizzes cours=%d : %s", courseid, exc.detail)
            return []

        quizzes: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            quizzes = raw.get("quizzes", [])
        elif isinstance(raw, list):
            quizzes = raw

        all_attempts: list[MoodleQuizAttempt] = []
        results = await asyncio.gather(
            *[self._get_attempts_for_quiz(userid, q["id"]) for q in quizzes if q.get("id")],
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                logger.warning("attempts quiz : %s", res)
                continue
            all_attempts.extend(res)
        return all_attempts

    async def _get_attempts_for_quiz(
        self, userid: int, quizid: int
    ) -> list[MoodleQuizAttempt]:
        """Tentatives d'un apprenant pour un quiz specifique."""
        try:
            raw = await self.repository.call(
                "mod_quiz_get_user_quiz_attempts",
                quizid=str(quizid),
                userid=str(userid),
                status="all",
            )
        except MoodleAPIException as exc:
            logger.warning("user_attempts quiz=%d : %s", quizid, exc.detail)
            return []
        attempts: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            attempts = raw.get("attempts", [])
        elif isinstance(raw, list):
            attempts = raw
        return [
            MoodleQuizAttempt(
                quizid=quizid,
                attempt_number=a.get("attempt", 1),
                state=a.get("state", "unknown"),
                sumgrades=_to_float(a.get("sumgrades")),
                timestart=a.get("timestart") or None,
                timefinish=a.get("timefinish") or None,
            )
            for a in attempts
        ]

    async def _get_assignments(
        self, userid: int, courseid: int
    ) -> list[MoodleAssignment]:
        """Devoirs avec statut de rendu et note pour un cours."""
        try:
            raw = await self.repository.call(
                "mod_assign_get_assignments",
                **{"courseids[0]": str(courseid)},
            )
        except MoodleAPIException as exc:
            logger.warning("assignments cours=%d : %s", courseid, exc.detail)
            return []

        courses_data: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            courses_data = raw.get("courses", [])
        elif isinstance(raw, list):
            courses_data = raw

        assigns: list[dict[str, Any]] = []
        for c in courses_data:
            assigns.extend(c.get("assignments", []))

        results = await asyncio.gather(
            *[self._get_submission_status(userid, a) for a in assigns],
            return_exceptions=True,
        )
        enriched: list[MoodleAssignment] = []
        for res in results:
            if isinstance(res, Exception):
                logger.warning("submission_status : %s", res)
                continue
            enriched.append(res)
        return enriched

    async def _get_submission_status(
        self, userid: int, assign: dict[str, Any]
    ) -> MoodleAssignment:
        """Recupere le statut de rendu et la note pour un devoir."""
        assignid: int = assign.get("id", 0)
        if not assignid:
            return MoodleAssignment(name=assign.get("name", ""), assignid=0)
        try:
            raw = await self.repository.call(
                "mod_assign_get_submission_status",
                assignid=str(assignid),
                userid=str(userid),
            )
        except MoodleAPIException:
            return MoodleAssignment(
                assignid=assignid,
                name=assign.get("name", ""),
                duedate=assign.get("duedate") or None,
            )

        submission: dict[str, Any] = {}
        grading: dict[str, Any] = {}
        if isinstance(raw, dict):
            last_attempt = raw.get("lastattempt") or {}
            submission = last_attempt.get("submission", {}) if isinstance(last_attempt, dict) else {}
            feedback = raw.get("feedback") or {}
            grading = feedback.get("gradefordisplay", {}) if isinstance(feedback, dict) else {}

        status = submission.get("status") if isinstance(submission, dict) else None
        gradingstatus = (
            (raw.get("lastattempt") or {}).get("gradingstatus")
            if isinstance(raw, dict)
            else None
        )
        grade_str = grading if isinstance(grading, str) else None

        return MoodleAssignment(
            assignid=assignid,
            name=assign.get("name", ""),
            duedate=assign.get("duedate") or None,
            status=status,
            gradingstatus=gradingstatus,
            grade=_to_float(grade_str),
        )

    async def _get_course_resources(self, courseid: int) -> list[MoodleResource]:
        """Recupere les ressources d'un cours via core_course_get_contents."""
        try:
            raw = await self.repository.call(
                "core_course_get_contents", courseid=str(courseid)
            )
        except MoodleAPIException as exc:
            logger.warning("resources cours=%d : %s", courseid, exc.detail)
            return []

        resources: list[MoodleResource] = []
        for section in raw if isinstance(raw, list) else []:
            section_name = section.get("name", "")
            for module in section.get("modules", []):
                modname = module.get("modname", "")
                if modname in _IGNORED_MODNAMES:
                    continue
                raw_desc = module.get("description") or ""
                resources.append(
                    MoodleResource(
                        cmid=module.get("id", 0),
                        name=module.get("name", ""),
                        modname=modname,
                        section_name=section_name,
                        url=module.get("url") or None,
                        description=_strip_html(raw_desc) or None,
                    )
                )
        return resources

    async def _get_calendar_events(self, courseid: int) -> list[MoodleCalendarEvent]:
        """Evenements calendrier des 30 prochains jours pour un cours."""
        now_ts = int(datetime.now(UTC).timestamp())
        thirty_days = 30 * 24 * 3600
        try:
            raw = await self.repository.call(
                "core_calendar_get_action_events_by_course",
                courseid=str(courseid),
                timesortfrom=str(now_ts),
                timesortto=str(now_ts + thirty_days),
                limitnum="50",
            )
        except MoodleAPIException as exc:
            logger.warning("calendar_events cours=%d : %s", courseid, exc.detail)
            return []
        events: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            events = raw.get("events", [])
        elif isinstance(raw, list):
            events = raw
        return [
            MoodleCalendarEvent(
                id=e["id"],
                name=e.get("name", ""),
                description=_strip_html(e.get("description") or "") or None,
                courseid=e.get("courseid") or None,
                timestart=e.get("timestart", 0),
                timeduration=e.get("timeduration", 0),
                modulename=e.get("modulename") or None,
                instance=e.get("instance") or None,
            )
            for e in events
            if e.get("id")
        ]

    async def _get_forum_posts(
        self, userid: int, courseid: int
    ) -> list[MoodleForumPost]:
        """Posts de forum rediges par l'apprenant dans un cours.

        Recupere d'abord les forums du cours (pour obtenir leur cmid),
        puis les posts de l'utilisateur pour chaque forum.
        """
        try:
            forums_raw = await self.repository.call(
                "mod_forum_get_forums_by_courses",
                **{"courseids[0]": str(courseid)},
            )
        except MoodleAPIException as exc:
            logger.warning(
                "forums cours=%d : %s", courseid, exc.detail
            )
            return []

        forums = forums_raw if isinstance(forums_raw, list) else []
        all_posts: list[MoodleForumPost] = []

        for forum in forums:
            cmid = forum.get("cmid")
            if not cmid:
                continue
            try:
                raw = await self.repository.call(
                    "mod_forum_get_discussion_posts_by_userid",
                    userid=str(userid),
                    cmid=str(cmid),
                )
            except MoodleAPIException as exc:
                logger.warning(
                    "forum_posts cours=%d cmid=%s userid=%d : %s",
                    courseid, cmid, userid, exc.detail,
                )
                continue

            posts: list[dict[str, Any]] = []
            if isinstance(raw, dict):
                posts = raw.get("posts", [])
            elif isinstance(raw, list):
                posts = raw

            all_posts.extend(
                MoodleForumPost(
                    id=p["id"],
                    subject=p.get("subject", ""),
                    message=_strip_html(p.get("message") or "") or None,
                    created=p.get("created", 0),
                    courseid=courseid,
                    discussion_id=p.get("discussion", 0),
                )
                for p in posts
                if p.get("id")
            )

        return all_posts

    async def get_quiz_attempt_review(self, attemptid: int) -> MoodleQuizReview:
        """Retourne la revue detaillee d'une tentative de quiz (question par question).

        Appelle mod_quiz_get_attempt_review avec page=-1 (toutes les questions).
        """
        raw = await self.repository.call(
            "mod_quiz_get_attempt_review",
            attemptid=str(attemptid),
            page="-1",
        )

        attempt_data: dict[str, Any] = {}
        questions_raw: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            attempt_data = raw.get("attempt", {})
            questions_raw = raw.get("questions", [])

        quizid: int = (
            attempt_data.get("quiz", 0) if isinstance(attempt_data, dict) else 0
        )

        questions = [
            MoodleQuizQuestion(
                slot=q.get("slot", idx + 1),
                question_text=_strip_html(q.get("html") or "")[:500] or None,
                student_answer=q.get("responseSummary") or None,
                correct=_state_to_correct(q.get("state")),
                mark=_to_float(q.get("mark")),
                maxmark=_to_float(q.get("maxmark")),
                feedback=q.get("feedback") or None,
            )
            for idx, q in enumerate(questions_raw)
        ]

        return MoodleQuizReview(
            attemptid=attemptid,
            quizid=quizid,
            questions=questions,
        )


# -------------------------------------------------------------------------
# Helpers internes
# -------------------------------------------------------------------------


def _to_float(value: Any) -> float | None:
    """Convertit une valeur en float, retourne None si impossible."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _state_to_correct(state: Any) -> bool | None:
    """Derive le booleen correct depuis l'etat Moodle d'une question de quiz.

    gradedright → True, gradedwrong → False, sinon → None (indetermine).
    """
    if state == "gradedright":
        return True
    if state == "gradedwrong":
        return False
    return None


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et normalise les espaces."""
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()


def _build_activity_log(
    courses: list[MoodleCourse],
    quiz_attempts: list[MoodleQuizAttempt],
    assignments: list[MoodleAssignment],
    completion_by_course: dict[int, list[MoodleCompletion]],
) -> list[MoodleActivityEvent]:
    """Derive le journal comportemental depuis les donnees Moodle deja recoltees.

    Detecte : quiz abandonnes, relances, devoirs en retard / a rendre,
    inactivite prolongee, activites massivement incompletes.
    Retourne une liste triee (warnings d'abord).
    """
    now_ts = int(datetime.now(UTC).timestamp())
    due_soon_limit = _DUE_SOON_THRESHOLD_DAYS * 24 * 3600
    inactivity_limit = _INACTIVITY_THRESHOLD_DAYS * 24 * 3600
    events: list[MoodleActivityEvent] = []

    # --- Quiz : regrouper par quizid ---
    attempts_by_quiz: dict[int, list[MoodleQuizAttempt]] = {}
    for a in quiz_attempts:
        attempts_by_quiz.setdefault(a.quizid, []).append(a)

    for quizid, attempts in attempts_by_quiz.items():
        if any(a.state == "abandoned" for a in attempts):
            events.append(
                MoodleActivityEvent(
                    event_type="quiz_abandoned",
                    description=f"Quiz {quizid} abandonne",
                    severity="warning",
                )
            )
        finished = [a for a in attempts if a.state == "finished"]
        if len(finished) > 1:
            events.append(
                MoodleActivityEvent(
                    event_type="quiz_retried",
                    description=f"Quiz {quizid} tente {len(finished)} fois",
                    severity="info",
                )
            )

    # --- Devoirs ---
    for assign in assignments:
        duedate = assign.duedate or 0
        submitted = assign.status == "submitted"
        if duedate <= 0 or submitted:
            continue
        if duedate < now_ts:
            events.append(
                MoodleActivityEvent(
                    event_type="assignment_late",
                    description=f"Devoir '{assign.name}' en retard",
                    severity="warning",
                )
            )
        elif duedate - now_ts < due_soon_limit:
            events.append(
                MoodleActivityEvent(
                    event_type="assignment_due_soon",
                    description=(
                        f"Devoir '{assign.name}' a rendre dans moins de"
                        f" {_DUE_SOON_THRESHOLD_DAYS} jours"
                    ),
                    severity="warning",
                )
            )

    # --- Inactivite par cours ---
    for course in courses:
        if course.lastaccess and (now_ts - course.lastaccess) > inactivity_limit:
            events.append(
                MoodleActivityEvent(
                    event_type="course_inactive",
                    description=(
                        f"Pas d'acces a '{course.fullname}' depuis plus de"
                        f" {_INACTIVITY_THRESHOLD_DAYS} jours"
                    ),
                    course_id=course.id,
                    severity="warning",
                )
            )

    # --- Activites incompletes (par cours) ---
    for cid, completions in completion_by_course.items():
        if not completions:
            continue
        incomplete = sum(1 for c in completions if c.state == 0)
        ratio = incomplete / len(completions)
        if incomplete >= _INCOMPLETE_MIN_COUNT and ratio >= _INCOMPLETE_MIN_RATIO:
            events.append(
                MoodleActivityEvent(
                    event_type="incomplete_activities",
                    description=(
                        f"{incomplete} activites non completees ({ratio:.0%} du cours)"
                    ),
                    course_id=cid,
                    severity="warning",
                )
            )

    # Tri : warnings en premier, puis info
    events.sort(key=lambda e: 0 if e.severity == "warning" else 1)
    return events


def _classify_level(score: float | None) -> LearnerLevel:
    """Convertit un score [0, 1] en LearnerLevel selon les seuils configures."""
    if score is None:
        return LearnerLevel.UNKNOWN
    if score >= _LEVEL_THRESHOLD_ADVANCED:
        return LearnerLevel.ADVANCED
    if score >= _LEVEL_THRESHOLD_INTERMEDIATE:
        return LearnerLevel.INTERMEDIATE
    return LearnerLevel.BEGINNER


def _course_level_score(
    course: MoodleCourse,
    grade_items: list[MoodleGradeItem],
    completions: list[MoodleCompletion],
) -> float | None:
    """Calcule un score [0, 1] agrege pour un cours, ou None si donnees insuffisantes.

    Pondere : ratio des notes (50%), progression (30%), taux de completion (20%).
    Une dimension absente est ignoree et les poids restants sont renormalises.
    """
    components: list[tuple[float, float]] = []  # (valeur normalisee [0,1], poids)

    # --- Notes : moyenne des ratios graderaw / grademax ---
    grade_ratios = [
        max(0.0, min(1.0, item.graderaw / item.grademax))
        for item in grade_items
        if item.graderaw is not None and item.grademax and item.grademax > 0
    ]
    if grade_ratios:
        avg_grade = sum(grade_ratios) / len(grade_ratios)
        components.append((avg_grade, _LEVEL_WEIGHT_GRADES))

    # --- Progression : course.progress (0-100) → ramene a [0, 1] ---
    if course.progress is not None:
        progress_norm = max(0.0, min(1.0, course.progress / 100))
        components.append((progress_norm, _LEVEL_WEIGHT_PROGRESS))

    # --- Completion : ratio activites completees (state >= 1) ---
    if completions:
        completed = sum(1 for c in completions if c.state >= 1)
        ratio = completed / len(completions)
        components.append((ratio, _LEVEL_WEIGHT_COMPLETION))

    if not components:
        return None

    total_weight = sum(weight for _, weight in components)
    weighted_sum = sum(value * weight for value, weight in components)
    return weighted_sum / total_weight


def _compute_learner_level(
    courses: list[MoodleCourse],
    grades_by_course: dict[int, list[MoodleGradeItem]],
    completion_by_course: dict[int, list[MoodleCompletion]],
) -> tuple[LearnerLevel, dict[int, LearnerLevel]]:
    """Calcule le niveau global et par cours a partir des donnees Moodle.

    Le niveau global est la moyenne des scores des cours pour lesquels
    un score a pu etre calcule. Retourne UNKNOWN si aucun cours exploitable.
    """
    level_by_course: dict[int, LearnerLevel] = {}
    course_scores: list[float] = []

    for course in courses:
        score = _course_level_score(
            course,
            grades_by_course.get(course.id, []),
            completion_by_course.get(course.id, []),
        )
        level_by_course[course.id] = _classify_level(score)
        if score is not None:
            course_scores.append(score)

    if not course_scores:
        return LearnerLevel.UNKNOWN, level_by_course

    global_score = sum(course_scores) / len(course_scores)
    return _classify_level(global_score), level_by_course
