from __future__ import annotations

"""HTML parsing logic for Difford's Guide cocktail recipe pages."""

import re
from typing import Any

from bs4 import BeautifulSoup, Tag


def _normalized(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return " ".join(cleaned.split())


def _find_heading(soup: BeautifulSoup, target: str) -> Tag | None:
    target_text = _normalized(target)
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if _normalized(heading.get_text(" ", strip=True)) == target_text:
            return heading
    return None


def _section_nodes(heading: Tag) -> list[Tag]:
    nodes: list[Tag] = []
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag) and sibling.name in {"h2", "h3", "h4"}:
            break
        if isinstance(sibling, Tag):
            nodes.append(sibling)
    return nodes


def _extract_steps(soup: BeautifulSoup, heading_text: str) -> list[str]:
    heading = _find_heading(soup, heading_text)
    if not heading:
        return []

    nodes = _section_nodes(heading)
    steps: list[str] = []

    for node in nodes:
        for li in node.find_all("li"):
            text = li.get_text(" ", strip=True)
            if text:
                steps.append(text)

    # Some pages may not use list markup for instructions.
    if not steps:
        for node in nodes:
            text = node.get_text("\n", strip=True)
            for line in text.splitlines():
                cleaned = line.strip(" -\t")
                if cleaned and cleaned not in steps:
                    steps.append(cleaned)

    return steps


def _extract_ingredients(soup: BeautifulSoup) -> list[dict[str, str]]:
    best_rows: list[dict[str, str]] = []
    for table in soup.find_all("table"):
        rows: list[dict[str, str]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            amount = cells[0].get_text(" ", strip=True)
            ingredient = cells[1].get_text(" ", strip=True)
            if amount and ingredient and ingredient != "---":
                rows.append({"amount": amount, "ingredient": ingredient})

        if len(rows) > len(best_rows):
            best_rows = rows

    return best_rows


def _extract_strength_taste_guide(soup: BeautifulSoup) -> dict[str, Any]:
    text_chunks: list[str] = []
    scores: list[int] = []

    # The guide consistently includes these label anchors in page text.
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    text_match = re.search(
        r"No alcohol\s+Medium\s+Boozy\s+Sweet\s+Medium\s+Dry/sour",
        page_text,
        flags=re.IGNORECASE,
    )
    if text_match:
        text_chunks.append(text_match.group(0))

    for image in soup.select('img[src*="/svg/range/"]'):
        src = image.get("src", "")
        match = re.search(r"/svg/range/(\d+)\.svg", src)
        if match:
            score = int(match.group(1))
            scores.append(score)

    return {
        "strength_score": scores[0] if len(scores) > 0 else None,
        "sweet_dry_score": scores[1] if len(scores) > 1 else None,
    }


def _extract_title(soup: BeautifulSoup) -> str | None:
    """Extract recipe title while ignoring interstitial/banner headings."""
    blocked_titles = {"are you a discerning drinker"}

    for heading in soup.find_all("h1"):
        text = heading.get_text(" ", strip=True)
        if text and _normalized(text) not in blocked_titles:
            return text

    title_tag = soup.find("title")
    if not title_tag:
        return None

    title_text = title_tag.get_text(" ", strip=True)
    # Keep only recipe name from page title like "X Cocktail Recipe".
    title_text = re.sub(r"\s+Cocktail Recipe$", "", title_text, flags=re.IGNORECASE)
    return title_text or None


def parse_page(html: str) -> tuple[str | None, dict[str, Any]]:
    """Parse a Difford's recipe page into sectioned recipe data."""
    soup = BeautifulSoup(html, "lxml")

    title = _extract_title(soup)

    sections: dict[str, Any] = {
        "ingredients": _extract_ingredients(soup),
        "prepare": _extract_steps(soup, "Prepare"),
        "how_to_make": _extract_steps(soup, "How to make"),
        "garnish": _extract_steps(soup, "Garnish"),
        "strength_taste_guide": _extract_strength_taste_guide(soup),
    }

    return title, sections
