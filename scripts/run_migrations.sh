#!/bin/bash
# scripts/run_migrations.sh
# Run database migrations before deployment.
# Exit with error if migrations fail (for CI/CD integration).

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(dirname "$SCRIPT_DIR")

cd "$REPO_ROOT"

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "❌ DATABASE_URL not set"
    exit 1
fi

echo "📦 Running database migrations..."

# Activate virtual environment if it exists
if [[ -f .venv/bin/activate ]]; then
    source .venv/bin/activate
fi

# Run migrations via Python CLI
python -m scraper.cli migrate

echo "✅ Migrations completed successfully"
