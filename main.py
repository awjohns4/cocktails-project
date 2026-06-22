"""
main.py — run the scraper from the command line.

    python main.py daiquiri 1-5
    python main.py daiquiri 5
"""

import argparse
import logging
import re
import sys
from scraper import config
from scraper.scraper import run


def _setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def _parse_result_range(range_text: str) -> tuple[int, int]:
    """Parse either a range (e.g. '1-5') or single index (e.g. '5')."""
    single_match = re.fullmatch(r"\s*(\d+)\s*", range_text)
    if single_match:
        idx = int(single_match.group(1))
        if idx < 1:
            raise ValueError("Result index must be >= 1.")
        return idx, idx

    range_match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", range_text)
    if not range_match:
        raise ValueError(
            "Result selector must be a single number like '5' or range '1-5'."
        )

    start_idx = int(range_match.group(1))
    end_idx = int(range_match.group(2))
    if start_idx < 1 or end_idx < 1:
        raise ValueError("Range values must be >= 1.")
    if end_idx < start_idx:
        raise ValueError("Range end must be greater than or equal to range start.")

    return start_idx, end_idx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Difford's Guide cocktail scraper")
    parser.add_argument(
        "drink_name",
        help="Drink search keyword (example: daiquiri)",
    )
    parser.add_argument(
        "result_range",
        help="Result selector: single index '5' or range '1-5'",
    )
    return parser.parse_args()


if __name__ == "__main__":
    _setup_logging()
    args = _parse_args()

    try:
        search_range = _parse_result_range(args.result_range)
    except ValueError as exc:
        raise SystemExit(str(exc))

    run(drink_name=args.drink_name, result_range=search_range)
