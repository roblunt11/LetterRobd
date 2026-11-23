"""Pipeline: parse -> enrich -> filter by period -> stats -> render."""

from __future__ import annotations

import sys

from .config import load_config
from .enrich import TmdbClient, TmdbError, check_key, enrich_films, unmatched_titles
from .parse import parse_diary
from .periods import PERIODS, resolve_period
from .render import render_page
from .stats import build_stats


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    try:
        if config.check_tmdb:
            print(check_key(TmdbClient(config.tmdb_api_key)))
            return 0

        diary = parse_diary(config.input)
        if config.enrich:
            diary = enrich_films(diary, config.tmdb_api_key, config.cache_path,
                                 cast_limit=config.cast_limit, refresh=config.refresh_cache)
            missing = unmatched_titles(diary)
            if missing:
                print(f"No TMDB match for {len(missing)} title(s), left out of director/actor "
                      f"stats: {', '.join(missing)}", file=sys.stderr)

        names = PERIODS if config.period == "all" else (config.period,)
        for name in names:
            period = resolve_period(name, config.as_of, config.calendar_year)
            # TODO: films = [f for f in diary if period.contains(f.watched)]
            films = diary
            render_page(period, build_stats(films), config.out)
    except TmdbError as err:
        print(f"TMDB error: {err}", file=sys.stderr)
        return 2
    except NotImplementedError as err:
        print(f"Not built yet: {err}", file=sys.stderr)
        return 1
    return 0
