import pytest

from jurisnexo.acquisition.official_corpus import object_key_for

DIGEST = "a" * 64


def test_scj_decision_object_key_is_jurisdiction_aware() -> None:
    assert object_key_for(source="supreme_court", collection="decisions", sha256=DIGEST) == (
        "jurisdictions/do/scj/decisions/aa/" + DIGEST + ".pdf"
    )


def test_scj_bulletin_object_key_separates_collection_without_changing_identity() -> None:
    assert object_key_for(source="supreme_court", collection="bulletins", sha256=DIGEST) == (
        "jurisdictions/do/scj/bulletins/aa/" + DIGEST + ".pdf"
    )


def test_tc_decision_object_key_uses_tc_namespace() -> None:
    assert object_key_for(source="constitutional_court", sha256=DIGEST) == (
        "jurisdictions/do/tc/decisions/aa/" + DIGEST + ".pdf"
    )


def test_object_key_rejects_path_injection_collection() -> None:
    with pytest.raises(ValueError, match="collection"):
        object_key_for(source="supreme_court", collection="../bulletins", sha256=DIGEST)


def test_object_key_rejects_noncanonical_digest() -> None:
    with pytest.raises(ValueError, match="sha256"):
        object_key_for(source="supreme_court", sha256="A" * 64)
