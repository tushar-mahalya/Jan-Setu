#!/usr/bin/env sh
set -eu

uv sync
npm --prefix frontend ci

# commit-msg stage is required for gitlint.
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run pre-commit run --all-files

printf '%s\n' "Jan Setu development environment is ready."
