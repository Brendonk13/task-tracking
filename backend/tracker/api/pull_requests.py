from typing import List

from django.db.models import Count
from django.shortcuts import get_object_or_404
from ninja import Router

from tracker import models, schemas

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
