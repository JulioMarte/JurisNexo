from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReconciliationSnapshot:
    planned_source_ids: frozenset[str]
    run_item_source_ids: frozenset[str]
    referenced_artifact_ids: frozenset[str]
    lineage_artifact_ids: frozenset[str]
    storage_artifact_ids: frozenset[str]
    quality_report_source_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    missing_run_items: tuple[str, ...]
    unexpected_run_items: tuple[str, ...]
    missing_lineage: tuple[str, ...]
    missing_storage: tuple[str, ...]
    missing_quality_reports: tuple[str, ...]

    @property
    def can_close(self) -> bool:
        return not any(
            (
                self.missing_run_items,
                self.unexpected_run_items,
                self.missing_lineage,
                self.missing_storage,
                self.missing_quality_reports,
            )
        )


def reconcile_normalization(snapshot: ReconciliationSnapshot) -> ReconciliationReport:
    return ReconciliationReport(
        missing_run_items=tuple(sorted(snapshot.planned_source_ids - snapshot.run_item_source_ids)),
        unexpected_run_items=tuple(sorted(snapshot.run_item_source_ids - snapshot.planned_source_ids)),
        missing_lineage=tuple(sorted(snapshot.referenced_artifact_ids - snapshot.lineage_artifact_ids)),
        missing_storage=tuple(sorted(snapshot.referenced_artifact_ids - snapshot.storage_artifact_ids)),
        missing_quality_reports=tuple(
            sorted(snapshot.planned_source_ids - snapshot.quality_report_source_ids)
        ),
    )
