#!/usr/bin/env sh
set -eu

uv sync
uv run pre-commit install
uv run pre-commit run --all-files

printf '%s\n' "Jan Setu development environment is ready."