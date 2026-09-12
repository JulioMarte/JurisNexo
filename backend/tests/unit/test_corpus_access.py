from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from jurisnexo.corpus.access import (
    CanonicalAuditState,
    CanonicalCommitAuthorization,
    CorpusAuthorizationError,
    CorpusPrincipal,
    CorpusScope,
    authorize_canonical_commit,
    authorize_scope_read,
    authorize_scope_write,
)

ORG_A = UUID("00000000-0000-0000-0000-00000000000a")
ORG_B = UUID("00000000-0000-0000-0000-00000000000b")
SUBJECT = UUID("00000000-0000-0000-0000-000000000001")
ARTIFACT = UUID("00000000-0000-0000-0000-000000000010")
ARTIFACT_PAGE = UUID("00000000-0000-0000-0000-000000000020")


def _principal(*, public_commit: bool = False) -> CorpusPrincipal:
    return CorpusPrincipal(
        subject_id=SUBJECT,
        organization_ids=frozenset({ORG_A}),
        can_commit_public=public_commit,
    )


def _request(
    *, scope: CorpusScope, audit_state: CanonicalAuditState = "VERIFIED"
) -> CanonicalCommitAuthorization:
    return CanonicalCommitAuthorization(
        scope=scope,
        extraction_audit_state=audit_state,
        source_artifact_id=ARTIFACT,
        approved_artifact_page_ids=(ARTIFACT_PAGE,),
    )


def test_private_scope_requires_organization() -> None:
    with pytest.raises(ValidationError):
        CorpusScope(visibility="private")


def test_public_scope_rejects_organization_id() -> None:
    with pytest.raises(ValidationError):
        CorpusScope(visibility="public", organization_id=ORG_A)


def test_public_read_is_allowed_without_membership() -> None:
    authorize_scope_read(principal=_principal(), scope=CorpusScope(visibility="public"))


def test_private_read_is_limited_to_principal_membership() -> None:
    authorize_scope_read(
        principal=_principal(),
        scope=CorpusScope(visibility="private", organization_id=ORG_A),
    )
    with pytest.raises(CorpusAuthorizationError):
        authorize_scope_read(
            principal=_principal(),
            scope=CorpusScope(visibility="private", organization_id=ORG_B),
        )


def test_private_write_cannot_cross_organization_boundary() -> None:
    with pytest.raises(CorpusAuthorizationError):
        authorize_scope_write(
            principal=_principal(),
            scope=CorpusScope(visibility="private", organization_id=ORG_B),
        )


def test_public_write_requires_explicit_privilege() -> None:
    scope = CorpusScope(visibility="public")
    with pytest.raises(CorpusAuthorizationError):
        authorize_scope_write(principal=_principal(), scope=scope)
    authorize_scope_write(principal=_principal(public_commit=True), scope=scope)


@pytest.mark.parametrize(
    "audit_state",
    ["MORE_INVESTIGATION_REQUIRED", "REJECTED", "SOURCE_QUALITY_BLOCKED"],
)
def test_canonical_commit_rejects_non_verified_extraction_audit(
    audit_state: CanonicalAuditState,
) -> None:
    request = _request(
        scope=CorpusScope(visibility="private", organization_id=ORG_A),
        audit_state=audit_state,
    )
    with pytest.raises(CorpusAuthorizationError):
        authorize_canonical_commit(principal=_principal(), request=request)


@pytest.mark.parametrize("audit_state", ["VERIFIED", "VERIFIED_WITH_AMENDMENTS"])
def test_canonical_commit_allows_verified_audit_for_member(
    audit_state: CanonicalAuditState,
) -> None:
    request = _request(
        scope=CorpusScope(visibility="private", organization_id=ORG_A),
        audit_state=audit_state,
    )
    authorize_canonical_commit(principal=_principal(), request=request)


def test_canonical_commit_requires_precommit_artifact_page_evidence() -> None:
    with pytest.raises(ValidationError):
        CanonicalCommitAuthorization(
            scope=CorpusScope(visibility="private", organization_id=ORG_A),
            extraction_audit_state="VERIFIED",
            source_artifact_id=ARTIFACT,
            approved_artifact_page_ids=(),
        )
