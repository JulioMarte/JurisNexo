# JurisNexo — Document Environment v1 and Agentic Discovery Baseline

## 1. Why this document exists

`docs/20-document-intelligence-and-structure-discovery.md` defines the target architecture. This document records the first measured Gemini baseline and the concrete v1 environment used to move from one-shot extraction toward bounded RLM-style exploration.

The governing rule remains:

> Model exploration produces hypotheses and evidence. It does not write canonical legal truth.

## 2. First live Gemini baseline

The first manual `Document discovery benchmark` run completed successfully on 2026-09-11 using:

```text
model: gemini-3.8-flash
thinking: medium
strategy: one-shot structured generation
fixture: synthetic legacy bulletin
```

Provider-reported usage:

```text
input tokens:       319
output tokens:      486
thinking tokens:  1,228
total tokens:     2,033
```

At the September 2026 introductory Gemini 3.8 Flash prices documented in `docs/21-google-gemini-model-selection-and-ci.md`, the run cost is roughly USD 0.0067.

The model correctly proposed:

- `bulletin` as the artifact class;
- an index on the first sampled page;
- `SENTENCIA DEL <fecha>` as a candidate case-start signal;
- decision date, expediente, and party extraction strategies;
- follow-up validation against the complete document rather than claiming the candidate rule was already proven.

This is encouraging but is not an accuracy result. The fixture is synthetic and small.

## 3. Runtime inconsistency discovered

The first manual benchmark resolved Python 3.14.7 because the workflow did not pin the interpreter even though the backend is developed and tested on Python 3.13.

Future model benchmarks must force Python 3.13 so model experiments and deterministic CI do not silently use different runtimes.

## 4. Document Environment v1

The first agent environment is intentionally read-only and smaller than the long-term design.

Supported tools:

```text
get_page(page_number)
get_pages(start_page, end_page)
search_text(query)
sample_pages(head|tail|even, count)
finish
```

Properties:

- physical pages are 1-based and remain explicit in every result;
- page output is character-bounded before being returned to the model;
- page-range reads have a hard maximum;
- text search is literal, case-insensitive, deterministic, and returns page provenance;
- sampling is deterministic;
- duplicate identical tool calls are detected;
- tool errors become bounded evidence instead of crashing the entire exploration loop when possible.

Not yet exposed:

```text
arbitrary Python
model-generated regex execution
network access
database access
canonical writes
```

Python and regex execution remain deferred until sandboxing and ReDoS/resource controls are explicit.

## 5. Agentic discovery loop v1

The v1 loop is provider-neutral and uses structured model outputs to choose the next operation.

```text
artifact pages
    -> environment summary + page 1 preview
    -> structured tool decision
    -> deterministic tool execution
    -> evidence transcript
    -> another structured tool decision
    -> ... bounded by budget
    -> final structured synthesis
    -> DocumentStructureHypothesis
```

The model cannot invent new tool names or arbitrary arguments outside the Pydantic schema.

Hard controls include:

- maximum model calls, including final synthesis;
- maximum cumulative provider-reported tokens;
- maximum prompt characters;
- maximum tool-output characters;
- maximum pages per range request;
- maximum text-search hits;
- output-token ceilings per decision and final synthesis.

If the provider reports cumulative usage above the declared token budget, the run fails rather than continuing silently.

## 6. Benchmark comparison contract

The manual workflow now supports:

```text
mode=one-shot
mode=agentic
```

Both use the same protected `llm-benchmark` Environment and `GEMINI_API_KEY` secret.

The first useful comparison should measure:

```text
structure correctness
pages actually inspected
model calls
input/output/thinking tokens
total estimated cost
latency
unresolved anomalies
quality of recommended validation actions
```

The agentic approach is justified only if selective inspection gives better structural reliability or scales better to large artifacts than one-shot context loading.

## 7. Next steps

After v1 passes deterministic CI:

1. run agentic discovery on the richer 25-page synthetic bulletin fixture;
2. compare its hypothesis and cost with one-shot discovery;
3. feed a real document whose structure is already known while hiding the existing parser rules;
4. measure whether the agent rediscovers boundaries and metadata grammar;
5. only then add candidate-index helpers, OCR/image diagnostics, or sandboxed programmatic execution.

No result from this environment is eligible for direct canonical promotion.
