from __future__ import annotations

"""
config.py — central configuration for the scraper.
Edit the values here before running.
"""

# ── Browser ───────────────────────────────────────────────────────────────────
HEADLESS: bool = True          # Set to False to watch the browser while scraping
SLOW_MO_MS: int = 0            # Milliseconds between Playwright actions (0 = fastest)
TIMEOUT_MS: int = 30_000       # Page load timeout in milliseconds
USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Pagination ────────────────────────────────────────────────────────────────
# Set MAX_PAGES to None to follow pagination until no next page is found.
MAX_PAGES: int | None = None

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = "INFO"        # DEBUG | INFO | WARNING | ERROR
