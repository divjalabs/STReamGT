from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, EmailStr

from app.models.enums import ProjectRole


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    organisation: str | None = None
    description: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    name: str
    organisation: str | None
    description: str | None
    owner_user_id: int
    created_at: datetime


class PopulationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class PopulationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    name: str
    description: str | None
    sample_count: int = 0


class StudyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    population_id: int | None = None
    include_in_matching: bool = True
    description: str | None = None


class KitRef(BaseModel):
    """Lightweight kit reference for study attachments."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    kit_code: str


class StudyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    population_id: int | None
    name: str
    include_in_matching: bool
    kits: list[KitRef] = []


class SampleTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str | None = None
    exclude_from_analysis: bool = False
    reliable_sample_type: bool = False


class SampleTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str | None
    exclude_from_analysis: bool
    reliable_sample_type: bool


class ShareRequest(BaseModel):
    email: EmailStr
    role: ProjectRole = ProjectRole.viewer


class ProjectMemberOut(BaseModel):
    user_id: int
    email: str
    role: ProjectRole


class ProjectAccessOut(BaseModel):
    owner_user_id: int
    owner_email: str
    members: list[ProjectMemberOut]
