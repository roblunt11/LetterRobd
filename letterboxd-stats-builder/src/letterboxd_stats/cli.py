"""Pipeline: parse -> enrich -> filter by period -> stats -> render."""

from __future__ import annotations

import sys

from .config import load_config
from .enrich import SourceError, enrich_films, uncredited_titles, unmatched_titles
from .parse import parse_diary
from .periods import PERIODS, resolve_period
from .render import render_page
from .sources import check_source, make_client_factory
from .stats import build_stats


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    factory = make_client_factory(config)
    try:
        if config.check_source:
            print(check_source(factory()))
            return 0

        diary = parse_diary(config.input)
        if config.enrich:
            diary = enrich_films(diary, factory, config.cache_path,
                                 cast_limit=config.cast_limit, refresh=config.refresh_cache)
            missing = unmatched_titles(diary)
            if missing:
                print(f"No match for {len(missing)} title(s), left out of director/actor stats: "
                      f"{', '.join(missing)}", file=sys.stderr)
            bare = uncredited_titles(diary)
            if bare:
                print(f"Matched but no director or cast listed for {len(bare)} title(s): "
                      f"{', '.join(bare)}", file=sys.stderr)

        names = PERIODS if config.period == "all" else (config.period,)
        for name in names:
            period = resolve_period(name, config.as_of, config.calendar_year)
            # TODO: films = [f for f in diary if period.contains(f.watched)]
            films = diary
            render_page(period, build_stats(films), config.out)
    except SourceError as err:
        print(f"Credits source error: {err}", file=sys.stderr)
        return 2
    except NotImplementedError as err:
        print(f"Not built yet: {err}", file=sys.stderr)
        return 1
    return 0
