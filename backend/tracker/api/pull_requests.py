from typing import List

from ninja import Router

from tracker import models, schemas

router = Router(tags=["pull-requests"])


@router.get("", response=List[schemas.PullRequestItem])
def list_pull_requests(request):
    # Grouped by repo, newest number first, per PullRequest.Meta.ordering.
    return models.PullRequest.objects.all()
