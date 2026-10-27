"""One species per project: bind a project's species to the kits assigned to it."""
from __future__ import annotations

from app.models import Project, Kit


def bind_project_species(project: Project, kit: Kit) -> None:
    """First kit assigned sets the project's species; a later mismatch raises ValueError.

    A kit with no species doesn't constrain anything (no-op). Comparison is case-insensitive.
    """
    ksp = (kit.species or "").strip()
    if not ksp:
        return
    psp = (project.species or "").strip()
    if not psp:
        project.species = kit.species
    elif psp.lower() != ksp.lower():
        raise ValueError(
            f"This project is for {project.species}; this kit is {kit.species}. "
            "A project holds one species."
        )
