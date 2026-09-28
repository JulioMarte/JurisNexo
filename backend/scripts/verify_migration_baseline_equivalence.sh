#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PRE_BASELINE_COMMIT="${PRE_BASELINE_COMMIT:-998398d275081590a229f90eebb53f9abf1bd80c}"
OLD_DIR="$(mktemp -d)"
OLD_REPO="$OLD_DIR/pre-baseline"
OLD_PROJECT="jurisnexo-prebaseline-check"
NEW_PROJECT="jurisnexo-baseline-check"
BASELINE_ONLY_DIR="$OLD_DIR/baseline-only"
ARTIFACT_DIR="${BASELINE_EQUIVALENCE_OUTPUT:-$ROOT/.artifacts/baseline-equivalence}"

cleanup() {
  docker compose -p "$OLD_PROJECT" -f "$OLD_REPO/compose.yaml" down -v --remove-orphans >/dev/null 2>&1 || true
  docker compose -p "$NEW_PROJECT" -f "$BASELINE_ONLY_DIR/compose.yaml" down -v --remove-orphans >/dev/null 2>&1 || true
  git worktree remove --force "$OLD_REPO" >/dev/null 2>&1 || true
  rm -rf "$OLD_DIR"
}
trap cleanup EXIT

mkdir -p "$ARTIFACT_DIR"

git cat-file -e "$PRE_BASELINE_COMMIT^{commit}"
git worktree add --detach "$OLD_REPO" "$PRE_BASELINE_COMMIT"

run_stack() {
  local project="$1"
  local compose_file="$2"
  docker compose -p "$project" -f "$compose_file" up -d db
  docker compose -p "$project" -f "$compose_file" run --rm migrate
}

dump_schema() {
  local project="$1"
  local compose_file="$2"
  local output="$3"
  docker compose -p "$project" -f "$compose_file" exec -T db     pg_dump -U jurisnexo -d jurisnexo       --schema-only       --no-owner       --no-privileges             --exclude-table=public.alembic_version     > "$output"
  sed -i '/^\\restrict /d; /^\\unrestrict /d' "$output"
}

dump_data() {
  local project="$1"
  local compose_file="$2"
  local output="$3"
  docker compose -p "$project" -f "$compose_file" exec -T db     pg_dump -U jurisnexo -d jurisnexo       --data-only       --inserts       --column-inserts       --no-owner       --no-privileges       --exclude-table=public.alembic_version     > "$output"
  sed -i '/^\\restrict /d; /^\\unrestrict /d' "$output"
}

echo "==> Rebuilding historical database from $PRE_BASELINE_COMMIT"
run_stack "$OLD_PROJECT" "$OLD_REPO/compose.yaml"

echo "==> Rebuilding consolidated baseline without post-baseline migrations"
mkdir -p "$BASELINE_ONLY_DIR"
git archive HEAD | tar -x -C "$BASELINE_ONLY_DIR"
find "$BASELINE_ONLY_DIR/backend/migrations/versions" -maxdepth 1 -type f \
  ! -name "0001_jurisnexo_baseline.py" -delete
run_stack "$NEW_PROJECT" "$BASELINE_ONLY_DIR/compose.yaml"

OLD_SCHEMA="$ARTIFACT_DIR/pre-baseline.schema.sql"
NEW_SCHEMA="$ARTIFACT_DIR/baseline.schema.sql"
OLD_DATA="$ARTIFACT_DIR/pre-baseline.data.sql"
NEW_DATA="$ARTIFACT_DIR/baseline.data.sql"
OLD_DATA_NORM="$ARTIFACT_DIR/pre-baseline.data.normalized.sql"
NEW_DATA_NORM="$ARTIFACT_DIR/baseline.data.normalized.sql"

dump_schema "$OLD_PROJECT" "$OLD_REPO/compose.yaml" "$OLD_SCHEMA"
dump_schema "$NEW_PROJECT" "$BASELINE_ONLY_DIR/compose.yaml" "$NEW_SCHEMA"

if ! diff -u "$OLD_SCHEMA" "$NEW_SCHEMA" > "$ARTIFACT_DIR/schema.diff"; then
  echo >&2 "ERROR: consolidated baseline does not reproduce the historical PostgreSQL schema"
  cat "$ARTIFACT_DIR/schema.diff" >&2
  exit 1
fi

dump_data "$OLD_PROJECT" "$OLD_REPO/compose.yaml" "$OLD_DATA"
dump_data "$NEW_PROJECT" "$BASELINE_ONLY_DIR/compose.yaml" "$NEW_DATA"

PYTHONPATH=backend/src python -m jurisnexo.db_dump_normalizer "$OLD_DATA" "$OLD_DATA_NORM"
PYTHONPATH=backend/src python -m jurisnexo.db_dump_normalizer "$NEW_DATA" "$NEW_DATA_NORM"

if ! diff -u "$OLD_DATA_NORM" "$NEW_DATA_NORM" > "$ARTIFACT_DIR/data.diff"; then
  echo >&2 "ERROR: consolidated baseline does not preserve migration-owned seed semantics"
  cat "$ARTIFACT_DIR/data.diff" >&2
  exit 1
fi

echo "==> Verifying Alembic control-table hardening"
for pair in "$OLD_PROJECT|$OLD_REPO/compose.yaml" "$NEW_PROJECT|$BASELINE_ONLY_DIR/compose.yaml"; do
  project="${pair%%|*}"
  compose_file="${pair#*|}"
  value="$(
    docker compose -p "$project" -f "$compose_file" exec -T db       psql -U jurisnexo -d jurisnexo -Atqc       "select relrowsecurity from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname='alembic_version'"
  )"
  test "$value" = "t"
done

echo "Historical migration chain and consolidated baseline are equivalent."
