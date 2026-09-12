from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import psycopg
import pytest

from jurisnexo.corpus.legal_graph import (
    PostgresLegalGraphRepository,
    ProvisionInput,
    RelationObservationInput,
    RequirementInput,
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
            insert into corpus.legal_documents (document_type, title, country_code, jurisdiction_code)
            values (%s, %s, 'DO', 'do')
            returning id
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
            values (%s, 'application/pdf', 123)
            returning id
            """,
            ("a" * 64,),
        )
        artifact = cursor.fetchone()
        assert artifact is not None
        cursor.execute(
            """
            insert into corpus.artifact_pages (
                artifact_id, page_number, extracted_text, extraction_status
            )
            values (%s, 1, 'La sentencia interpreta el artículo 17.', 'native_text')
            returning id
            """,
            (artifact[0],),
        )
        page = cursor.fetchone()
        assert page is not None
        return page[0]


def test_relation_observation_requires_explicit_promotion_and_preserves_evidence(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        repository = PostgresLegalGraphRepository(connection)
        statute = _document(connection, document_type="statute", title="Ley de prueba")
        decision = _document(
            connection,
            document_type="judicial_decision",
            title="Sentencia de prueba",
        )
        article_17 = repository.upsert_provision(
            ProvisionInput(
                document_id=statute,
                provision_type="article",
                label="Artículo 17",
                normalized_label="art-17",
                ordinal=17,
                text="Texto normativo del artículo 17.",
            )
        )
        evidence_page = _evidence_page(connection)

        observation_id = repository.record_relation_observation(
            RelationObservationInput(
                source_document_id=decision,
                relation_type="interprets",
                target_document_id=statute,
                target_provision_id=article_17,
                assertion_method="llm_extracted",
                method_name="fixture-agent-v1",
                confidence=0.83,
                evidence_artifact_page_id=evidence_page,
                evidence_excerpt="interpreta el artículo 17",
                evidence_char_start=13,
                evidence_char_end=37,
            )
        )

        with connection.cursor() as cursor:
            cursor.execute("select count(*) from corpus.legal_relations")
            assert cursor.fetchone() == (0,)

        relation_id = repository.promote_relation(
            observation_id,
            verification_method="independent_auditor",
        )
        relations = repository.relations_for_document(decision)
        assert len(relations) == 1
        assert relations[0].id == relation_id
        assert relations[0].relation_type == "interprets"
        assert relations[0].target_document_id == statute
        assert relations[0].target_provision_id == article_17

        with connection.cursor() as cursor:
            cursor.execute(
                "select status from corpus.legal_relation_observations where id = %s",
                (observation_id,),
            )
            assert cursor.fetchone() == ("accepted",)
            cursor.execute(
                """
                select artifact_page_id, evidence_excerpt
                from corpus.legal_relation_evidence
                where relation_id = %s
                """,
                (relation_id,),
            )
            assert cursor.fetchone() == (evidence_page, "interpreta el artículo 17")


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
            repository.promote_relation(
                observation_id,
                verification_method="deterministic_resolver",
            )


def test_requirement_can_be_grounded_in_norm_and_interpreted_by_case(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        repository = PostgresLegalGraphRepository(connection)
        regulation = _document(connection, document_type="regulation", title="Reglamento")
        decision = _document(connection, document_type="judicial_decision", title="Caso")
        article = repository.upsert_provision(
            ProvisionInput(
                document_id=regulation,
                provision_type="article",
                label="Artículo 8",
                normalized_label="art-8",
            )
        )
        requirement = repository.create_requirement(
            RequirementInput(
                jurisdiction_code="do",
                requirement_type="document_submission",
                canonical_text="Presentar certificación vigente.",
            )
        )
        established = repository.attach_requirement_source(
            requirement_id=requirement,
            document_id=regulation,
            provision_id=article,
            source_role="establishes",
            verification_method="primary_text_review",
            verification_status="verified",
        )
        interpreted = repository.attach_requirement_source(
            requirement_id=requirement,
            document_id=decision,
            source_role="interprets",
            verification_method="decision_auditor",
            verification_status="verified",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                select source_role, verification_status
                from corpus.legal_requirement_sources
                where id in (%s, %s)
                order by source_role
                """,
                (established, interpreted),
            )
            assert cursor.fetchall() == [
                ("establishes", "verified"),
                ("interprets", "verified"),
            ]


def test_tags_remain_classification_not_relations(
    connection: psycopg.Connection[Any],
) -> None:
    with connection.transaction(force_rollback=True):
        document = _document(connection, document_type="statute", title="Ley tributaria")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                insert into corpus.legal_tags (slug, label, tag_type)
                values ('tributario', 'Tributario', 'practice_area')
                returning id
                """
            )
            tag = cursor.fetchone()
            assert tag is not None
            cursor.execute(
                """
                insert into corpus.legal_document_tags (document_id, tag_id, provenance)
                values (%s, %s, 'human_reviewed')
                """,
                (document, tag[0]),
            )
            cursor.execute(
                "select count(*) from corpus.legal_relations where source_document_id = %s",
                (document,),
            )
            assert cursor.fetchone() == (0,)
