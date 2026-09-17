# V4 known rollout risks

- A populated database containing `legal_propositions.proposition_type` values `issue`, `material_fact` or `procedural_fact` will be intentionally blocked by migration `0046`; those rows require explicit evidence-preserving conversion.
- Application code outside the current repository may still depend on `disposition_targets` or `disposition_effect_concepts.target_type`; private deployment must inventory those callers before migration.
- Shared `legal_concepts` is intentionally introduced only for new V4 categories. Mixing it mechanically with mature specialized concept registries would add complexity rather than remove it.
- `disposition_effect_argument_rules` is descriptive baseline grammar, not a complete enforcement engine. PostgreSQL still enforces shape, references and procedural context; jurisdiction-specific semantic completeness remains an extraction/audit responsibility unless a future invariant justifies stronger DB enforcement.
- The branch proves fresh-schema behavior through CI. A private VPS database still needs a restored production-like staging upgrade before production deployment.
