"""Add directors and top-billed cast to each film, using whichever credits source is configured.

A source is any object with `lookup(title, year) -> dict | None` returning
{"id": str, "title": str, "directors": [str], "cast": [str]} (cast in billing order, best effort),
or None when the film cannot be matched. See wikidata.py and tmdb.py.

Results, including "no match", are cached per source in .cache/<source>.json so re-runs are fast and
a fully cached run needs no network. Unmatched films are kept with empty credits.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Callable

from .parse import Film

CACHE_VERSION = 2
CAST_STORED = 10  # billed cast kept in the cache; `cast_limit` trims at enrich time


class SourceError(RuntimeError):
    """A problem talking to a credits source (bad key, blocked, network failure, repeated errors)."""


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# ---------------------------------------------------------------- cache

def _cache_key(name: str, year: int) -> str:
    return f"{normalize_title(name)}|{year}"


def load_cache(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}
    return data.get("films", {})


def save_cache(path: Path, films: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": CACHE_VERSION, "films": films}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- public API

def enrich_films(
    films: list[Film],
    client_factory: Callable[[], object],
    cache_path: Path,
    cast_limit: int = 5,
    refresh: bool = False,
    progress: bool = True,
) -> list[Film]:
    """Fill `source_id`, `directors` and `cast` on each film in place and return the list.

    Each distinct (title, year) is looked up once. `client_factory` is only called if something
    is not already cached, so a fully cached run needs no key and no network.
    """
    cache = {} if refresh else load_cache(cache_path)
    distinct = {}
    for film in films:
        distinct.setdefault(_cache_key(film.name, film.year), (film.name, film.year))
    todo = [key for key in distinct if key not in cache]

    if todo:
        client = client_factory()
        try:
            for i, key in enumerate(todo, 1):
                name, year = distinct[key]
                cache[key] = client.lookup(name, year)
                if progress and (i % 10 == 0 or i == len(todo)):
                    print(f"Credit lookups: {i}/{len(todo)}", file=sys.stderr)
                if i % 25 == 0:
                    save_cache(cache_path, cache)
        finally:  # keep partial progress if interrupted or an error stops the run
            save_cache(cache_path, cache)

    for film in films:
        entry = cache.get(_cache_key(film.name, film.year))
        if entry:
            film.source_id = entry["id"]
            film.directors = list(entry["directors"])
            film.cast = list(entry["cast"][:cast_limit])
    return films


def unmatched_titles(films: list[Film]) -> list[str]:
    """Distinct titles (with year) the source could not match, in first-seen order."""
    return list(dict.fromkeys(f"{f.name} ({f.year})" for f in films if f.source_id is None))


def uncredited_titles(films: list[Film]) -> list[str]:
    """Titles that matched but have no director and no cast listed (common on Wikidata)."""
    return list(dict.fromkeys(
        f"{f.name} ({f.year})" for f in films if f.source_id is not None and not f.directors and not f.cast
    ))
