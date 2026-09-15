from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from jurisnexo.bootstrap.http import create_http_app
from jurisnexo.bootstrap.settings import RuntimeSettings
from jurisnexo.platform.db.connection import ConnectionFactory

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.provenance]


class FakeFetcher:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.urls: list[str] = []

    def get_bytes(self, url: str) -> bytes:
        self.urls.append(url)
        return self.content


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def exists(self, key: str) -> bool:
        return key in self.objects

    def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        assert content_type == "application/pdf"
        assert metadata["sha256"] == hashlib.sha256(content).hexdigest()
        self.objects[key] = content


@pytest.fixture
def connection_factory() -> ConnectionFactory:
    def open_connection() -> psycopg.Connection[Any]:
        return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    return open_connection


@pytest.fixture
def api_client(
    connection_factory: ConnectionFactory,
) -> Iterator[tuple[TestClient, FakeFetcher, FakeObjectStore]]:
    fetcher = FakeFetcher(b"%PDF-1.7\nfunctional ingestion API fixture\n%%EOF\n")
    store = FakeObjectStore()
    app = create_http_app(
        RuntimeSettings(environment="test"),
        connection_factory=connection_factory,
        fetcher_factory=lambda: fetcher,
        object_store_factory=lambda: store,
    )
    with TestClient(app) as client:
        yield client, fetcher, store


def _delete_fixture(
    connection_factory: ConnectionFactory,
    *,
    source_id: UUID,
    collection_id: UUID | None = None,
    document_id: UUID | None = None,
    artifact_id: UUID | None = None,
    run_id: UUID | None = None,
) -> None:
    with (
        connection_factory() as connection,
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        if run_id is not None:
            cursor.execute("DELETE FROM corpus.acquisition_runs WHERE id = %s", (run_id,))
        if document_id is not None:
            cursor.execute(
                "DELETE FROM corpus.source_documents WHERE id = %s",
                (document_id,),
            )
        if artifact_id is not None:
            cursor.execute(
                "DELETE FROM corpus.source_artifacts WHERE id = %s",
                (artifact_id,),
            )
        if collection_id is not None:
            cursor.execute(
                "DELETE FROM corpus.source_collections WHERE id = %s",
                (collection_id,),
            )
        cursor.execute("DELETE FROM corpus.source_registries WHERE id = %s", (source_id,))


def test_ingestion_control_api_acquires_and_catalogs_artifact(
    api_client: tuple[TestClient, FakeFetcher, FakeObjectStore],
    connection_factory: ConnectionFactory,
) -> None:
    client, fetcher, store = api_client
    source_code = f"test_source_{uuid4().hex[:10]}"
    source_identifier = f"fixture-{uuid4().hex}"
    document_url = "https://example.invalid/fixture-decision.pdf"
    source_id: UUID | None = None
    collection_id: UUID | None = None
    document_id: UUID | None = None
    artifact_id: UUID | None = None
    run_id: UUID | None = None

    try:
        source_response = client.post(
            "/v1/sources",
            json={
                "code": source_code,
                "name": "Integration fixture source",
                "institution": "Integration tests",
                "authority_class": "official_primary",
                "base_locator": "https://example.invalid/",
                "active": True,
            },
        )
        assert source_response.status_code == 201
        assert source_response.headers["X-Correlation-ID"]
        source_id = UUID(source_response.json()["id"])

        collection_response = client.post(
            "/v1/source-collections",
            json={
                "source_id": str(source_id),
                "code": "decisions",
                "document_kind": "judicial_decision",
                "acquisition_policy": "enabled",
                "agent_visibility": "hidden",
                "active": True,
            },
        )
        assert collection_response.status_code == 201
        collection_id = UUID(collection_response.json()["id"])

        with connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.source_documents (
                    source_registry_id, source_identifier, source_collection,
                    document_kind, discovery_url, current_document_url,
                    artifact_availability, latest_source_metadata,
                    latest_payload_sha256
                ) VALUES (%s, %s, 'decisions', 'judicial_decision',
                          'https://example.invalid/', %s, 'available', '{}'::jsonb,
                          repeat('a', 64))
                RETURNING id
                """,
                (source_id, source_identifier, document_url),
            )
            row = cursor.fetchone()
            assert row is not None
            document_id = row[0]

        documents_response = client.get(
            "/v1/source-documents",
            params={"source_id": str(source_id), "source_collection": "decisions"},
        )
        assert documents_response.status_code == 200
        assert documents_response.json()["data"][0]["acquired"] is False

        create_run_response = client.post(
            "/v1/acquisition-runs",
            json={
                "source_collection_id": str(collection_id),
                "source_document_ids": [str(document_id)],
            },
        )
        assert create_run_response.status_code == 201
        run_payload = create_run_response.json()
        assert run_payload["status"] == "queued"
        assert run_payload["selected_count"] == 1
        run_id = UUID(run_payload["id"])

        execute_response = client.post(f"/v1/acquisition-runs/{run_id}:execute")
        assert execute_response.status_code == 200
        executed = execute_response.json()
        assert executed["status"] == "succeeded"
        assert executed["acquired_count"] == 1
        assert executed["failed_count"] == 0
        assert fetcher.urls == [document_url]
        assert len(store.objects) == 1
        stored_key = next(iter(store.objects))
        expected_prefix = f"jurisdictions/do/{source_code.replace('_', '-')}/decisions/"
        assert stored_key.startswith(expected_prefix)

        items_response = client.get(f"/v1/acquisition-runs/{run_id}/items")
        assert items_response.status_code == 200
        item = items_response.json()["data"][0]
        assert item["status"] == "acquired"
        artifact_id = UUID(item["artifact_id"])

        artifacts_response = client.get("/v1/artifacts", params={"limit": 200})
        assert artifacts_response.status_code == 200
        artifact = next(
            row for row in artifacts_response.json()["data"] if row["id"] == str(artifact_id)
        )
        assert artifact["sha256"] == hashlib.sha256(fetcher.content).hexdigest()
        assert artifact["storage_locator"].startswith("s3://unconfigured/")
    finally:
        if source_id is not None:
            _delete_fixture(
                connection_factory,
                source_id=source_id,
                collection_id=collection_id,
                document_id=document_id,
                artifact_id=artifact_id,
                run_id=run_id,
            )


def test_collection_policy_blocks_acquisition_until_explicitly_enabled(
    api_client: tuple[TestClient, FakeFetcher, FakeObjectStore],
    connection_factory: ConnectionFactory,
) -> None:
    client, _, _ = api_client
    source_code = f"policy_source_{uuid4().hex[:10]}"
    source_id: UUID | None = None
    collection_id: UUID | None = None
    document_id: UUID | None = None

    try:
        source = client.post(
            "/v1/sources",
            json={
                "code": source_code,
                "name": "Policy fixture source",
                "institution": "Integration tests",
                "authority_class": "official_primary",
            },
        ).json()
        source_id = UUID(source["id"])
        collection = client.post(
            "/v1/source-collections",
            json={
                "source_id": str(source_id),
                "code": "decisions",
                "document_kind": "judicial_decision",
            },
        ).json()
        collection_id = UUID(collection["id"])

        with connection_factory() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.source_documents (
                    source_registry_id, source_identifier, source_collection,
                    document_kind, discovery_url, current_document_url,
                    artifact_availability, latest_source_metadata,
                    latest_payload_sha256
                ) VALUES (%s, %s, 'decisions', 'judicial_decision',
                          'https://example.invalid/', 'https://example.invalid/a.pdf',
                          'available', '{}'::jsonb, repeat('b', 64))
                RETURNING id
                """,
                (source_id, f"policy-{uuid4().hex}"),
            )
            row = cursor.fetchone()
            assert row is not None
            document_id = row[0]

        blocked = client.post(
            "/v1/acquisition-runs",
            json={
                "source_collection_id": str(collection_id),
                "source_document_ids": [str(document_id)],
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "acquisition_policy_blocks_run"
    finally:
        if source_id is not None:
            _delete_fixture(
                connection_factory,
                source_id=source_id,
                collection_id=collection_id,
                document_id=document_id,
            )
