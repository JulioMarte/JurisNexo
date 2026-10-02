from __future__ import annotations
import importlib.util
from pathlib import Path
PATH=Path(__file__).parents[2]/"scripts"/"scj_principales_ling_ocr.py"
SPEC=importlib.util.spec_from_file_location("scj_principales_ling_ocr",PATH)
assert SPEC and SPEC.loader
mod=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mod)
def test_contract_pins_ling_novita_and_twenty_workers()->None:
    assert mod.MODEL=="inclusionai/ling-3.0-flash-vl"
    assert mod.PROVIDER=="novita"
    assert mod.WORKERS==20
    assert mod.PENDING=={"misaligned","no_native_text"}
def test_evidence_key_is_page_and_pass_specific()->None:
    assert mod._key("generation","a"*64,0,2).endswith("/"+"a"*64+"/pages/000001/pass-2.json")
def test_second_pass_is_adversarial_and_image_authoritative()->None:
    assert "image is the authority" in mod.PASS2
    assert "FIRST-PASS OCR DRAFT" in mod.PASS2
def test_provider_disables_fallbacks()->None:
    provider=mod._provider("test-key")
    assert provider.provider_order==("novita",)
    assert provider.allow_provider_fallbacks is False
    assert provider.reasoning_effort=="none"
