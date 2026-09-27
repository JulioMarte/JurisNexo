# SCJ Principales visual benchmark — 2026-09-27

## Purpose

Freeze the evidence from the 290-page visual normalization benchmark so architectural decisions do not depend on expiring GitHub Actions artifacts.

The gold pages were admitted only when native PDF text agreed with an independent Tesseract reading of the rendered page under the repository's strict visual-reference policy. All models received the same frozen page images and references.

## Corpus and run

- Source corpus: SCJ `principales-sentencias`
- Corpus inventory observed during calibration: 36 PDFs, 29,811 PDF pages
- Alignment audit: 600 candidate pages
- Gold pages admitted: 290 (48.33% of the deliberately eligible candidate sample; this is **not** an estimate of whole-corpus alignment)
- Benchmark pages per complete model: 290
- Reasoning setting: `high`
- Harness branch lineage: `feat/universal-normalization-control-plane-v3`
- Benchmark workflow commit used for the four-model run: `bb8226b7c42751c9167546b6f3aa67cbe466b3df`
- Canonical retained evidence: GitHub Actions artifacts from the benchmark run; artifacts are evidence, not the permanent record.

## Results

| Model | Completed | Mean WER | Legal-critical recall | Observed cost | Median latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| `deepseek/deepseek-v4.1-flash` | 290/290 | 1.554% | 99.316% | $0.1414 | 6.17 s |
| `openai/gpt-6-luna` | 290/290 | 1.549% | 99.471% | $0.2598 | 10.35 s |
| `inclusionai/ling-3.0-flash-vl` | 290/290 | 2.035% | 97.573% | $0.0722 | 23.51 s |
| `google/gemini-2.5-flash-lite` | 242/290 | 4.782% on completed responses | 97.125% on completed responses | $0.1702 partial | 6.79 s on completed responses |

Gemini's 48 failures were responses routed to Google AI Studio with no usable textual content. The successful subset also contained severe transcription outliers, so its aggregate quality numbers are not directly comparable to the three 290/290 runs.

## Page-level observations

DeepSeek and Luna were essentially tied on mean WER. Luna preserved slightly more legal-critical material, while DeepSeek was materially cheaper and faster. In the direct legal-critical comparison, DeepSeek lost at least one detected critical element on 8/290 pages and Luna on 4/290 pages.

Ling cost roughly half as much as DeepSeek, but DeepSeek won substantially more page-level comparisons. Ling lost at least one detected legal-critical element on 14/290 pages and had six pages below 50% legal-critical recall. Ling was also much slower in this configuration: median 23.51 s versus 6.17 s for DeepSeek. Its `high` reasoning configuration consumed unusually large thinking-token volume, so a lower-reasoning Ling experiment remains a valid future question; this report does not assume it will improve quality.

## Cost extrapolation if every one of 29,811 pages were sent to a model

These are simple extrapolations from observed per-page spend, not a production budget:

| Model | Approximate cost for 29,811 pages |
| --- | ---: |
| Ling 3.0 Flash VL | $7.42 |
| DeepSeek V4.1 Flash | $14.53 |
| GPT-6 Luna | $26.71 |
| Gemini 2.5 Flash-Lite | $20.97 based only on successful responses; operationally invalid until failures are resolved |

The exhaustive text-layer census introduced after this benchmark is the authoritative way to estimate how many pages actually require multimodal normalization. Do not multiply the 48.33% gold admission rate by 29,811: the 600-page calibration was sampled from deliberately eligible pages and is not representative of all corpus pages.

## Reproducibility contract

The benchmark is reproducible only when all models consume the same frozen manifest/images, the visual-reference admission thresholds remain unchanged, provider/model identifiers and reasoning settings are recorded, and costs are taken from provider-reported run metadata where available. A future benchmark that changes any of those dimensions is a new experiment rather than a continuation of this result.
