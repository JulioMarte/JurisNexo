# SCJ Principales Ling literal OCR — deterministic evidence analysis

Status: ROUTING EVIDENCE — divergence, output-quality and legal-span
signals only. This is not a semantic-correctness claim about the
transcriptions and does not overwrite the primary PDF source. The
legal-span disagreements are the priority review set for independent
(blind visual) adjudication; model output is never ground truth.

## Provenance

- Frozen plan SHA-256: `63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4`
- Model / provider: `inclusionai/ling-3.0-flash-vl` / `NovitaAI`
- Code revision: `fd3476226e3b240f00389cc7c58640a853759c7a`
- Object store: durable `benchmarks/scj-principales/ling-literal-ocr/v1` namespace,
  read offline from a local bucket mirror (no S3 calls).
- Analyzer: `backend/scripts/analyze_scj_ling_literal_ocr.py`

## Coverage

- Pages with Pass 1: **15900**
- Pages missing Pass 2: **0**
- Source classifications: `{'misaligned': 15855, 'no_native_text': 45}`

## Pass 1 vs Pass 2 change taxonomy

| Class | Pages |
| --- | ---: |
| exact | 12130 |
| whitespace | 301 |
| case | 8 |
| accent | 77 |
| punctuation | 1502 |
| digits | 8 |
| substantive | 1874 |

## Substantive divergence

- Substantive pages: **1874**
- Similarity min / p25 / median / p75 / max: 0.000 / 0.998 / 0.999 / 1.000 / 1.000

Largest rewrites (lowest similarity first):

| Page | Similarity | Length delta |
| --- | ---: | ---: |
| d938d11a7d76ce4c/31 | 0.000 | 29 |
| 90dc4bbaa296974b/3094 | 0.303 | -2 |
| d7e7b90bd53373b2/338 | 0.744 | 470 |
| 90dc4bbaa296974b/2284 | 0.748 | 3 |
| d938d11a7d76ce4c/626 | 0.803 | 14 |
| 90dc4bbaa296974b/3793 | 0.826 | -15 |
| 67a61b56bf76dce2/17 | 0.829 | -8 |
| 051995ccff4db8c9/7 | 0.860 | -13 |
| 90dc4bbaa296974b/1716 | 0.890 | -4 |
| 4adc376e55e426c3/1622 | 0.890 | -1 |

## Output-quality anomalies (routing only)

| Anomaly | Pass 1 | Pass 2 |
| --- | ---: | ---: |
| empty | 1 | 0 |
| wrapper_only | 0 | 1 |
| markdown_fence | 0 | 0 |
| ilegible_marker | 1 | 1 |
| non_transcription | 0 | 0 |
| repetition_loop | 0 | 0 |
| repeated_character | 0 | 0 |

Example pages:

- `pass1:empty`: d938d11a7d76ce4c/31
- `pass1:ilegible_marker`: 3b2f2ca96229de7a/115
- `pass2:ilegible_marker`: 3b2f2ca96229de7a/115
- `pass2:wrapper_only`: d938d11a7d76ce4c/31

## Legal-critical span disagreements

40 span-level disagreements across Pass 1 / Pass 2 — the priority review set.

| Page | Category | Pass 1 only | Pass 2 only |
| --- | --- | --- | --- |
| 051995ccff4db8c9/20 | identifier | CIOSO-ADMINISTRATIVO | CONTENCIOSO-ADMINISTRATIVO |
| 0ceeb4c10b996069/19 | reference | — | artículo 75 |
| 0ceeb4c10b996069/561 | reference | artículo 88 | — |
| 110b75b05b390937/506 | identifier | — | CONTENCIOSO-ADMINISTRATIVO |
| 1e4df311e3a52d9d/746 | identifier | CONTENCIOSO-TRIBUTARIO | TIOSO-TRIBUTARIO |
| 28910fd19775f243/607 | identifier | — | SSEN-00072 |
| 2a3a0bdb4c7b1062/327 | identifier | CONTENCIOSO-ADMINISTRATIVO | CONTENCIOSO-ADMINISTRA |
| 2b7f5a47d6428b77/122 | year | — | 2008 |
| 2b7f5a47d6428b77/141 | year | — | 2007 |
| 4adc376e55e426c3/1528 | identifier | SSEN-00069 | SSEN-000069 |
| 4adc376e55e426c3/2742 | year | — | 1943 |
| 5a93756aaa0a524c/527 | reference | artículo 88 | — |
| 67a61b56bf76dce2/6 | identifier | SCJJ-SS-22-0516 | SCJ-SS-22-0516 |
| 67a61b56bf76dce2/23 | identifier | SS-ENL-00002 | ENL-00002 |
| 67a61b56bf76dce2/84 | identifier | SSEN-00658 | — |
| 8796f27bd2673ccd/145 | reference | artículo 10 | — |
| 8796f27bd2673ccd/326 | year | 1953 | — |
| 8b3260dd383ad2ec/353 | identifier | EPEN-00341 | — |
| 8b3260dd383ad2ec/407 | identifier | SCJ-SS-25 | SCJ-SS-25-0739 |
| 90dc4bbaa296974b/1312 | year | 1997 | — |
| 90dc4bbaa296974b/1361 | identifier | SSEN-00064 | — |
| 90dc4bbaa296974b/1390 | money | — | RD$67,920.00 |
| 90dc4bbaa296974b/1886 | identifier | — | LC6PA-GA1720019140 |
| 90dc4bbaa296974b/1898 | identifier | — | SSEN-000315 |
| 90dc4bbaa296974b/1987 | money | RD$ 1,000.000.00 | RD$ 1,000,000.00 |
| 90dc4bbaa296974b/2337 | money | RD$5,000,000.00 | RD$5,000.000.00 |
| 90dc4bbaa296974b/2572 | year | 2021 | — |
| 90dc4bbaa296974b/2638 | money | RD$2,000.00.. | RD$2,000.00. |
| 90dc4bbaa296974b/3094 | identifier | — | SSEN-00591 |
| 90dc4bbaa296974b/3225 | identifier | — | SSEN-00117 |
| 90dc4bbaa296974b/3607 | identifier | — | GO-MEZ |
| 90dc4bbaa296974b/3727 | identifier | — | SEGUN-DO |
| 90dc4bbaa296974b/3744 | identifier | SSEN-00419 | — |
| 9723843bd087c416/898 | money | 22,183,832.64, pesos | — |
| d99d782ff681d830/90 | identifier | SCI-PS-22-1667, SCI-PS-22-3542 | SCJ-PS-22-1667, SCJ-PS-22-3542 |
| e33f4eceb6b2089c/350 | reference | artículo 3 | artículos 3 |
| e33f4eceb6b2089c/528 | identifier | SCI-SS-24-1199 | SCJ-SS-24-1199 |
| e33f4eceb6b2089c/626 | year | — | 2013 |
| fc71c5a4d965486a/706 | identifier | — | SASS-00164 |
| fc71c5a4d965486a/729 | money | RD$150,000,00 | RD$150,000.00 |

## Runtime and provenance

- Returned model mismatches: 0
- Returned provider mismatches: 0
- Truncation suspects: 0
- Render pixel-verified pairs: 11611
- Render legacy-unverified pairs: 4289
- Completion tokens total: 23884291
- Cost total USD: 2.6055758134
- Cost pass 1 / pass 2 USD: 1.1764358984 / 1.4291399150

## Per-document detail

| Document | Pages | Changed | Substantive | Legal | Anomalies | Cost USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 051995ccff4db8c9 | 130 | 35 | 23 | 1 | 0 | 0.028599 |
| 05faaf62d064359e | 96 | 13 | 5 | 0 | 0 | 0.009550 |
| 09a126d58fa421d2 | 143 | 12 | 8 | 0 | 0 | 0.016290 |
| 0ceeb4c10b996069 | 133 | 13 | 11 | 2 | 0 | 0.016727 |
| 110b75b05b390937 | 142 | 26 | 10 | 1 | 0 | 0.018606 |
| 1e4df311e3a52d9d | 181 | 25 | 17 | 1 | 0 | 0.025022 |
| 28910fd19775f243 | 199 | 30 | 18 | 1 | 0 | 0.030076 |
| 2a3a0bdb4c7b1062 | 84 | 11 | 9 | 1 | 0 | 0.008122 |
| 2b7f5a47d6428b77 | 644 | 182 | 82 | 2 | 0 | 0.108059 |
| 31c81cc7791d3c93 | 113 | 28 | 18 | 0 | 0 | 0.016848 |
| 392c41e4c5908f0e | 1296 | 210 | 116 | 0 | 0 | 0.228384 |
| 3b2f2ca96229de7a | 1028 | 149 | 78 | 0 | 2 | 0.181660 |
| 400555c52f375fc9 | 102 | 10 | 7 | 0 | 0 | 0.012425 |
| 423a7a8e577e60ac | 126 | 15 | 14 | 0 | 0 | 0.015009 |
| 4adc376e55e426c3 | 2884 | 932 | 390 | 2 | 0 | 0.487018 |
| 56368abb248c8bcb | 111 | 22 | 14 | 0 | 0 | 0.017476 |
| 5a93756aaa0a524c | 129 | 14 | 5 | 1 | 0 | 0.015841 |
| 67a61b56bf76dce2 | 236 | 49 | 28 | 3 | 0 | 0.035906 |
| 68a193128e8f0096 | 163 | 22 | 9 | 0 | 0 | 0.019968 |
| 8796f27bd2673ccd | 647 | 141 | 75 | 2 | 0 | 0.115716 |
| 8b3260dd383ad2ec | 445 | 59 | 25 | 2 | 0 | 0.076387 |
| 90dc4bbaa296974b | 3874 | 1180 | 546 | 14 | 0 | 0.678614 |
| 9723843bd087c416 | 225 | 50 | 23 | 1 | 0 | 0.035763 |
| 9986704b219f0850 | 158 | 35 | 20 | 0 | 0 | 0.019928 |
| a41f53009dc06066 | 94 | 14 | 10 | 0 | 0 | 0.009262 |
| bb216b7baf34bdab | 74 | 4 | 3 | 0 | 0 | 0.007017 |
| c444cf873b12bbd1 | 77 | 8 | 5 | 0 | 0 | 0.008819 |
| c8e9bc0160aaef3f | 73 | 13 | 9 | 0 | 0 | 0.006958 |
| d7e7b90bd53373b2 | 181 | 31 | 19 | 0 | 0 | 0.024921 |
| d938d11a7d76ce4c | 154 | 22 | 8 | 0 | 2 | 0.019459 |
| d99d782ff681d830 | 206 | 45 | 30 | 1 | 0 | 0.033248 |
| dbffcb165acabc47 | 158 | 25 | 9 | 0 | 0 | 0.019985 |
| e13ead3753fcd5e1 | 144 | 26 | 15 | 0 | 0 | 0.022682 |
| e33f4eceb6b2089c | 195 | 44 | 26 | 3 | 0 | 0.029326 |
| f82899ec948c960c | 191 | 29 | 18 | 0 | 0 | 0.024667 |
| fc71c5a4d965486a | 1064 | 246 | 171 | 2 | 0 | 0.181237 |

## Reproduction

```text
python backend/scripts/analyze_scj_ling_literal_ocr.py \
  --plan-sha 63f0ac73fa659a67bca79c20dbf1bde5e18a99f560c0bef6f50de10c51df8cc4 \
  --output <dir> [--object-root <local-mirror>]
```

Without `--object-root` the analyzer reads the configured S3-compatible durable store; with it, a local directory mirroring object-store keys. Results are deterministic for the frozen plan. A new model, provider or plan is a new evidence generation.
