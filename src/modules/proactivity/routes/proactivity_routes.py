"""Endpoints REST pour le domaine proactivite."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from ....conf import limiter
from ....exceptions import MoodleAPIException
from ...auth import User, require_role
from ...shared.common import MessageResponse
from ..dependencies import get_proactivity_service
from ..models.schemas import ProactivityJobInfo, ProactivityStatusResponse
from ..services import ProactivityService

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_scheduler_status(request: Request) -> ProactivityStatusResponse:
    """Construit ProactivityStatusResponse depuis l'etat du scheduler APScheduler."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return ProactivityStatusResponse(scheduler_running=False, jobs=[])

    running = scheduler.running
    jobs: list[ProactivityJobInfo] = []
    for job in scheduler.get_jobs():
        jobs.append(
            ProactivityJobInfo(
                id=job.id,
                next_run=job.next_run_time,
                trigger=str(job.trigger),
                running=running,
            )
        )
    return ProactivityStatusResponse(scheduler_running=running, jobs=jobs)


@router.get(
    "/status",
    response_model=ProactivityStatusResponse,
    summary="Etat du scheduler proactivite",
    responses={
        401: {"description": "Non authentifie"},
        403: {"description": "Role admin requis"},
    },
)
@limiter.limit("30/minute")
async def get_status(
    request: Request,
    _user: Annotated[User, Depends(require_role("admin"))],
) -> ProactivityStatusResponse:
    """Retourne l'etat des jobs APScheduler (next_run, trigger, actif/pause)."""
    return _get_scheduler_status(request)


@router.post(
    "/trigger",
    response_model=MessageResponse,
    summary="Declenche manuellement un job proactivite",
    responses={
        401: {"description": "Non authentifie"},
        403: {"description": "Role admin requis"},
    },
)
@limiter.limit("10/minute")
async def trigger_job(
    request: Request,
    job: Annotated[
        Literal["reminder", "suggestion"],
        Query(description="Job a declencher : reminder | suggestion"),
    ],
    _user: Annotated[User, Depends(require_role("admin"))],
    svc: Annotated[ProactivityService, Depends(get_proactivity_service)],
) -> MessageResponse:
    """Declenche immediatement run_reminder_job() ou run_suggestion_job().

    Utile pour les tests manuels et le debug.
    """
    try:
        if job == "reminder":
            count = await svc.run_reminder_job()
            return MessageResponse(
                message=f"Job reminder execute : {count} notification(s) envoyee(s)."
            )
        else:
            count = await svc.run_suggestion_job()
            return MessageResponse(
                message=f"Job suggestion execute : {count} suggestion(s) envoyee(s)."
            )
    except MoodleAPIException as exc:
        logger.error("Trigger job=%s echoue : %s", job, exc.detail)
        return MessageResponse(
            message=f"Job {job} termine avec erreur Moodle : {exc.detail}"
        )
