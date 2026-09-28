from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReachabilityAudit:
    catalog_artifact_ids: frozenset[str]
    referenced_artifact_ids: frozenset[str]
    storage_artifact_ids: frozenset[str]

    @property
    def unreferenced_catalog_artifacts(self) -> tuple[str, ...]:
        return tuple(sorted(self.catalog_artifact_ids - self.referenced_artifact_ids))

    @property
    def missing_storage_objects(self) -> tuple[str, ...]:
        return tuple(sorted(self.referenced_artifact_ids - self.storage_artifact_ids))

    @property
    def storage_orphans(self) -> tuple[str, ...]:
        return tuple(sorted(self.storage_artifact_ids - self.catalog_artifact_ids))


def audit_derivative_reachability(
    *,
    catalog_artifact_ids: frozenset[str],
    referenced_artifact_ids: frozenset[str],
    storage_artifact_ids: frozenset[str],
) -> ReachabilityAudit:
    """Read-only audit. Deliberately performs no deletion."""
    return ReachabilityAudit(
        catalog_artifact_ids=catalog_artifact_ids,
        referenced_artifact_ids=referenced_artifact_ids,
        storage_artifact_ids=storage_artifact_ids,
    )
