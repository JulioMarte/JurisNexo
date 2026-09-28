# Running expensive CI locally

Some JurisNexo validation workloads are better suited to a developer workstation than GitHub-hosted runners. In particular, exhaustive OCR over tens of thousands of pages is CPU-heavy, long-running, and does not benefit from a GitHub Actions timeout.

The repository therefore exposes the underlying checks through `scripts/local_ci.py`. This is deliberately not an Actions emulator: GitHub workflows remain orchestration, while the actual checks are ordinary repository commands that can run in either environment.

## Prerequisites

Use Python 3.13 and install the backend plus development/runtime dependencies needed by the workload:

```bash
python -m pip install -e ./backend
python -m pip install pytest==9.1.1 ruff boto3==1.43.93 pypdfium2==5.13.0 pillow==12.3.0
```

Install Tesseract OCR and Spanish + English language packs.

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

macOS with Homebrew:

```bash
brew install tesseract tesseract-lang
```

Windows: install Tesseract OCR, ensure `tesseract.exe` is on `PATH`, and verify that `spa` and `eng` traineddata are installed. Then verify:

```bash
tesseract --version
tesseract --list-langs
```

The language list must contain `spa` and `eng`.

## Credentials

The SCJ census reads the existing S3-compatible object store. Set the same environment variables used by CI:

- `JURISNEXO_S3_BUCKET`
- `JURISNEXO_S3_ENDPOINT_URL`
- `JURISNEXO_S3_REGION`
- `JURISNEXO_S3_ACCESS_KEY_ID`
- `JURISNEXO_S3_SECRET_ACCESS_KEY`

Do not commit these values.

PowerShell example:

```powershell
$env:JURISNEXO_S3_BUCKET="..."
$env:JURISNEXO_S3_ENDPOINT_URL="..."
$env:JURISNEXO_S3_REGION="..."
$env:JURISNEXO_S3_ACCESS_KEY_ID="..."
$env:JURISNEXO_S3_SECRET_ACCESS_KEY="..."
```

Bash/zsh example:

```bash
export JURISNEXO_S3_BUCKET='...'
export JURISNEXO_S3_ENDPOINT_URL='...'
export JURISNEXO_S3_REGION='...'
export JURISNEXO_S3_ACCESS_KEY_ID='...'
export JURISNEXO_S3_SECRET_ACCESS_KEY='...'
```

## Discover local checks

```bash
python scripts/local_ci.py list
```

Current profiles include the normalization contract and backend quality/unit suite. More GitHub workflows should be migrated to this pattern when their underlying command is useful locally; do not duplicate workflow YAML behavior in Python.

## Run the SCJ text-layer census

Start a fresh census:

```bash
python scripts/local_ci.py census
```

Default durable state lives under `.local-ci/`:

- `.local-ci/scj-census/pages-000.jsonl`: append-only page evidence/checkpoint
- `.local-ci/scj-census/summary-000.json`: current summary
- `.local-ci/pdf-cache/`: cached source PDFs

The cache prevents repeated S3 downloads. The JSONL is written after every completed page.

Pressing Ctrl+C requests a graceful stop after the current page. Resume later with:

```bash
python scripts/local_ci.py census --resume
```

Never delete or edit the JSONL while resuming. If you intentionally want a clean rerun, move/delete `.local-ci/scj-census` first. Keeping the PDF cache is safe.

The runner prints throughput and category counts periodically. The final summary uses the same strict visual-reference policy as the benchmark gold admission gate. This census is evidence collection; the production routing thresholds will be calibrated separately rather than silently weakening the gold policy.

## Run CI-style profiles locally

```bash
python scripts/local_ci.py run normalization-contract
python scripts/local_ci.py run backend-quality
```

These commands fail immediately when an underlying command fails and return a non-zero process exit code, making them suitable for local development scripts as well as future self-hosted CI.

## Design rules

1. GitHub Actions should orchestrate; business/test logic belongs in repository scripts.
2. Long workloads must checkpoint and resume.
3. Paid LLM benchmarks remain explicitly opt-in and are not part of the default local quality suite.
4. Local and GitHub runs must call the same underlying Python modules and tests.
5. Results needed for scientific comparison should record tool/model versions and immutable source hashes; raw heavyweight evidence can remain outside Git.
