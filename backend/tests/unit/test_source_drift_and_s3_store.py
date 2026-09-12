from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jurisnexo.acquisition.s3_object_store import S3ObjectStore, S3ObjectStoreConfig
from jurisnexo.acquisition.source_drift import (
    BrowserRecoveryRequest,
    inspect_scj_megaconsulta_surface,
    inspect_tc_sentence_surface,
)

pytestmark = [pytest.mark.unit, pytest.mark.provenance]


class MissingObjectError(Exception):
    pass


@dataclass(slots=True)
class FakeS3Client:
    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def head_object(self, *, Bucket: str, Key: str) -> object:
        if (Bucket, Key) not in self.objects:
            raise MissingObjectError(Key)
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object:
        assert ContentType == "application/pdf"
        assert Metadata["sha256"]
        self.objects[(Bucket, Key)] = Body
        return {"ETag": "fixture"}


def _store(client: FakeS3Client) -> S3ObjectStore:
    return S3ObjectStore(
        client=client,
        config=S3ObjectStoreConfig(
            bucket="jurisnexo-official",
            endpoint_url="https://storage.example.test/s3",
            region="us-east-1",
        ),
        is_not_found=lambda exc: isinstance(exc, MissingObjectError),
    )


def test_generic_s3_store_is_provider_neutral() -> None:
    client = FakeS3Client()
    store = _store(client)
    key = "official/constitutional_court/aa/document.pdf"

    assert store.exists(key) is False
    store.put(
        key=key,
        content=b"%PDF fixture",
        content_type="application/pdf",
        metadata={"sha256": "a" * 64},
    )
    assert store.exists(key) is True


def test_s3_config_requires_https_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        S3ObjectStoreConfig(
            bucket="jurisnexo-official",
            endpoint_url="http://storage.example.test",
            region="us-east-1",
        )


def test_tc_surface_requests_browser_recovery_when_contract_disappears() -> None:
    observation = inspect_tc_sentence_surface("<html><body>maintenance</body></html>")

    assert observation.status == "source_drift"
    assert observation.requires_browser_recovery is True
    request = BrowserRecoveryRequest(observation=observation)
    assert "Playwright" in request.objective
    assert "Do not mutate production" in request.objective


def test_tc_surface_is_healthy_when_sentence_contract_is_present() -> None:
    html = """
    <html><body>
      <h1>Sentencias</h1>
      <a href="/consultas/secretaría/sentencias/tc000126">TC/0001/26</a>
    </body></html>
    """

    observation = inspect_tc_sentence_surface(html)

    assert observation.status == "healthy"
    assert observation.discovered_item_count == 1


def test_scj_landing_page_can_be_healthy_without_direct_pdf_results() -> None:
    html = "<html><body>Consulta de la Suprema Corte de Justicia</body></html>"

    observation = inspect_scj_megaconsulta_surface(html)

    assert observation.status == "healthy"
    assert observation.discovered_item_count == 0
