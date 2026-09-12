from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CorpusVisibility = Literal["public", "private"]
CanonicalAuditState = Literal[
    "VERIFIED",
    "VERIFIED_WITH_AMENDMENTS",
    "MORE_INVESTIGATION_REQUIRED",
    "REJECTED",
    "SOURCE_QUALITY_BLOCKED",
]


class CorpusAuthorizationError(PermissionError):
    """Raised when a principal cannot perform the requested corpus operation."""


class CorpusScope(BaseModel):
    """Durable access boundary for corpus data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    visibility: CorpusVisibility
    organization_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> CorpusScope:
        if self.visibility == "private" and self.organization_id is None:
            raise ValueError("private corpus scope requires organization_id")
        if self.visibility == "public" and self.organization_id is not None:
            raise ValueError("public corpus scope must not carry organization_id")
        return self


@dataclass(frozen=True, slots=True)
class CorpusPrincipal:
    """Server-side authorization context; never supplied by an agent/model."""

    subject_id: UUID
    organization_ids: frozenset[UUID]
    can_commit_public: bool = False


class CanonicalCommitAuthorization(BaseModel):
    """Minimum gate inputs required before canonical persistence is allowed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: CorpusScope
    extraction_audit_state: CanonicalAuditState
    source_artifact_id: UUID
    approved_case_page_ids: tuple[UUID, ...] = Field(min_length=1)


_ALLOW_CANONICAL_COMMIT_STATES = {"VERIFIED", "VERIFIED_WITH_AMENDMENTS"}


def authorize_scope_read(*, principal: CorpusPrincipal, scope: CorpusScope) -> None:
    """Allow public reads globally and private reads only inside principal membership."""

    if scope.visibility == "public":
        return
    if scope.organization_id not in principal.organization_ids:
        raise CorpusAuthorizationError("principal is not a member of the private corpus organization")


def authorize_scope_write(*, principal: CorpusPrincipal, scope: CorpusScope) -> None:
    """Authorize mutations without trusting caller-provided tenant identifiers."""

    if scope.visibility == "public":
        if not principal.can_commit_public:
            raise CorpusAuthorizationError("principal is not authorized to mutate public corpus")
        return
    if scope.organization_id not in principal.organization_ids:
        raise CorpusAuthorizationError("principal cannot mutate another organization's corpus")


def authorize_canonical_commit(
    *, principal: CorpusPrincipal, request: CanonicalCommitAuthorization
) -> None:
    """Fail closed unless tenant and extraction-audit gates both permit canonical commit."""

    authorize_scope_write(principal=principal, scope=request.scope)
    if request.extraction_audit_state not in _ALLOW_CANONICAL_COMMIT_STATES:
        raise CorpusAuthorizationError(
            "canonical commit requires VERIFIED or VERIFIED_WITH_AMENDMENTS extraction audit"
        )
