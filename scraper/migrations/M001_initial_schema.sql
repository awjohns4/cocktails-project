-- M001: Initial schema for cocktail scraper
-- Creates pages and recipe_sections tables with indexes.
-- Safe to run multiple times (uses IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS pages (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT    NOT NULL UNIQUE,
    title       TEXT,
    scraped_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status      TEXT    NOT NULL DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS recipe_sections (
    id            BIGSERIAL PRIMARY KEY,
    page_id       BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    section_name  TEXT    NOT NULL,
    section_json  TEXT    NOT NULL,
    UNIQUE(page_id, section_name)
);

CREATE INDEX IF NOT EXISTS idx_recipe_sections_page_id ON recipe_sections(page_id);
