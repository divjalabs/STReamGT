"""Project-scoped access control.

A project aggregates samples across many kits, so project access is DECOUPLED from kit_access:
kit_access gates job submission, this gates the animal/sample/consensus/matching data. Access is
granted to admins, the project owner, and users in project_access (editor role for writes).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth.deps import get_current_user
from app.models import User, Project, ProjectRole
from app.models.project import project_access


def _role_for(db: Session, project: Project, user: User) -> ProjectRole | None:
    """Return the user's effective role on the project, or None if no access."""
    if user.is_admin or project.owner_user_id == user.id:
        return ProjectRole.editor
    row = db.execute(
        select(project_access.c.role).where(
            project_access.c.project_id == project.id,
            project_access.c.user_id == user.id,
        )
    ).first()
    return row[0] if row else None


def get_accessible_project(
    project_id: int,
    *,
    need_edit: bool = False,
    db: Session,
    user: User,
) -> Project:
    """Load a project the user may access, or raise 404 (hide existence) / 403 (read-only)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    role = _role_for(db, project, user)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if need_edit and role != ProjectRole.editor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Editor access required")
    return project


def project_dep(need_edit: bool = False):
    """FastAPI dependency factory: resolves `project_id` path param to an accessible Project."""

    def _dep(
        project_id: int,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Project:
        return get_accessible_project(project_id, need_edit=need_edit, db=db, user=user)

    return _dep
