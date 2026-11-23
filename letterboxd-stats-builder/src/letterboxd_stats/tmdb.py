"""TMDB credits source (optional; needs a free API key from themoviedb.org).

Search by title + year; if that finds nothing, search without the year and accept a release year
within +/-1. Then fetch details with credits in one request. Error messages never include URLs,
so the key cannot leak.
"""

from __future__ import annotations

import difflib
import json
import time
import urllib.error
import urllib.parse
from typing import Callable

from .enrich import CAST_STORED, SourceError, normalize_title
from .http import urllib_get

BASE_URL = "https://api.themoviedb.org/3"
HttpGet = Callable[[str, dict], tuple]


class TmdbError(SourceError):
    """A problem talking to TMDB."""


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


class TmdbClient:
    name = "tmdb"

    def __init__(
        self,
        api_key: str | None,
        http_get: HttpGet = urllib_get,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = 0.05,
        retries: int = 3,
    ):
        if not api_key or not api_key.strip():
            raise TmdbError(
                "TMDB_API_KEY is not set. Add it to a .env file (see .env.example), "
                "or use the default source, which needs no key: --source wikidata."
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
        return {"id": str(match["id"]), "title": details.get("title") or match.get("title"),
                "directors": directors, "cast": cast}
