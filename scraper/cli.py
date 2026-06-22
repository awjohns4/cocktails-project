#!/usr/bin/env python
"""
CLI tool to manage database migrations.

Usage:
    python -m scraper.cli migrate
"""

import argparse
import logging
import sys

from scraper.migration_runner import apply_migrations


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def migrate_cmd(args: argparse.Namespace) -> int:
    """Run pending database migrations."""
    try:
        count = apply_migrations()
        print(f"\n✓ Migrations applied: {count}")
        return 0
    except Exception as e:
        print(f"\n✗ Migration error: {e}")
        return 1


def main() -> int:
    """Parse arguments and run the requested command."""
    parser = argparse.ArgumentParser(
        description="Cocktail scraper database management tool"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.add_parser("migrate", help="Apply pending database migrations")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.command == "migrate":
        return migrate_cmd(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
