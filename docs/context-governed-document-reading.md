# Context-governed document reading

JurisNexo must not decide how much legal-document evidence to read by an arbitrary page count. Pages vary too much in text density. A 7-page limit can reject cheap evidence and still allow expensive evidence.

## Policy

Multi-page reads are allowed over any valid range. Before their text is placed in the parent agent context, the harness performs a token preflight:

1. count the parent agent's active prompt;
2. count the requested evidence;
3. calculate the projected parent context;
4. inline the evidence only when the projected context is within the configured parent soft limit.

The default parent soft limit is 120,000 tokens. This is a configurable policy value, not a property of `get_printed_pages()` and not a claim about a model's maximum context window.

For Gemini, JurisNexo uses the provider's `models.countTokens` tokenizer endpoint before injection. Providers without an exact counter use a conservative characters/4 estimate and must label that result as approximate.

The cumulative `max_total_tokens` run budget remains separate. It is an economic/safety guardrail. Active context capacity and cumulative paid token usage are different quantities and must not be conflated.

## Large range workflow

If a requested range would exceed the parent soft limit, the range text is not inserted into the parent context. The tool returns the active, requested, projected, and soft-limit token counts. The parent remains responsible for deciding what to do next.

The preferred order is:

1. narrow or search deterministically when strong anchors exist;
2. otherwise call `delegate_printed_pages(start, end, expected_description)` for focused semantic location;
3. never silently drop evidence or rewrite source pagination.

## DecisionLocatorAgent

The first delegated role is deliberately narrow. `DecisionLocatorAgent` only tries to locate where an expected decision starts within supplied printed pages. It does not interpret law or answer the user.

A delegated range is split recursively only when its rendered prompt exceeds the delegated context soft limit. Splitting therefore depends on token fit rather than page count.

Each locator response must cite only printed pages actually supplied to that subagent. The harness rejects candidate starts or evidence pages outside the inspected chunk. The parent receives compact findings plus the concrete cited pages, rendered again with view-page and source provenance. This preserves trace-backed scoring without returning the entire delegated corpus to the parent.

## Important limitations

The current implementation does not yet compact an already-large parent history. It prevents a new large range from making the context worse, but future work should add evidence compaction/summarization with provenance retention.

The fallback characters/4 counter is only an estimate. Exact provider tokenizers should be implemented for every production model provider.

Delegation can increase total model cost substantially. The run-level token budget therefore remains necessary even though fixed page limits are removed.

The 120,000-token default is intentionally configurable and must be benchmarked. It should not be treated as a universal optimum. Different models and tasks may justify different working-context policies.
