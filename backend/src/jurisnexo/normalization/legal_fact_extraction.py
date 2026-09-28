from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject, JsonValue

LEGAL_FACT_FIELDS: tuple[str, ...] = (
    "dates",
    "money",
    "articles",
    "laws",
    "decrees",
    "resolutions",
    "gaceta_official",
    "rnc",
    "cedulas",
    "matriculas",
    "cadastre",
    "case_ids",
    "citations",
)

LEGAL_FACT_SCHEMA: JsonObject = {
    "type": "object",
    "additionalProperties": False,
    "required": list(LEGAL_FACT_FIELDS),
    "properties": {
        field: {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 100,
        }
        for field in LEGAL_FACT_FIELDS
    },
}


def build_legal_fact_prompt(text: str) -> str:
    return (
        "Extract only legal facts that are explicitly present in the page text below. "
        "Do not infer, complete, correct, or normalize a value that is not written in the text. "
        "Return every distinct visible value for each requested field. "
        "Use the source wording for each value; use [] when the field is absent. "
        "A value may appear in more than one field when the schemas genuinely overlap "
        "(for example an SCJ identifier may also be a citation).\n\n"
        "PAGE TEXT:\n"
        f"{text}"
    )


def normalize_fact(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def validate_legal_fact_payload(value: Mapping[str, object]) -> dict[str, list[str]]:
    missing = [field for field in LEGAL_FACT_FIELDS if field not in value]
    extras = sorted(set(value) - set(LEGAL_FACT_FIELDS))
    if missing or extras:
        raise ValueError(f"legal fact payload mismatch: missing={missing}, extras={extras}")
    result: dict[str, list[str]] = {}
    for field in LEGAL_FACT_FIELDS:
        raw = value[field]
        if not isinstance(raw, list):
            raise ValueError(f"legal fact field {field!r} must be an array")
        if len(raw) > 100:
            raise ValueError(f"legal fact field {field!r} exceeds 100 values")
        values: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(f"legal fact field {field!r} contains non-string value")
            cleaned = " ".join(item.split())
            if not cleaned:
                raise ValueError(f"legal fact field {field!r} contains an empty value")
            values.append(cleaned)
        result[field] = values
    return result


@dataclass(frozen=True, slots=True)
class FieldExtractionScore:
    expected: int
    predicted: int
    matched: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        return 1.0 if self.predicted == 0 and self.expected == 0 else (
            0.0 if self.predicted == 0 else self.matched / self.predicted
        )

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 0.0 if total == 0 else 2 * self.precision * self.recall / total


@dataclass(frozen=True, slots=True)
class LegalFactExtractionScore:
    fields: dict[str, FieldExtractionScore]
    expected: int
    predicted: int
    matched: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        return 1.0 if self.predicted == 0 and self.expected == 0 else (
            0.0 if self.predicted == 0 else self.matched / self.predicted
        )

    @property
    def recall(self) -> float:
        return 1.0 if self.expected == 0 else self.matched / self.expected

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 0.0 if total == 0 else 2 * self.precision * self.recall / total

    @property
    def exact_page(self) -> bool:
        return self.false_positive == 0 and self.false_negative == 0

    def to_json_dict(self) -> JsonObject:
        return {
            "expected": self.expected,
            "predicted": self.predicted,
            "matched": self.matched,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "exact_page": self.exact_page,
            "fields": {
                field: {
                    "expected": item.expected,
                    "predicted": item.predicted,
                    "matched": item.matched,
                    "false_positive": item.false_positive,
                    "false_negative": item.false_negative,
                    "precision": item.precision,
                    "recall": item.recall,
                    "f1": item.f1,
                }
                for field, item in self.fields.items()
            },
        }


def score_legal_fact_extraction(
    *,
    expected: Mapping[str, list[str]],
    predicted: Mapping[str, list[str]],
) -> LegalFactExtractionScore:
    expected_checked = validate_legal_fact_payload(expected)
    predicted_checked = validate_legal_fact_payload(predicted)
    field_scores: dict[str, FieldExtractionScore] = {}
    total_expected = total_predicted = total_matched = 0
    total_fp = total_fn = 0
    for field in LEGAL_FACT_FIELDS:
        # The task is distinct-value extraction, so repeated source mentions and
        # repeated model values must not inflate either recall or precision.
        expected_values = Counter({normalize_fact(value): 1 for value in expected_checked[field]})
        predicted_values = Counter({normalize_fact(value): 1 for value in predicted_checked[field]})
        matched = sum((expected_values & predicted_values).values())
        expected_count = sum(expected_values.values())
        predicted_count = sum(predicted_values.values())
        fp = predicted_count - matched
        fn = expected_count - matched
        field_scores[field] = FieldExtractionScore(
            expected=expected_count,
            predicted=predicted_count,
            matched=matched,
            false_positive=fp,
            false_negative=fn,
        )
        total_expected += expected_count
        total_predicted += predicted_count
        total_matched += matched
        total_fp += fp
        total_fn += fn
    return LegalFactExtractionScore(
        fields=field_scores,
        expected=total_expected,
        predicted=total_predicted,
        matched=total_matched,
        false_positive=total_fp,
        false_negative=total_fn,
    )


def empty_legal_fact_payload() -> dict[str, list[str]]:
    return {field: [] for field in LEGAL_FACT_FIELDS}


def schema_as_json_value() -> JsonValue:
    return LEGAL_FACT_SCHEMA
