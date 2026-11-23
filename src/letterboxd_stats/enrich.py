"""Add directors and top-billed cast to each film using the TMDB API (stdlib only).

Flow per distinct (title, year):
  1. Search TMDB for the title, filtered to the release year.
  2. If that finds nothing, search without the year and accept a release year within +/-1
     (Letterboxd and TMDB sometimes disagree by a year for festival releases).
  3. Fetch details with credits in a single request (append_to_response=credits).
  4. Cache the result, including "no match", in .cache/tmdb.json so re-runs are fast.

Unmatched films are kept with empty credits; call `unmatched_titles` to report them.
Nothing here logs the API key, and error messages never include request URLs.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .parse import Film

BASE_URL = "https://api.themoviedb.org/3"
CACHE_VERSION = 1
CAST_STORED = 10  # billed cast kept in the cache; `cast_limit` trims at enrich time


class TmdbError(RuntimeError):
    """A problem talking to TMDB (bad key, network failure, repeated server errors)."""


# (url, headers) -> (status, body, response_headers with lower-case keys)
HttpGet = Callable[[str, dict], tuple]


def _urllib_get(url: str, headers: dict) -> tuple:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as err:  # non-2xx still carries a status we handle
        return err.code, err.read(), {k.lower(): v for k, v in err.headers.items()}


# ---------------------------------------------------------------- matching helpers

def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _release_year(release_date: str | None) -> int | None:
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def pick_match(results: list[dict], title: str, year: int) -> dict | None:
    """Choose the TMDB result that best matches a Letterboxd title and year, or None.

    A result must have an equal normalised title (or original title) and a release year within
    one year. A near-identical title (similarity >= 0.88) is accepted only when the year is exact.
    Among candidates, prefer exact titles, then the closest year, then the most popular.
    """
    wanted = normalize_title(title)
    best: tuple | None = None
    for result in results:
        result_year = _release_year(result.get("release_date"))
        if result_year is None or abs(result_year - year) > 1:
            continue
        names = {normalize_title(result.get("title") or ""),
                 normalize_title(result.get("original_title") or "")} - {""}
        exact = wanted in names
        similarity = max((difflib.SequenceMatcher(None, wanted, n).ratio() for n in names), default=0.0)
        if not exact and not (similarity >= 0.88 and result_year == year):
            continue
        rank = (not exact, abs(result_year - year), -(result.get("popularity") or 0))
        if best is None or rank < best[0]:
            best = (rank, result)
    return best[1] if best else None


# ---------------------------------------------------------------- client

class TmdbClient:
    def __init__(
        self,
        api_key: str | None,
        http_get: HttpGet = _urllib_get,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = 0.05,
        retries: int = 3,
    ):
        if not api_key or not api_key.strip():
            raise TmdbError(
                "TMDB_API_KEY is not set. Add it to a .env file (see .env.example), "
                "or run with --no-enrich to skip director and cast lookups."
            )
        self._key = api_key.strip()
        self._http_get = http_get
        self._sleep = sleep
        self._delay = delay
        self._retries = retries

    def _get(self, path: str, **params) -> dict | None:
        params = {k: v for k, v in params.items() if v is not None}
        headers = {"accept": "application/json"}
        if self._key.startswith("eyJ"):  # v4 "API Read Access Token" (a JWT) -> Bearer header
            headers["Authorization"] = f"Bearer {self._key}"
        else:  # v3 "API Key" -> query parameter
            params["api_key"] = self._key
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"

        for attempt in range(self._retries + 1):
            self._sleep(self._delay)
            try:
                status, body, resp_headers = self._http_get(url, headers)
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                if attempt == self._retries:
                    raise TmdbError(f"Could not reach TMDB ({type(err).__name__}).") from None
                self._sleep(2 ** attempt)
                continue

            if status == 200:
                return json.loads(body)
            if status == 404:
                return None
            if status == 401:
                raise TmdbError("TMDB rejected the API key (HTTP 401). Check TMDB_API_KEY in your .env file.")
            if status == 429 or status >= 500:
                if attempt == self._retries:
                    raise TmdbError(f"TMDB kept returning HTTP {status} for {path}; try again later.")
                try:
                    wait = float(resp_headers.get("retry-after", ""))
                except ValueError:
                    wait = 2 ** attempt
                self._sleep(wait)
                continue
            raise TmdbError(f"TMDB returned HTTP {status} for {path}.")
        raise TmdbError(f"TMDB request failed for {path}.")  # pragma: no cover

    def lookup(self, title: str, year: int) -> dict | None:
        """Return {tmdb_id, tmdb_title, directors, cast} for a film, or None if unmatched."""
        found = self._get("/search/movie", query=title, year=year, include_adult="false") or {}
        match = pick_match(found.get("results", []), title, year)
        if match is None:
            found = self._get("/search/movie", query=title, include_adult="false") or {}
            match = pick_match(found.get("results", []), title, year)
        if match is None:
            return None

        details = self._get(f"/movie/{match['id']}", append_to_response="credits")
        if not details:
            return None
        credits = details.get("credits") or {}
        directors = list(dict.fromkeys(
            c["name"] for c in credits.get("crew", []) if c.get("job") == "Director" and c.get("name")
        ))
        billed = sorted(credits.get("cast", []), key=lambda c: c.get("order", 9999))
        cast = [c["name"] for c in billed if c.get("name")][:CAST_STORED]
        return {
            "tmdb_id": match["id"],
            "tmdb_title": details.get("title") or match.get("title"),
            "directors": directors,
            "cast": cast,
        }


def check_key(client: TmdbClient) -> str:
    """Make one real lookup so the user can confirm the key works. Returns a summary line."""
    result = client.lookup("Fight Club", 1999)
    if result is None:
        raise TmdbError("The key was accepted but the test lookup found nothing; try again later.")
    director = ", ".join(result["directors"]) or "unknown director"
    return f'TMDB key OK: found "{result["tmdb_title"]}", directed by {director}.'


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
    api_key: str | None,
    cache_path: Path,
    cast_limit: int = 5,
    refresh: bool = False,
    client: TmdbClient | None = None,
    progress: bool = True,
) -> list[Film]:
    """Fill `tmdb_id`, `directors` and `cast` on each film in place and return the list.

    Each distinct (title, year) is looked up once. A fully cached run needs no API key.
    """
    cache = {} if refresh else load_cache(cache_path)
    distinct = {}
    for film in films:
        distinct.setdefault(_cache_key(film.name, film.year), (film.name, film.year))
    todo = [key for key in distinct if key not in cache]

    if todo:
        client = client or TmdbClient(api_key)
        try:
            for i, key in enumerate(todo, 1):
                name, year = distinct[key]
                cache[key] = client.lookup(name, year)
                if progress and (i % 10 == 0 or i == len(todo)):
                    print(f"TMDB lookups: {i}/{len(todo)}", file=sys.stderr)
                if i % 25 == 0:
                    save_cache(cache_path, cache)
        finally:  # keep partial progress if interrupted or an error stops the run
            save_cache(cache_path, cache)

    for film in films:
        entry = cache.get(_cache_key(film.name, film.year))
        if entry:
            film.tmdb_id = entry["tmdb_id"]
            film.directors = list(entry["directors"])
            film.cast = list(entry["cast"][:cast_limit])
    return films


def unmatched_titles(films: list[Film]) -> list[str]:
    """Distinct titles (with year) that TMDB could not match, in first-seen order."""
    seen = dict.fromkeys(f"{f.name} ({f.year})" for f in films if f.tmdb_id is None)
    return list(seen)
