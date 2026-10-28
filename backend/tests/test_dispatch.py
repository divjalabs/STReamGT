"""enqueue_job dispatches to the right backend, and hands back a handle on the running job."""
from app.config import settings
from app.api import jobs


class _FakeAsyncResult:
    def __init__(self, task_id):
        self.id = task_id


def test_celery_mode_calls_delay(monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "celery")
    called = {}
    # patch the lazily-imported symbol on the tasks module
    import app.worker.tasks as tasks
    def fake_delay(job_id):
        called["delay"] = job_id
        return _FakeAsyncResult("abc-123")

    monkeypatch.setattr(tasks.run_pipeline, "delay", fake_delay)
    handle = jobs.enqueue_job(42)
    assert called["delay"] == 42
    assert handle == "celery:abc-123"


def test_ecs_mode_launches_head_task(monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "ecs")
    called = {}
    import app.services.dispatch as dispatch
    arn = "arn:aws:ecs:eu-central-1:123:task/streamgt/abc"
    def fake_launch(job_id):
        called["ecs"] = job_id
        return arn

    monkeypatch.setattr(dispatch, "launch_head_task_ecs", fake_launch)
    handle = jobs.enqueue_job(99)
    assert called["ecs"] == 99
    assert handle == arn, "the task handle must reach the caller so a stop can use it"


def test_ecs_dispatch_requires_settings(monkeypatch):
    """launch_head_task_ecs fails clearly if the ECS settings aren't configured."""
    import pytest
    from app.services.dispatch import launch_head_task_ecs
    monkeypatch.setattr(settings, "ecs_cluster", None)
    monkeypatch.setattr(settings, "head_task_def", None)
    monkeypatch.setattr(settings, "ecs_subnets", None)
    with pytest.raises(RuntimeError, match="run_mode=ecs requires"):
        launch_head_task_ecs(1)
