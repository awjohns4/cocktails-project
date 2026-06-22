#!/usr/bin/env sh
set -eu

if [ -z "${DRINK_NAME:-}" ]; then
  echo "DRINK_NAME is required"
  exit 1
fi

if [ -z "${RESULT_SELECTOR:-}" ]; then
  echo "RESULT_SELECTOR is required (examples: 1 or 1-5)"
  exit 1
fi

python main.py "$DRINK_NAME" "$RESULT_SELECTOR"
