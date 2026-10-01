#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKDIR="${OCR_HARD_WORKDIR:-$ROOT/.local/ocr-hard-rescue}"
PAGE_LIMIT="${OCR_HARD_PAGE_LIMIT:-500}"
SHARD_COUNT="${OCR_HARD_SHARD_COUNT:-5}"
PYTHON="${PYTHON:-python}"

usage() {
  cat <<'EOF'
Usage: benchmark/normalization/run_scj_ocr_hard_rescue_local.sh <prepare|ocr|aggregate|all>

Environment:
  OCR_HARD_WORKDIR      Working directory (default .local/ocr-hard-rescue)
  OCR_HARD_PAGE_LIMIT   Pages to freeze/process (default 500)
  OCR_HARD_SHARD_COUNT  Sequential local shards per engine (default 5)
  PYTHON                Python executable (default python)

Preparation requires the same JURISNEXO_S3_* credentials used by CI.
Install Tesseract + Spanish/English language data, RapidOCR/ONNX Runtime,
and PaddleOCR/PaddlePaddle before running the OCR phase.
EOF
}

prepare() {
  mkdir -p "$WORKDIR"
  "$PYTHON" "$ROOT/benchmark/normalization/prepare_scj_ocr_hard_rescue.py"     --output "$WORKDIR/prepared" --limit "$PAGE_LIMIT"
}

ocr() {
  local engine shard out
  for engine in tesseract rapidocr paddleocr; do
    mkdir -p "$WORKDIR/results/$engine"
    for ((shard=0; shard<SHARD_COUNT; shard++)); do
      out="$WORKDIR/results/$engine/shard-$shard"
      "$PYTHON" "$ROOT/benchmark/normalization/run_open_source_ocr_engine.py"         --engine "$engine"         --manifest "$WORKDIR/prepared/prepared-manifest.json"         --output "$out"         --shard-index "$shard"         --shard-count "$SHARD_COUNT"
    done
    args=()
    for ((shard=0; shard<SHARD_COUNT; shard++)); do
      args+=(--input "$WORKDIR/results/$engine/shard-$shard/predictions.jsonl")
    done
    "$PYTHON" "$ROOT/benchmark/normalization/merge_scj_ocr_hard_rescue_shards.py"       --engine "$engine" "${args[@]}"       --output "$WORKDIR/merged/$engine.jsonl" --expected "$PAGE_LIMIT"
  done
}

aggregate() {
  "$PYTHON" "$ROOT/benchmark/normalization/aggregate_scj_ocr_hard_rescue.py"     --manifest "$WORKDIR/prepared/prepared-manifest.json"     --tesseract "$WORKDIR/merged/tesseract.jsonl"     --rapidocr "$WORKDIR/merged/rapidocr.jsonl"     --paddleocr "$WORKDIR/merged/paddleocr.jsonl"     --output "$WORKDIR/adjudication"
  cat "$WORKDIR/adjudication/summary.json"
}

case "${1:-}" in
  prepare) prepare ;;
  ocr) ocr ;;
  aggregate) aggregate ;;
  all) prepare; ocr; aggregate ;;
  *) usage; exit 2 ;;
esac
