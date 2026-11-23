"""Command-line flags and environment."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .periods import PERIODS


@dataclass(frozen=True)
class Config:
    input: Path
    out: Path
    period: str  # one of PERIODS, or "all"
    calendar_year: int | None
    as_of: date | None
    enrich: bool
    cast_limit: int
    refresh_cache: bool
    check_tmdb: bool
    tmdb_api_key: str | None
    cache_path: Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (stdlib only).

    Existing environment variables win, and empty values are ignored, so a copied
    .env.example with a blank TMDB_API_KEY does not shadow a real key.
    """
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lsb",
        description="Build a stats page from your Letterboxd data export.",
    )
    p.add_argument("--input", type=Path, default=Path("data"),
                   help="Letterboxd export zip or extracted folder (default: ./data)")
    p.add_argument("--out", type=Path, default=Path("dist"),
                   help="Output folder (default: ./dist)")
    p.add_argument("--period", choices=[*PERIODS, "all"], default="all",
                   help="Which period to build (default: all)")
    p.add_argument("--calendar-year", type=int, metavar="YYYY",
                   help="Year to use for calendar-year (default: current year)")
    p.add_argument("--as-of", type=date.fromisoformat, metavar="YYYY-MM-DD",
                   help='Treat this date as "today" for rolling periods')
    p.add_argument("--no-enrich", action="store_true",
                   help="Skip the TMDB director/cast lookup (watch counts and ratings only)")
    p.add_argument("--cast-limit", type=int, default=5, metavar="N",
                   help="Top-billed cast members counted per film (default: 5)")
    p.add_argument("--refresh-cache", action="store_true",
                   help="Ignore cached TMDB results and look every film up again")
    p.add_argument("--check-tmdb", action="store_true",
                   help="Test your TMDB key with one lookup, then exit")
    return p


def load_config(argv: list[str] | None = None) -> Config:
    args = build_parser().parse_args(argv)
    load_dotenv(Path(".env"))
    return Config(
        input=args.input,
        out=args.out,
        period=args.period,
        calendar_year=args.calendar_year,
        as_of=args.as_of,
        enrich=not args.no_enrich,
        cast_limit=args.cast_limit,
        refresh_cache=args.refresh_cache,
        check_tmdb=args.check_tmdb,
        tmdb_api_key=os.environ.get("TMDB_API_KEY") or None,
        cache_path=Path(".cache") / "tmdb.json",
    )
