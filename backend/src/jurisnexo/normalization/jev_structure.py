from __future__ import annotations

from dataclasses import dataclass

from jurisnexo.model_providers.contracts import JsonObject, ModelProviderError
from jurisnexo.normalization.jev_answers import choice_probability, noul_probability


@dataclass(frozen=True, slots=True)
class StructureProbabilities:
    index: float
    judgment: float
    front_matter: float
    other: float
    uncertain: float
    decision_start: float
    decision_end: float


def build_structure_questions(*, record_ids: tuple[str, ...]) -> dict[str, JsonObject]:
    questions: dict[str, JsonObject] = {}
    for record_id in record_ids:
        questions[f"{record_id}__page_role"] = {
            "type": "choice",
            "instructions": (
                f'For record "{record_id}", classify the editorial/legal role of '
                "the page excerpt. Use only observable text; do not infer missing pages."
            ),
            "criteria": {
                "index": "A table of contents, sumario, index, or list of decisions with page references.",
                "judgment": "Substantive text belonging to a judicial decision or judgment.",
                "front_matter": "Cover, title page, publication metadata, preface, or other front matter.",
                "other": "Neither an index, judgment, nor front matter.",
                "uncertain": "The excerpt is insufficient or ambiguous.",
            },
        }
        questions[f"{record_id}__decision_start"] = {
            "type": "noul",
            "instructions": f'Does record "{record_id}" contain strong evidence that a judicial decision starts on this page?',
            "true_when": "A decision heading, court formula, decision number/date, parties, or equivalent opening structure is visible.",
            "false_when": "The page is continuation text, index/front matter, or lacks a decision-opening signal.",
        }
        questions[f"{record_id}__decision_end"] = {
            "type": "noul",
            "instructions": f'Does record "{record_id}" contain strong evidence that a judicial decision ends on this page?',
            "true_when": "A dispositive ending, signatures, certification, closing formula, or transition to the next decision is visible.",
            "false_when": "The page is continuation text, index/front matter, or lacks a decision-ending signal.",
        }
    return questions


def parse_structure_probabilities(
    answers: dict[str, JsonObject], *, record_id: str
) -> StructureProbabilities:
    role = _required(answers, f"{record_id}__page_role")
    start = _required(answers, f"{record_id}__decision_start")
    end = _required(answers, f"{record_id}__decision_end")
    return StructureProbabilities(
        index=choice_probability(role, "index"),
        judgment=choice_probability(role, "judgment"),
        front_matter=choice_probability(role, "front_matter"),
        other=choice_probability(role, "other"),
        uncertain=choice_probability(role, "uncertain"),
        decision_start=noul_probability(start),
        decision_end=noul_probability(end),
    )


def _required(answers: dict[str, JsonObject], key: str) -> JsonObject:
    answer = answers.get(key)
    if answer is None:
        raise ModelProviderError(f"decision response omitted {key}")
    return answer
