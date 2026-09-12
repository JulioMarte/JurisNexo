from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.acquisition.completeness import (
    CorpusCompletenessReport,
    RegisteredArtifactInventory,
    SourceInventorySnapshot,
    verify_source_completeness,
)
from jurisnexo.acquisition.official_corpus import (
    ArtifactCatalog,
    HttpFetcher,
    ObjectStore,
    OfficialDocumentCandidate,
    acquire_candidates,
    object_key_for,
)


@dataclass(frozen=True, slots=True)
class SourceReconciliationPlan:
    source: str
    discovered_count: int
    missing_registration: tuple[OfficialDocumentCandidate, ...]
    missing_storage: tuple[OfficialDocumentCandidate, ...]

    @property
    def candidates_to_acquire(self) -> tuple[OfficialDocumentCandidate, ...]:
        by_url: dict[str, OfficialDocumentCandidate] = {}
        for candidate in (*self.missing_registration, *self.missing_storage):
            by_url[candidate.document_url] = candidate
        return tuple(by_url[url] for url in sorted(by_url))

    @property
    def acquisition_count(self) -> int:
        return len(self.candidates_to_acquire)


def plan_source_reconciliation(
    *,
    snapshot: SourceInventorySnapshot,
    inventory: RegisteredArtifactInventory,
    object_store: ObjectStore,
) -> SourceReconciliationPlan:
    """Find official documents missing from PostgreSQL or object storage.

    The plan deliberately uses the current official inventory as the authority. A document
    already registered in PostgreSQL is re-fetched only when its content-addressed object is
    missing from storage.
    """

    observations = inventory.observations_for(snapshot.source)
    by_identifier_and_url = {
        (item.source_identifier, item.document_url): item for item in observations
    }

    missing_registration: list[OfficialDocumentCandidate] = []
    missing_storage: list[OfficialDocumentCandidate] = []

    seen_identifiers: dict[str, str] = {}
    for candidate in snapshot.candidates:
        if candidate.source != snapshot.source:
            raise ValueError("source inventory snapshot contains a candidate from another source")
        previous_url = seen_identifiers.get(candidate.source_identifier)
        if previous_url is not None and previous_url != candidate.document_url:
            raise ValueError(
                f"ambiguous official identifier {candidate.source_identifier!r}: multiple URLs"
            )
        seen_identifiers[candidate.source_identifier] = candidate.document_url

        observation = by_identifier_and_url.get(
            (candidate.source_identifier, candidate.document_url)
        )
        if observation is None:
            missing_registration.append(candidate)
            continue

        key = object_key_for(source=snapshot.source, sha256=observation.sha256)
        if not object_store.exists(key):
            missing_storage.append(candidate)

    return SourceReconciliationPlan(
        source=snapshot.source,
        discovered_count=len(seen_identifiers),
        missing_registration=tuple(missing_registration),
        missing_storage=tuple(missing_storage),
    )


@dataclass(frozen=True, slots=True)
class SourceReconciliationResult:
    plan: SourceReconciliationPlan
    acquired_count: int
    report: CorpusCompletenessReport


def reconcile_source(
    *,
    snapshot: SourceInventorySnapshot,
    inventory: RegisteredArtifactInventory,
    fetcher: HttpFetcher,
    object_store: ObjectStore,
    artifact_catalog: ArtifactCatalog,
) -> SourceReconciliationResult:
    """Acquire only missing official artifacts, register them, then re-certify the source."""

    plan = plan_source_reconciliation(
        snapshot=snapshot,
        inventory=inventory,
        object_store=object_store,
    )
    candidates = plan.candidates_to_acquire
    acquired = acquire_candidates(
        candidates=candidates,
        fetcher=fetcher,
        object_store=object_store,
        artifact_catalog=artifact_catalog,
    )
    report = verify_source_completeness(
        snapshot=snapshot,
        inventory=inventory,
        object_store=object_store,
    )
    return SourceReconciliationResult(
        plan=plan,
        acquired_count=len(acquired),
        report=report,
    )
