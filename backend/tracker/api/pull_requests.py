from typing import List

from django.db.models import Count
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from tracker import models, schemas
from tracker.services import actors
from tracker.services import pull_requests as pull_request_service

router = Router(tags=["pull-requests"])


def _pull_requests():
    """Base queryset for every PR response: the comment count without a query per row."""
    return models.PullRequest.objects.annotate(comment_count=Count("comments"))


@router.get("", response=List[schemas.PullRequestItem])
def list_pull_requests(request):
    # Grouped by repo, newest number first, per PullRequest.Meta.ordering.
    return _pull_requests()


@router.get("/{int:pull_request_id}", response=schemas.PullRequestItem)
def get_pull_request(request, pull_request_id: int):
    return get_object_or_404(_pull_requests(), id=pull_request_id)


@router.patch("/{int:pull_request_id}", response=schemas.PullRequestItem)
def patch_pull_request(request, pull_request_id: int, payload: schemas.PullRequestPatch):
    """Link a PR to the ticket a person says it belongs to (C3.7).

    The identifier match only fires when a branch, title or body names a ticket this
    app already holds, so a branch cut before its ticket existed arrives unlinked and
    stays that way until somebody finishes the job by hand.

    Checks run in the A3 order every mutating endpoint here keeps — 404 for the pull
    request, then 400 for the actor, then 400 for the ticket — so a request that names
    two unknown things is told about the pull request first and writes nothing either
    way.
    """
    pull_request = get_object_or_404(_pull_requests(), id=pull_request_id)
    actor = actors.require_actor(payload.actor_session_id)
    ticket = models.Ticket.objects.filter(id=payload.ticket_id).first()
    if ticket is None:
        raise HttpError(400, "unknown ticket")
    pull_request_service.link(pull_request, ticket, payload.actor_session_id, actor["name"])
    return pull_request
