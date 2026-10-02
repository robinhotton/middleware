"""Endpoints REST pour le domaine Moodle."""

from fastapi import APIRouter, Depends, Request

from ....conf import limiter
from ...auth import RoleName, User, require_role
from ..dependencies import get_moodle_service
from ..models import LearnerProfile, MoodleQuizReview
from ..services import MoodleService

router = APIRouter()


@router.get(
    "/learner/{moodle_userid}",
    tags=["moodle"],
    summary="Profil apprenant agrege (LLM-ready)",
    response_model=LearnerProfile,
    responses={
        502: {"description": "Erreur Moodle Web Services"},
        404: {"description": "Apprenant introuvable dans Moodle"},
        403: {"description": "Acces admin requis"},
    },
)
@limiter.limit("10/minute")
async def get_learner_profile(
    request: Request,
    moodle_userid: int,
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
    service: MoodleService = Depends(get_moodle_service),
) -> LearnerProfile:
    """Retourne le profil complet d'un apprenant Moodle.

    Orchestre en parallele : cours, notes, completion, quiz, devoirs.
    Requiert le role admin (token Moodle admin = acces global).
    """
    return await service.get_learner_profile(moodle_userid)


@router.get(
    "/learner/{moodle_userid}/quiz/{attemptid}/review",
    tags=["moodle"],
    summary="Revue detaillee d'une tentative de quiz (question par question)",
    response_model=MoodleQuizReview,
    responses={
        502: {"description": "Erreur Moodle Web Services"},
        403: {"description": "Acces admin requis"},
    },
)
@limiter.limit("10/minute")
async def get_quiz_attempt_review(
    request: Request,
    moodle_userid: int,
    attemptid: int,
    _current_user: User = Depends(require_role(RoleName.ADMIN)),
    service: MoodleService = Depends(get_moodle_service),
) -> MoodleQuizReview:
    """Retourne la revue question par question d'une tentative de quiz.

    Appelle mod_quiz_get_attempt_review (page=-1 = toutes les questions).
    A utiliser pour les tentatives a l'etat 'finished'.
    Requiert le role admin.
    """
    return await service.get_quiz_attempt_review(attemptid)
