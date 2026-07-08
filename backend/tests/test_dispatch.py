"""enqueue_job dispatches to the right backend based on settings.run_mode."""
from app.config import settings
from app.api import jobs


def test_celery_mode_calls_delay(monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "celery")
    called = {}
    # patch the lazily-imported symbol on the tasks module
    import app.worker.tasks as tasks
    monkeypatch.setattr(tasks.run_pipeline, "delay", lambda job_id: called.setdefault("delay", job_id))
    jobs.enqueue_job(42)
    assert called["delay"] == 42


def test_ecs_mode_launches_head_task(monkeypatch):
    monkeypatch.setattr(settings, "run_mode", "ecs")
    called = {}
    import app.services.dispatch as dispatch
    monkeypatch.setattr(dispatch, "launch_head_task_ecs", lambda job_id: called.setdefault("ecs", job_id))
    jobs.enqueue_job(99)
    assert called["ecs"] == 99


def test_ecs_dispatch_requires_settings(monkeypatch):
    """launch_head_task_ecs fails clearly if the ECS settings aren't configured."""
    import pytest
    from app.services.dispatch import launch_head_task_ecs
    monkeypatch.setattr(settings, "ecs_cluster", None)
    monkeypatch.setattr(settings, "head_task_def", None)
    monkeypatch.setattr(settings, "ecs_subnets", None)
    with pytest.raises(RuntimeError, match="run_mode=ecs requires"):
        launch_head_task_ecs(1)
