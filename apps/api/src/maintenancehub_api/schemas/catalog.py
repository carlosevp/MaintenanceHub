from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from maintenancehub_api.schemas.common import ORMModel


class EnvironmentOut(ORMModel):
    id: str
    key: str
    name: str
    sort_order: int


class EnvironmentCreate(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = 0


class AppEnvironmentIn(BaseModel):
    environment_id: str
    display_name: str = Field(min_length=1, max_length=200)


class AppEnvironmentOut(ORMModel):
    id: str
    environment_id: str
    display_name: str
    environment: Optional[EnvironmentOut] = None


class ApplicationCreate(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    environments: list[AppEnvironmentIn] = Field(default_factory=list)


class ApplicationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    status: Optional[str] = None


class ApplicationOut(ORMModel):
    id: str
    key: str
    name: str
    description: Optional[str] = None
    status: str
    environments: list[AppEnvironmentOut] = Field(default_factory=list)


class OwnershipIn(BaseModel):
    owner_type: str  # user | support_group
    owner_id: str


class OwnershipOut(ORMModel):
    id: str
    subject_type: str
    subject_id: str
    owner_type: str
    owner_id: str


class DependencyCreate(BaseModel):
    to_type: str
    to_id: str
    dependency_kind: str = "depends_on"
    from_environment_id: Optional[str] = None
    to_environment_id: Optional[str] = None


class DependencyOut(ORMModel):
    id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    dependency_kind: str
    origin: str
    from_environment_id: Optional[str] = None
    to_environment_id: Optional[str] = None


class InfraComponentOut(ORMModel):
    id: str
    key: str
    name: str
    kind: Optional[str] = None
    description: Optional[str] = None


class TagCreate(BaseModel):
    key: str
    name: str


class TagOut(ORMModel):
    id: str
    key: str
    name: str


class ExternalCiLinkIn(BaseModel):
    source_system: str
    external_id: str
    display_name: Optional[str] = None


class ExternalCiLinkOut(ORMModel):
    id: str
    subject_type: str
    subject_id: str
    source_system: str
    external_id: str
    display_name: Optional[str] = None


class SupportGroupCreate(BaseModel):
    key: str
    name: str
    directory_group: Optional[str] = None


class SupportGroupOut(ORMModel):
    id: str
    key: str
    name: str
    directory_group: Optional[str] = None
