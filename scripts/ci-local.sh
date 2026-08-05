#!/usr/bin/env bash
#
# Everything CI runs, in one command, in the same order.
#
# This exists because twice now a push has failed on a check that passes locally — not
# because the check is environment-dependent, but because I ran *some* of the commands and
# not the others: `npm run lint` without `npm run format:check`, then `typecheck` before
# adding a file rather than after. Both were a minute of work and a red build.
#
# Keep this in step with `.github/workflows/ci.yml`. A check that lives only in the
# workflow is a check that gets discovered by pushing.
#
# Usage: scripts/ci-local.sh  [--fast]
#   --fast skips the API test suite and the migration check, which need PostgreSQL.

set -euo pipefail

cd "$(dirname "$0")/.."
FAST=${1:-}

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------- TypeScript workspaces

step 'eslint'
npm run lint

step 'prettier --check'
npm run format:check

step 'tsc --noEmit (all workspaces)'
npm run typecheck

step 'jest + node:test (all workspaces)'
npm test --workspaces --if-present

# ------------------------------------------------------------------------- reproducible

step 'fixtures regenerate to the same bytes'
node scripts/generate-fixtures.mjs
git diff --exit-code fixtures/papers.sample.json
node scripts/build-katex-runtime.mjs
git diff --exit-code apps/mobile/src/math/katexRuntime.ts
node scripts/build-mathjax-runtime.mjs
git diff --exit-code apps/mobile/src/math/mathjaxRuntime.ts

# -------------------------------------------------------------------------------- Python

step 'ruff check'
(cd apps/api && uv run ruff check .)

step 'ruff format --check'
(cd apps/api && uv run ruff format --check .)

step 'mypy'
(cd apps/api && uv run mypy papermatch_api)

if [ "$FAST" = '--fast' ]; then
  printf '\n\033[33mSkipped: pytest and the migration check (--fast).\033[0m\n'
  exit 0
fi

step 'pytest'
(cd apps/api && uv run pytest -q)

step 'migrations apply to an empty database'
(
  cd apps/api
  DB=papermatch_ci_local
  PGPASSWORD=papermatch dropdb -h localhost -U papermatch --if-exists "$DB"
  PGPASSWORD=papermatch createdb -h localhost -U papermatch "$DB"
  export PAPERMATCH_DATABASE_URL="postgresql+psycopg://papermatch:papermatch@localhost:5432/$DB"
  uv run alembic upgrade head
  uv run python -m papermatch_api.cli seed >/dev/null
  PGPASSWORD=papermatch dropdb -h localhost -U papermatch "$DB"
)

printf '\n\033[32mAll checks passed.\033[0m\n'
