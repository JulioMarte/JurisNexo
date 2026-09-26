from __future__ import annotations

from jurisnexo.normalization.jev_quality import (
    JevRoutingPolicy,
    TextQualityProbabilities,
)


def _p(
    *,
    acceptable: float,
    material_error: float = 0.0,
    uncertain: float = 0.0,
    critical: float = 0.0,
    visual: float = 0.0,
) -> TextQualityProbabilities:
    return TextQualityProbabilities(
        acceptable=acceptable,
        material_error=material_error,
        uncertain=uncertain,
        legal_critical_damage=critical,
        needs_visual_review=visual,
    )


def test_policy_keeps_high_confidence_clean_text_on_cheap_path() -> None:
    policy = JevRoutingPolicy()
    assert policy.recommend(_p(acceptable=0.99)) == "accept"
    assert policy.recommend(_p(acceptable=0.93)) == "sentinel"


def test_policy_escalates_visible_damage_before_auto_accept() -> None:
    policy = JevRoutingPolicy()
    assert (
        policy.recommend(
            _p(
                acceptable=0.99,
                material_error=0.30,
            )
        )
        == "deepseek_review"
    )


def test_critical_damage_lowers_visual_escalation_threshold() -> None:
    policy = JevRoutingPolicy(
        visual_min_probability=0.40,
        critical_visual_multiplier=0.50,
    )
    assert (
        policy.recommend(
            _p(
                acceptable=0.75,
                critical=0.8,
                visual=0.25,
            )
        )
        == "visual_review"
    )


def test_uncertainty_can_force_human_review() -> None:
    policy = JevRoutingPolicy(human_min_uncertain=0.55)
    assert (
        policy.recommend(
            _p(
                acceptable=0.30,
                uncertain=0.60,
            )
        )
        == "human_review"
    )



def test_shadow_policy_never_executes_auto_routing() -> None:
    policy = JevRoutingPolicy()
    probabilities = _p(acceptable=0.999)

    assert policy.recommend(probabilities) == "accept"
    assert policy.route(probabilities) == "shadow_observe"


def test_active_policy_requires_explicit_promotion() -> None:
    policy = JevRoutingPolicy(promotion_state="active")
    probabilities = _p(acceptable=0.999)

    assert policy.route(probabilities) == "accept"
