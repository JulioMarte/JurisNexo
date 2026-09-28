from __future__ import annotations

"""Publish corpus-verification evidence as immutable, content-checked S3 objects."""

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any, cast

from jurisnexo.acquisition.s3_object_store import build_s3_object_store
from jurisnexo.normalization.visual_reference_alignment import (
    VisualReferencePolicy,
)

BASE_PREFIX = "benchmarks/scj-principales/corpus-verification/v1"
_HEX = re.compile(r"^[0-9a-f]+$")
POLICY = VisualReferencePolicy()


def _policy_sha256() -> str:
    policy = {
        name: getattr(POLICY, name)
        for name in POLICY.__dataclass_fields__
    }
    return _sha256_bytes(
        json.dumps(
            policy,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _require_hex(value: str, *, length: int, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != length or _HEX.fullmatch(normalized) is None:
        raise ValueError(f"{label} must be {length} lowercase hex characters")
    return normalized


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _archive_member(
    archive: tarfile.TarFile,
    *,
    relative_path: str,
    payload: bytes,
) -> None:
    info = tarfile.TarInfo(name=relative_path)
    info.size = len(payload)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(payload))


def build_deterministic_archive(source: Path, destination: Path) -> str:
    files = sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and path.relative_to(source).as_posix() != "publish.json"
    )
    if not files:
        raise RuntimeError(f"no files found under {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            mtime=0,
        ) as compressed:
            with tarfile.open(
                mode="w",
                fileobj=compressed,
                format=tarfile.PAX_FORMAT,
            ) as archive:
                for path in files:
                    relative = path.relative_to(source).as_posix()
                    _archive_member(
                        archive,
                        relative_path=relative,
                        payload=path.read_bytes(),
                    )

    return _sha256_bytes(destination.read_bytes())


def _dataset_prefix(
    *,
    inventory_sha256: str,
    policy_sha256: str,
    code_revision: str,
) -> str:
    inventory = _require_hex(
        inventory_sha256,
        length=64,
        label="inventory_sha256",
    )
    policy = _require_hex(
        policy_sha256,
        length=64,
        label="policy_sha256",
    )
    revision = _require_hex(
        code_revision,
        length=40,
        label="code_revision",
    )
    return f"{BASE_PREFIX}/{inventory}/{policy}/{revision}"


def _head_metadata(store: Any, key: str) -> dict[str, str] | None:
    try:
        response = store.client.head_object(
            Bucket=store.config.bucket,
            Key=key,
        )
    except Exception as exc:
        if store.is_not_found(exc):
            return None
        raise
    metadata = response.get("Metadata") if isinstance(response, dict) else None
    if not isinstance(metadata, dict):
        return {}
    return {
        str(name).lower(): str(value)
        for name, value in metadata.items()
    }


def _put_immutable_bytes(
    store: Any,
    *,
    key: str,
    payload: bytes,
    content_type: str,
    metadata: dict[str, str],
) -> None:
    payload_sha = _sha256_bytes(payload)
    expected_metadata = {
        **metadata,
        "payload-sha256": payload_sha,
    }
    existing = _head_metadata(store, key)
    if existing is not None:
        if existing.get("payload-sha256") != payload_sha:
            raise RuntimeError(
                f"immutable corpus object already exists with different bytes: {key}"
            )
        return
    store.put(
        key=key,
        content=payload,
        content_type=content_type,
        metadata=expected_metadata,
    )


def _put_immutable_file(
    store: Any,
    *,
    key: str,
    path: Path,
    content_type: str,
    metadata: dict[str, str],
) -> str:
    payload_sha = _sha256_bytes(path.read_bytes())
    expected_metadata = {
        **metadata,
        "payload-sha256": payload_sha,
    }
    existing = _head_metadata(store, key)
    if existing is not None:
        if existing.get("payload-sha256") != payload_sha:
            raise RuntimeError(
                f"immutable corpus object already exists with different bytes: {key}"
            )
        return payload_sha
    store.put_file(
        key=key,
        path=path,
        content_type=content_type,
        metadata=expected_metadata,
    )
    return payload_sha


def _document_archive_key(
    *,
    inventory_sha256: str,
    document_id: str,
    code_revision: str,
) -> str:
    prefix = _dataset_prefix(
        inventory_sha256=inventory_sha256,
        policy_sha256=_policy_sha256(),
        code_revision=code_revision,
    )
    doc_id = _require_hex(
        document_id,
        length=16,
        label="document_id",
    )
    return f"{prefix}/documents/{doc_id}.tar.gz"


def restore_document(
    *,
    output_dir: Path,
    inventory_sha256: str,
    document_id: str,
    code_revision: str,
) -> dict[str, str] | None:
    inventory_sha = _require_hex(
        inventory_sha256,
        length=64,
        label="inventory_sha256",
    )
    revision = _require_hex(
        code_revision,
        length=40,
        label="code_revision",
    )
    key = _document_archive_key(
        inventory_sha256=inventory_sha,
        document_id=document_id,
        code_revision=revision,
    )
    store = build_s3_object_store()
    metadata = _head_metadata(store, key)
    if metadata is None:
        return None

    expected_sha = _require_hex(
        metadata.get("payload-sha256", ""),
        length=64,
        label="payload-sha256",
    )
    client = cast(Any, store.client)
    response = client.get_object(
        Bucket=store.config.bucket,
        Key=key,
    )
    body = response["Body"].read()
    payload = body if isinstance(body, bytes) else bytes(body)
    actual_sha = _sha256_bytes(payload)
    if actual_sha != expected_sha:
        raise RuntimeError("restored document archive checksum mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as compressed:
        with tarfile.open(
            mode="r:",
            fileobj=compressed,
        ) as archive:
            members = archive.getmembers()
            for member in members:
                if not member.isfile():
                    raise RuntimeError(
                        "restored corpus archive contains non-file member"
                    )
                target = (output_dir / member.name).resolve()
                if output_dir.resolve() not in target.parents:
                    raise RuntimeError(
                        "restored corpus archive escaped output directory"
                    )
            archive.extractall(
                path=output_dir,
                members=members,
                filter="data",
            )

    document_path = output_dir / "document.json"
    if not document_path.is_file():
        raise RuntimeError("restored archive omitted document.json")
    document = json.loads(document_path.read_text(encoding="utf-8"))
    if str(document.get("policy_sha256")) != _policy_sha256():
        raise RuntimeError("restored archive policy SHA mismatch")
    if str(document.get("code_revision") or "") != revision:
        raise RuntimeError("restored archive code revision mismatch")

    receipt = {
        "key": key,
        "archive_sha256": actual_sha,
        "inventory_sha256": inventory_sha,
        "policy_sha256": _policy_sha256(),
        "code_revision": revision,
        "document_id": _require_hex(
            document_id,
            length=16,
            label="document_id",
        ),
        "source_pdf_sha256": str(document["source_pdf_sha256"]),
        "object_key": str(document["object_key"]),
    }
    (output_dir / "publish.json").write_text(
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt


def publish_document(
    *,
    input_dir: Path,
    inventory_sha256: str,
    document_id: str,
    code_revision: str,
    archive_path: Path,
) -> dict[str, str]:
    document_path = input_dir / "document.json"
    if not document_path.is_file():
        raise RuntimeError("document.json is required before publishing")

    document = json.loads(document_path.read_text(encoding="utf-8"))
    if not document.get("complete_scan"):
        raise RuntimeError("refusing to publish an incomplete document scan")
    if document.get("interrupted"):
        raise RuntimeError("refusing to publish an interrupted document scan")

    inventory_sha = _require_hex(
        inventory_sha256,
        length=64,
        label="inventory_sha256",
    )
    policy_sha = _require_hex(
        str(document["policy_sha256"]),
        length=64,
        label="policy_sha256",
    )
    document_revision = str(document.get("code_revision") or "")
    if document_revision and document_revision != code_revision:
        raise RuntimeError(
            "document code revision does not match publisher revision"
        )
    source_sha = _require_hex(
        str(document["source_pdf_sha256"]),
        length=64,
        label="source_pdf_sha256",
    )
    doc_id = _require_hex(document_id, length=16, label="document_id")
    prefix = _dataset_prefix(
        inventory_sha256=inventory_sha,
        policy_sha256=policy_sha,
        code_revision=code_revision,
    )

    archive_sha = build_deterministic_archive(input_dir, archive_path)
    key = f"{prefix}/documents/{doc_id}.tar.gz"
    store = build_s3_object_store()
    stored_sha = _put_immutable_file(
        store,
        key=key,
        path=archive_path,
        content_type="application/gzip",
        metadata={
            "inventory-sha256": inventory_sha,
            "policy-sha256": policy_sha,
            "source-pdf-sha256": source_sha,
            "document-id": doc_id,
        },
    )
    if stored_sha != archive_sha:
        raise RuntimeError("published archive checksum mismatch")
    return {
        "key": key,
        "archive_sha256": archive_sha,
        "inventory_sha256": inventory_sha,
        "policy_sha256": policy_sha,
        "code_revision": code_revision,
        "document_id": doc_id,
        "source_pdf_sha256": source_sha,
        "object_key": str(document["object_key"]),
    }


def publish_summary(
    *,
    summary_path: Path,
    inventory_path: Path,
    documents_root: Path,
    code_revision: str,
) -> dict[str, str]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory_sha = _require_hex(
        str(inventory["inventory_sha256"]),
        length=64,
        label="inventory_sha256",
    )
    if str(summary.get("inventory_sha256")) != inventory_sha:
        raise RuntimeError("aggregate inventory SHA does not match frozen inventory")

    policy_shas = {
        str(item.get("policy_sha256") or "")
        for item in summary["document_ranking"]
    }
    if len(policy_shas) != 1:
        raise RuntimeError("documents were evaluated under different policies")
    policy_sha = _require_hex(
        policy_shas.pop(),
        length=64,
        label="policy_sha256",
    )
    prefix = _dataset_prefix(
        inventory_sha256=inventory_sha,
        policy_sha256=policy_sha,
        code_revision=code_revision,
    )

    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(documents_root.rglob("publish.json"))
    ]
    if len(receipts) != int(summary["documents"]):
        raise RuntimeError(
            "durable document receipt count does not match aggregate"
        )

    expected_documents = {
        str(item["object_key"]): str(item["source_pdf_sha256"])
        for item in summary["document_ranking"]
    }
    observed_documents: set[str] = set()
    for receipt in receipts:
        if str(receipt.get("inventory_sha256")) != inventory_sha:
            raise RuntimeError("document receipt inventory SHA mismatch")
        if str(receipt.get("policy_sha256")) != policy_sha:
            raise RuntimeError("document receipt policy SHA mismatch")
        if str(receipt.get("code_revision")) != code_revision:
            raise RuntimeError("document receipt code revision mismatch")

        object_key = str(receipt.get("object_key") or "")
        source_sha = str(receipt.get("source_pdf_sha256") or "")
        if object_key in observed_documents:
            raise RuntimeError("duplicate durable document receipt")
        if expected_documents.get(object_key) != source_sha:
            raise RuntimeError(
                "document receipt source identity mismatch"
            )
        observed_documents.add(object_key)

    if observed_documents != set(expected_documents):
        raise RuntimeError(
            "durable document receipts do not cover aggregate documents"
        )

    store = build_s3_object_store()
    common_metadata = {
        "inventory-sha256": inventory_sha,
        "policy-sha256": policy_sha,
    }
    inventory_bytes = _canonical_json_bytes(inventory)
    summary_bytes = _canonical_json_bytes(summary)
    _put_immutable_bytes(
        store,
        key=f"{prefix}/inventory.json",
        payload=inventory_bytes,
        content_type="application/json",
        metadata=common_metadata,
    )
    _put_immutable_bytes(
        store,
        key=f"{prefix}/census-summary.json",
        payload=summary_bytes,
        content_type="application/json",
        metadata=common_metadata,
    )

    success = {
        "schema_version": 1,
        "inventory_sha256": inventory_sha,
        "policy_sha256": policy_sha,
        "code_revision": code_revision,
        "document_count": int(summary["documents"]),
        "total_pages": int(summary["total_pages"]),
    }
    success_key = f"{prefix}/_SUCCESS.json"
    _put_immutable_bytes(
        store,
        key=success_key,
        payload=_canonical_json_bytes(success),
        content_type="application/json",
        metadata=common_metadata,
    )
    return {
        "prefix": prefix,
        "success_key": success_key,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--output-dir", type=Path, required=True)
    restore.add_argument("--inventory-sha256", required=True)
    restore.add_argument("--document-id", required=True)
    restore.add_argument("--code-revision", required=True)

    document = subparsers.add_parser("document")
    document.add_argument("--input-dir", type=Path, required=True)
    document.add_argument("--inventory-sha256", required=True)
    document.add_argument("--document-id", required=True)
    document.add_argument("--code-revision", required=True)
    document.add_argument("--archive", type=Path, required=True)

    summary = subparsers.add_parser("summary")
    summary.add_argument("--summary", type=Path, required=True)
    summary.add_argument("--inventory", type=Path, required=True)
    summary.add_argument("--documents-root", type=Path, required=True)
    summary.add_argument("--code-revision", required=True)

    args = parser.parse_args()
    if args.command == "restore":
        result = restore_document(
            output_dir=args.output_dir,
            inventory_sha256=args.inventory_sha256,
            document_id=args.document_id,
            code_revision=args.code_revision,
        )
        print(
            json.dumps(
                {
                    "restored": result is not None,
                    "receipt": result,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "document":
        result = publish_document(
            input_dir=args.input_dir,
            inventory_sha256=args.inventory_sha256,
            document_id=args.document_id,
            code_revision=args.code_revision,
            archive_path=args.archive,
        )
        (args.input_dir / "publish.json").write_text(
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        result = publish_summary(
            summary_path=args.summary,
            inventory_path=args.inventory,
            documents_root=args.documents_root,
            code_revision=args.code_revision,
        )

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
