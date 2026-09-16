from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

from jurisnexo.corpus.legal_graph import (
    LegalNormInput,
    PostgresLegalGraphRepository,
    ProvisionInput,
    RelationObservationInput,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


@pytest.fixture(scope="module")
def connection() -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        yield conn


def _document(connection: psycopg.Connection[Any], *, document_type: str, title: str) -> UUID:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.legal_documents (
                document_type, title, country_code, jurisdiction_code
            ) values (%s, %s, 'DO', 'do') returning id
            """,
            (document_type, title),
        )
        row = cursor.fetchone()
        assert row is not None
        return row[0]


def _evidence_page(connection: psycopg.Connection[Any]) -> UUID:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            insert into corpus.source_artifacts (sha256, mime_type, byte_size)
            values (%s, 'application/pdf', 123) returning id
            """,
            ("a" * 64,),
        )
        artifact = cursor.fetchone()
        assert artifact is not None
        cursor.execute(
            """
            insert into corpus.artifact_pages (
                artifact_id, page_number, extracted_text, extraction_status
            ) values (%s, 1, 'La sentencia cita el artículo 17.', 'native_text') returning id
            """,
            (artifact[0],),
        )
        page = cursor.fetchone()
        assert page is not None
        return page[0]


def test_relation_observation_promotes_to_identity_assertion_and_evidence(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        repository = PostgresLegalGraphRepository(connection)
        statute = _document(connection, document_type="statute", title="Ley de prueba")
        decision = _document(connection, document_type="judicial_decision", title="Sentencia")
        article = repository.upsert_provision(
            ProvisionInput(
                document_id=statute,
                provision_type="article",
                label="Artículo 17",
                normalized_label="art-17",
            )
        )
        evidence_page = _evidence_page(connection)
        observation_id = repository.record_relation_observation(
            RelationObservationInput(
                source_document_id=decision,
                relation_type="cites",
                target_document_id=statute,
                target_provision_id=article,
                assertion_method="explicit_primary_text",
                method_name="citation-parser-v1",
                evidence_artifact_page_id=evidence_page,
                evidence_excerpt="cita el artículo 17",
            )
        )
        assertion_id = repository.promote_relation(
            observation_id,
            verification_method="independent_auditor",
        )
        relations = repository.relations_for_document(decision)
        assert len(relations) == 1
        assert relations[0].assertion_id == assertion_id
        assert relations[0].relation_type == "cites"
        assert relations[0].target_document_id == statute

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select count(*)
                from corpus.legal_relation_assertion_evidence
                where assertion_id = %s and artifact_page_id = %s
                """,
                (assertion_id, evidence_page),
            )
            assert cursor.fetchone() == (1,)


def test_contextual_relation_observation_cannot_be_promoted_globally(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        repository = PostgresLegalGraphRepository(connection)
        statute = _document(connection, document_type="statute", title="Ley interpretada")
        decision = _document(connection, document_type="judicial_decision", title="Sentencia")
        observation_id = repository.record_relation_observation(
            RelationObservationInput(
                source_document_id=decision,
                relation_type="interprets",
                target_document_id=statute,
                assertion_method="llm_extracted",
                method_name="fixture-agent-v1",
            )
        )
        with pytest.raises(ValueError, match="requires issue/proposition context"):
            repository.promote_relation(observation_id, verification_method="auditor")
        with connection.cursor() as cursor:
            cursor.execute("select count(*) from corpus.legal_relation_identities")
            assert cursor.fetchone() == (0,)


def test_unresolved_citation_is_observable_but_not_canonical(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        repository = PostgresLegalGraphRepository(connection)
        source = _document(connection, document_type="judicial_decision", title="Caso")
        observation_id = repository.record_relation_observation(
            RelationObservationInput(
                source_document_id=source,
                relation_type="cites",
                raw_target_citation="Ley 999-99, art. 3",
                assertion_method="explicit_primary_text",
                method_name="citation-parser-v1",
            )
        )
        with pytest.raises(ValueError, match="unresolved target"):
            repository.promote_relation(observation_id, verification_method="resolver")


def test_derived_norm_is_not_primary_text_and_requires_verified_source(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        repository = PostgresLegalGraphRepository(connection)
        regulation = _document(connection, document_type="regulation", title="Reglamento")
        article = repository.upsert_provision(
            ProvisionInput(
                document_id=regulation,
                provision_type="article",
                label="Artículo 8",
                normalized_label="art-8",
            )
        )
        proposition_id, assertion_id = repository.create_legal_norm(
            LegalNormInput(
                jurisdiction_code="do",
                norm_kind="document_submission",
                statement_text="Presentar certificación vigente.",
                derivation_kind="synthesized_interpretation",
            ),
            verification_method="legal-analyst-v1",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "select assertion_kind from corpus.legal_propositions where id = %s",
                (proposition_id,),
            )
            assert cursor.fetchone() == ("synthesized_interpretation",)

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            repository.verify_legal_norm(assertion_id, reviewer="lawyer-1")

        repository.attach_norm_source(
            norm_assertion_id=assertion_id,
            document_id=regulation,
            provision_id=article,
            source_role="establishes",
            verification_method="primary_text_review",
            verification_status="verified",
        )
        repository.verify_legal_norm(assertion_id, reviewer="lawyer-1")
        with connection.cursor() as cursor:
            cursor.execute(
                "select verification_status, reviewed_by from corpus.legal_norm_assertions where id = %s",
                (assertion_id,),
            )
            assert cursor.fetchone() == ("verified", "lawyer-1")


def test_tags_remain_classification_not_relation_identity(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        document = _document(connection, document_type="statute", title="Ley tributaria")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_tags (slug, label, tag_type)
                values ('tributario', 'Tributario', 'practice_area') returning id
                """
            )
            tag = cursor.fetchone()
            assert tag is not None
            cursor.execute(
                "insert into corpus.legal_document_tags (document_id, tag_id, provenance) values (%s, %s, 'human_reviewed')",
                (document, tag[0]),
            )
            cursor.execute(
                "select count(*) from corpus.legal_relation_identities where source_document_id = %s",
                (document,),
            )
            assert cursor.fetchone() == (0,)
