# SCJ Principales Ling literal OCR — 2026-10-03

Status: FULL CORPUS RUN COMPLETE — runtime and provenance evidence only; independent
semantic adjudication is still pending.

## Purpose

Freeze the current state of the corpus-wide Ling literal-OCR lane so the result
does not depend on expiring GitHub Actions artifacts, and record exactly what the
completed generation proves and what it does not.

This document is operational benchmark evidence. It is **not** a claim that the
transcriptions are legally or textually correct, and it does not overwrite the
primary PDF source.

## Frozen plan and corpus

- Source corpus: SCJ `principales-sentencias`, durable text-layer census generation.
- Frozen plan SHA-256: `63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4`
- Documents: 36
- Target pages: 15,900 (`misaligned` 15,855 + `no_native_text` 45)
- Model: `inclusionai/ling-3.0-flash-vl`
- Provider: `NovitaAI`, provider fallback disabled
- Passes per page: 2 (literal, then adversarial)
- Plan identity is frozen: `worker_count = 20` is a historical hash field and is
  **not** the runtime concurrency.

## Async execution contract

- One shared `httpx.AsyncClient` per worker process with a **global** in-flight cap
  of up to 200 requests (`--max-concurrent-requests`); it is not 200 per plan worker.
- PDFium rendering is serialized on a single thread and feeds the async calls, so
  observed in-flight concurrency is lower than the cap.
- Model-call retries keep the prior policy: five attempts total with 1/2/4/8 s
  backoff. Object-store GET reads retry transient `ResponseStreamingError`/
  `IncompleteRead` failures and fail closed after the attempt budget.
- Corpus-wide Pass 1 and Pass 2 run as separate jobs so each pass has its own
  Actions timeout and a visible stage.

## Run provenance

- Workflow: `.github/workflows/scj-principales-ling-literal-ocr.yml`
- Branch: `fix/scj-ling-null-stop-response` (PR #137)
- Full-run commit: `3471912`
- Full run: `37094969170` (attempt 1)
- Canary before the full run: `37094058456` (200 fresh pages; 0 failures; US$0.0355)
- Prior interleaved run that this generation resumed over: `37026431085` (cancelled)

## Results

| Metric | Value |
| --- | ---: |
| Pages with both passes | **15,900 / 15,900** |
| Missing Pass 1 / Pass 2 | 0 / 0 |
| Model generations | **31,800** |
| Failed pages | **0** |
| Pages with retries | **0** |
| Output-truncation suspects (≥16,000 completion tokens) | 0 |
| Returned model | `inclusionai/ling-3.0-flash-vl` on 31,800/31,800 |
| Returned provider | `Novita` on 31,800/31,800 |
| Pass 1 completion tokens | 11,932,604 |
| Pass 2 completion tokens | 11,951,687 |
| Cost billed by this run | US$1.8698632526 |
| Cumulative generation cost | US$2.6055758134 |
| Pass 1 / Pass 2 cumulative cost | US$1.1764358984 / US$1.429139915 |
| Peak observed in-flight requests | 129 (cap 200) |
| Render pairs pixel-verified | 11,611 |
| Render pairs legacy-unverified (pre-pixel-hash records) | 4,289 |

Job durations: Pass 1 1 h 01 m 46 s, Pass 2 1 h 13 m 02 s, aggregate 4 h 46 m 10 s.

Adversarial pass: Pass 2 was byte-identical to Pass 1 on 12,130 pages (76.3 %)
and changed the text on 3,770 pages (23.7 %). A difference is the intended
behavior of the adversarial pass, not evidence of a defect.

## Per-document coverage and cost

`pages / pages where Pass 2 changed text / empty Pass 1 / empty Pass 2 / truncation
suspects / pages with retries / Pass 1 tokens / Pass 2 tokens / cost`

```text
051995ccff4db8c9   130 / 35  / 0 / 0 / 0 / 0 / 158580 / 175027 / 0.02859918
05faaf62d064359e    96 / 13  / 0 / 0 / 0 / 0 /  36767 /  36792 / 0.00954969
09a126d58fa421d2   143 / 12  / 0 / 0 / 0 / 0 /  65150 /  65162 / 0.01629044
0ceeb4c10b996069   133 / 13  / 0 / 0 / 0 / 0 /  71612 /  71637 / 0.01672679
110b75b05b390937   142 / 26  / 0 / 0 / 0 / 0 /  80141 /  80183 / 0.01860647
1e4df311e3a52d9d   181 / 25  / 0 / 0 / 0 / 0 / 112962 / 112902 / 0.02502222
28910fd19775f243   199 / 30  / 0 / 0 / 0 / 0 / 142371 / 142557 / 0.03007623
2a3a0bdb4c7b1062    84 / 11  / 0 / 0 / 0 / 0 /  32558 /  32607 / 0.00812232
2b7f5a47d6428b77   644 / 182 / 0 / 0 / 0 / 0 / 532443 / 532553 / 0.10805917
31c81cc7791d3c93   113 / 28  / 0 / 0 / 0 / 0 /  79325 /  79307 / 0.01684776
392c41e4c5908f0e  1296 / 210 / 0 / 0 / 0 / 0 / 844009 / 844209 / 0.22838442
3b2f2ca96229de7a  1028 / 149 / 0 / 0 / 0 / 0 / 667860 / 667986 / 0.18166015
400555c52f375fc9   102 / 10  / 0 / 0 / 0 / 0 /  52010 /  52081 / 0.01242544
423a7a8e577e60ac   126 / 15  / 0 / 0 / 0 / 0 /  60940 /  60938 / 0.01500872
4adc376e55e426c3  2884 / 932 / 0 / 0 / 0 / 0 / 2405675 / 2406041 / 0.48701802
56368abb248c8bcb   111 / 22  / 0 / 0 / 0 / 0 /  83867 /  83873 / 0.01747556
5a93756aaa0a524c   129 / 14  / 0 / 0 / 0 / 0 /  66443 /  66457 / 0.01584126
67a61b56bf76dce2   236 / 49  / 0 / 0 / 0 / 0 / 170804 / 171192 / 0.03590631
68a193128e8f0096   163 / 22  / 0 / 0 / 0 / 0 /  83844 /  83837 / 0.01996777
8796f27bd2673ccd   647 / 141 / 0 / 0 / 0 / 0 / 427911 / 428044 / 0.11571605
8b3260dd383ad2ec   445 / 59  / 0 / 0 / 0 / 0 / 275661 / 275590 / 0.07638756
90dc4bbaa296974b  3874 / 1180/ 0 / 0 / 0 / 0 / 3401368 / 3401465 / 0.67861357
9723843bd087c416   225 / 50  / 0 / 0 / 0 / 0 / 173560 / 173617 / 0.03576289
9986704b219f0850   158 / 35  / 0 / 0 / 0 / 0 /  84166 /  84130 / 0.01992772
a41f53009dc06066    94 / 14  / 0 / 0 / 0 / 0 /  35488 /  35555 / 0.00926230
bb216b7baf34bdab    74 /  4  / 0 / 0 / 0 / 0 /  26545 /  26561 / 0.00701739
c444cf873b12bbd1    77 /  8  / 0 / 0 / 0 / 0 /  34726 /  34708 / 0.00881919
c8e9bc0160aaef3f    73 / 13  / 0 / 0 / 0 / 0 /  27517 /  27573 / 0.00695743
d7e7b90bd53373b2   181 / 31  / 0 / 0 / 0 / 0 / 112339 / 112398 / 0.02492063
d938d11a7d76ce4c   154 / 22  / 1 / 0 / 0 / 0 /  82403 /  82426 / 0.01945878
d99d782ff681d830   206 / 45  / 0 / 0 / 0 / 0 / 162062 / 162355 / 0.03324846
dbffcb165acabc47   158 / 25  / 0 / 0 / 0 / 0 /  86319 /  87037 / 0.01998463
e13ead3753fcd5e1   144 / 26  / 0 / 0 / 0 / 0 / 109763 / 109771 / 0.02268160
e33f4eceb6b2089c   195 / 44  / 0 / 0 / 0 / 0 / 139397 / 139537 / 0.02932556
f82899ec948c960c   191 / 29  / 0 / 0 / 0 / 0 / 107296 / 107316 / 0.02466728
fc71c5a4d965486a  1064 / 246 / 0 / 0 / 0 / 0 / 898722 / 898263 / 0.18123691
```

## Anomalies requiring independent visual adjudication

These are observations, not confirmed errors. None is a runtime failure.

- `d938d11a7d76ce4c` page `31`: Pass 1 returned empty text and Pass 2 returned the
  wrapper `---BEGIN OCR---` / `---END OCR---`. That is not a transcription and is
  the single clearly invalid output in the generation.
- `3b2f2ca96229de7a` page `115`: both passes contain the `[ilegible]` marker for an
  unreadable fragment; expected behavior, but the image should confirm it.
- 3,770 pages where Pass 2 differs from Pass 1: the priority review set for
  measuring real adversarial correction.
- 4,289 render pairs are `legacy-unverified` because their durable Pass 1 records
  predate the decoded-pixel hash; their PNG checksum and source identity are intact.

## Known limitations

1. **Semantic fidelity is not certified.** This run proves coverage, source
   identity, pinned provider/model, both passes persisted, and exact cost. It does
   not prove the transcriptions are correct; that needs independent adjudication.
2. **The aggregate is slow.** It reconciles 15,900 pages with sequential
   object-store round-trips and took 4 h 46 m, close to the 6 h Actions job ceiling.
   It should be parallelized or made to skip redundant HEAD requests before the
   corpus grows.
3. **Rendering gates throughput.** With serialized PDFium, observed in-flight
   requests peaked at 129 despite the 200 cap.
4. Legacy render pairs remain unverified until regenerated under the current
   render-identity contract.

## Running the worker locally

The worker reads every object through one object-store boundary. Set
`JURISNEXO_LOCAL_OBJECT_ROOT` (or pass `--object-root`) to a directory that mirrors
object-store keys; the same tree holds the shared source PDFs and the census and
durable evidence, so `plan`, `worker` and `aggregate` run fully offline without S3
calls. The legacy `JURISNEXO_LOCAL_CORPUS_ROOT` / `--corpus-root` remain accepted
as aliases. Source PDFs are SHA-256-verified against the frozen plan, evidence
reads run the same per-page identity checks, and immutable writes are rejected
when the stored payload hash differs. See the "Running the Ling worker locally"
section of `docs/44-scj-principales-verified-corpus-census.md`.

Because a completed plan is fully resumable, re-running against a finished plan
restores durable observations with no model spend; real inference happens only for
page/pass observations that are not yet durable.

## Reproducibility contract

This result is reproducible only when the frozen plan SHA, the corpus generation,
the pinned provider/model, the two-pass prompts, the render scale, and the
provider-reported costs are unchanged. Changing the model, provider, prompt,
render scale, or pass structure is a new experiment, not a continuation of this
result. Runtime concurrency may vary without changing evidence identity.
