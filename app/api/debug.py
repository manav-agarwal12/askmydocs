from celery.result import AsyncResult
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models import User
from app.worker.celery_app import celery_app
from app.worker.tasks import boom, count_documents, ping, slow_add

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/ping")
def enqueue_ping(current_user: User = Depends(get_current_user)):
    task = ping.delay()          # .delay() sends it to Redis and returns instantly
    return {"task_id": task.id}


@router.post("/slow-add")
def enqueue_slow_add(
    a: int = 2,
    b: int = 3,
    seconds: int = 10,
    current_user: User = Depends(get_current_user),
):
    task = slow_add.delay(a, b, seconds)
    return {"task_id": task.id}


@router.post("/count-documents")
def enqueue_count_documents(current_user: User = Depends(get_current_user)):
    task = count_documents.delay()
    return {"task_id": task.id}


@router.post("/boom")
def enqueue_boom(current_user: User = Depends(get_current_user)):
    task = boom.delay()
    return {"task_id": task.id}


@router.get("/tasks/{task_id}")
def get_task_result(task_id: str, current_user: User = Depends(get_current_user)):
    """Ask the result backend what happened to a task."""
    result = AsyncResult(task_id, app=celery_app)

    payload = {
        "task_id": task_id,
        "state": result.state,   # PENDING / STARTED / SUCCESS / FAILURE
        "ready": result.ready(),
    }

    if result.successful():
        payload["result"] = result.result
    elif result.failed():
        payload["error"] = str(result.result)   # result holds the exception

    return payload