# Database Migrations

This document describes the PostgreSQL migration system for the cocktail scraper project.

## Overview

Migrations are versioned SQL scripts stored in `scraper/migrations/` and are applied to the PostgreSQL database in order. The system tracks which migrations have been applied using the `migrations_applied` table, ensuring migrations run exactly once (idempotent).

## Migration Files

Migration files are named with a numbered prefix: `M###_description.sql`

- **M001_initial_schema.sql** — Creates `pages`, `recipe_sections`, and associated indexes

Each migration:
- Uses `IF NOT EXISTS` clauses where applicable for additional idempotency
- Is self-contained and can be reviewed independently
- Should be tested before deployment

## Running Migrations

### Local Development

```bash
source .venv/bin/activate

# Set the database URL
export DATABASE_URL="postgresql://user:password@host/database"

# Run migrations
python -m scraper.cli migrate

# Verbose mode for debugging
python -m scraper.cli -v migrate
```

### Deployment

#### Via GitHub Actions (CI/CD)

Migrations run automatically as part of the deployment workflow (`.github/workflows/deploy-dev.yml`):

1. Infrastructure is deployed via Bicep
2. System waits 30 seconds for PostgreSQL to stabilize
3. Connection string is retrieved from Key Vault
4. Migrations are applied via `python -m scraper.cli migrate`

#### Via Local Deployment Script

When running `scripts/deploy-dev.sh`:

1. Infrastructure is deployed via Bicep (3 phases)
2. Phase 4: Connection string is fetched from Azure
3. Phase 4: `python -m scraper.cli migrate` is executed

## Adding New Migrations

1. **Create a new SQL file** with the next number:
   ```bash
   touch scraper/migrations/M002_add_my_feature.sql
   ```

2. **Write idempotent SQL**:
   ```sql
   -- M002: Add new_field to pages table
   -- Idempotent: uses IF NOT EXISTS and conditional logic
   
   ALTER TABLE pages ADD COLUMN IF NOT EXISTS new_field TEXT;
   ```

3. **Test locally** before committing:
   ```bash
   export DATABASE_URL="postgresql://..."
   python -m scraper.cli migrate
   ```

4. **Verify idempotency** by running migrations twice — second run should skip the new migration:
   ```bash
   python -m scraper.cli migrate
   # Output: "No pending migrations to apply"
   ```

## Idempotency Principles

- Use `IF NOT EXISTS` or `IF NOT` clauses for DDL (CREATE TABLE, CREATE INDEX, etc.)
- Handle column additions with `IF NOT EXISTS`
- For data migrations, use `WHERE` clauses to avoid duplicates
- Always include rollback considerations in comments (though rollback is manual in this system)

## Troubleshooting

### Migration not running
```bash
# Check which migrations have been applied
psql $DATABASE_URL -c "SELECT * FROM migrations_applied ORDER BY applied_at;"
```

### Connection errors
Ensure `DATABASE_URL` is set correctly:
```bash
# Format for Azure PostgreSQL Flexible Server:
postgresql://user:password@servername.postgres.database.azure.com/postgres
```

### Syntax errors in migration
Errors are logged and the transaction is rolled back:
```bash
python -m scraper.cli -v migrate
# Check logs for the specific error
```

## Database Schema

### migrations_applied table
Tracks which migrations have been successfully applied:

```sql
CREATE TABLE migrations_applied (
    id            BIGSERIAL PRIMARY KEY,
    migration_name TEXT    NOT NULL UNIQUE,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### Current Schema (as of M001)

**pages** table:
- `id` (BIGSERIAL PRIMARY KEY)
- `url` (TEXT UNIQUE NOT NULL)
- `title` (TEXT)
- `scraped_at` (TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)
- `status` (TEXT DEFAULT 'ok')

**recipe_sections** table:
- `id` (BIGSERIAL PRIMARY KEY)
- `page_id` (BIGINT NOT NULL, references pages.id)
- `section_name` (TEXT NOT NULL)
- `section_json` (TEXT NOT NULL)
- UNIQUE constraint: (page_id, section_name)
- Index on `page_id`
