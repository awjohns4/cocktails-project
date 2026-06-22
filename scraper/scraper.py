"""
scraper.py — Playwright browser automation layer.
"""

import logging
from typing import Tuple
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, Browser

from scraper import config
from scraper.parser import parse_page
from scraper.database import init_db, upsert_page, save_recipe_sections

logger = logging.getLogger(__name__)

DIFFORD_BASE_URL = "https://www.diffordsguide.com"


def _build_search_url(drink_name: str) -> str:
    params = {
        "s": "1",
        "k": drink_name,
        "g[dg]": "1",
        "g[dd]": "1",
        "a": "35",
        "na": "1",
        "cal": "425",
        "gid": "all",
    }
    return f"{DIFFORD_BASE_URL}/cocktails/search?{urlencode(params)}"


def discover_recipe_urls(
    page: Page,
    drink_name: str,
    result_range: Tuple[int, int],
) -> list[str]:
    """Discover recipe URLs from Difford search results for a drink name."""
    start_idx, end_idx = result_range
    search_url = _build_search_url(drink_name)
    logger.info("Discovering recipe pages from: %s", search_url)

    page.goto(search_url, timeout=config.TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_selector('a[href*="/cocktails/recipe/"]', timeout=config.TIMEOUT_MS)
    soup = BeautifulSoup(page.content(), "lxml")

    discovered: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="/cocktails/recipe/"]'):
        href = anchor.get("href")
        if not href:
            continue
        full_url = urljoin(DIFFORD_BASE_URL, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        discovered.append(full_url)

    selected = discovered[start_idx - 1:end_idx]
    logger.info(
        "Found %d recipe links. Using results %d-%d (%d URLs).",
        len(discovered),
        start_idx,
        end_idx,
        len(selected),
    )
    return selected


def _fetch_html(page: Page, url: str) -> str:
    """Navigate to *url* and return the fully-rendered HTML."""
    page.goto(url, timeout=config.TIMEOUT_MS, wait_until="domcontentloaded")
    page.wait_for_selector("h1", timeout=config.TIMEOUT_MS)
    return page.content()


def scrape_url(page: Page, url: str) -> None:
    """Scrape a single URL and persist the results to the database."""
    logger.info("Scraping %s", url)
    try:
        html = _fetch_html(page, url)
        title, sections = parse_page(html)
        page_id = upsert_page(url, title)
        save_recipe_sections(page_id, sections)
        logger.info("Saved %d sections from '%s'", len(sections), url)
    except Exception:
        logger.exception("Failed to scrape %s", url)
        upsert_page(url, None, status="error")


def run(drink_name: str, result_range: Tuple[int, int]) -> None:
    """Entry point — initialise DB, discover result URLs, and scrape them."""
    init_db()

    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(
            headless=config.HEADLESS,
            slow_mo=config.SLOW_MO_MS,
        )
        context = browser.new_context(user_agent=config.USER_AGENT)
        page = context.new_page()

        urls_to_scrape = discover_recipe_urls(page, drink_name, result_range)

        if not urls_to_scrape:
            logger.warning("No URLs found to scrape.")

        for url in urls_to_scrape:
            scrape_url(page, url)

        browser.close()

    logger.info("Scraping complete.")
