"""Wikidata credits source: no account, no key, no sign-up.

Per film, three polite sequential requests:
  1. SPARQL (query.wikidata.org): find the film item by English label/alias, class "film"
     (including subclasses such as short film), with a release year within +/-1 of Letterboxd's.
  2. wbgetentities (www.wikidata.org/w/api.php): read its director (P57) and cast member (P161)
     statements in their stored order, using the "series ordinal" qualifier (P1545) when present.
  3. wbgetentities again: turn those person ids into English names.

Known limits, worth knowing before trusting the actor rankings:
  - Wikidata does not guarantee billing order for cast. Ordinals are used when editors added them;
    otherwise the stored statement order is used, which is often but not always billing order.
  - Coverage varies: obscure or very new films may have no cast, or even no director, listed.
  - TV episodes and many specials are not "film" items and will not match.

Wikimedia rules followed: a descriptive User-Agent with contact details, gzip, one request at a
time, and honouring 429 Retry-After.
"""

from __future__ import annotations

import itertools
import json
import time
import urllib.error
import urllib.parse
from typing import Callable

from .enrich import CAST_STORED, SourceError
from .http import urllib_get

SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"
HttpGet = Callable[[str, dict], tuple]


class WikidataError(SourceError):
    """A problem talking to Wikidata."""


def sparql_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{escaped}"'


def title_variants(title: str) -> list[str]:
    """Spellings Wikidata labels commonly use: curly apostrophes, 'and' for '&', hyphen for en dash."""
    transforms = (
        lambda t: t.replace("'", "\u2019"),
        lambda t: t.replace("&", "and"),
        lambda t: t.replace("\u2013", "-").replace("\u2014", "-"),
    )
    variants = []
    for flags in itertools.product((False, True), repeat=len(transforms)):
        text = title
        for use, transform in zip(flags, transforms):
            if use:
                text = transform(text)
        if text not in variants:
            variants.append(text)
    return variants


def build_film_query(title: str, year: int) -> str:
    values = " ".join(f"{sparql_string(v)}@en" for v in title_variants(title))
    return (
        "SELECT ?film ?date WHERE {\n"
        f"  VALUES ?label {{ {values} }}\n"
        "  ?film rdfs:label|skos:altLabel ?label .\n"
        "  ?film wdt:P31/wdt:P279* wd:Q11424 .\n"   # instance of film (or a subclass)
        "  ?film wdt:P577 ?date .\n"                # publication date
        f"  FILTER(YEAR(?date) >= {year - 1} && YEAR(?date) <= {year + 1})\n"
        "}"
    )


def choose_film(bindings: list[dict], year: int) -> str | None:
    """Pick the film id whose release date is closest to `year`; ties go to the older (lower) Q-number."""
    best: dict[str, int] = {}
    for row in bindings:
        film_uri = (row.get("film") or {}).get("value", "")
        date = (row.get("date") or {}).get("value", "")
        qid = film_uri.rsplit("/", 1)[-1]
        if not (qid.startswith("Q") and qid[1:].isdigit() and date[:4].isdigit()):
            continue
        diff = abs(int(date[:4]) - year)
        best[qid] = min(diff, best.get(qid, diff))
    if not best:
        return None
    return min(best, key=lambda q: (best[q], int(q[1:])))


def ordered_ids(claims: dict, prop: str) -> list[str]:
    """Item ids from a property's statements: ordinal-qualified ones first (by ordinal), then stored order."""
    found = []  # (ordinal or None, position, id)
    for position, claim in enumerate(claims.get(prop, [])):
        if claim.get("rank") == "deprecated":
            continue
        snak = claim.get("mainsnak") or {}
        value = (snak.get("datavalue") or {}).get("value")
        if snak.get("snaktype") != "value" or not isinstance(value, dict) or "id" not in value:
            continue
        ordinal = None
        for qualifier in (claim.get("qualifiers") or {}).get("P1545", []):  # series ordinal
            raw = (qualifier.get("datavalue") or {}).get("value")
            if isinstance(raw, str) and raw.strip().isdigit():
                ordinal = int(raw)
                break
        found.append((ordinal, position, value["id"]))
    found.sort(key=lambda t: (t[0] is None, t[0] or 0, t[1]))
    return list(dict.fromkeys(item_id for _, _, item_id in found))


def label_of(entity: dict) -> str | None:
    labels = entity.get("labels") or {}
    chosen = labels.get("en") or next(iter(labels.values()), None)
    return chosen.get("value") if chosen else None


class WikidataClient:
    name = "wikidata"

    def __init__(
        self,
        user_agent: str,
        http_get: HttpGet = urllib_get,
        sleep: Callable[[float], None] = time.sleep,
        delay: float = 0.3,
        retries: int = 3,
    ):
        self._headers = {"User-Agent": user_agent, "Accept": "application/json", "Accept-Encoding": "gzip"}
        self._http_get = http_get
        self._sleep = sleep
        self._delay = delay
        self._retries = retries

    def _get(self, base: str, **params) -> dict | None:
        url = f"{base}?{urllib.parse.urlencode({**params, 'format': 'json'})}"
        for attempt in range(self._retries + 1):
            self._sleep(self._delay)
            try:
                status, body, resp_headers = self._http_get(url, self._headers)
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                if attempt == self._retries:
                    raise WikidataError(f"Could not reach Wikidata ({type(err).__name__}).") from None
                self._sleep(2 ** attempt)
                continue

            if status == 200:
                try:
                    return json.loads(body)
                except ValueError:
                    raise WikidataError("Wikidata returned a response that was not valid JSON.") from None
            if status == 404:
                return None
            if status == 403:
                raise WikidataError(
                    "Wikimedia refused the request (HTTP 403). Set LSB_CONTACT in .env to an email "
                    "address or URL so your User-Agent complies with their policy."
                )
            if status == 400:
                raise WikidataError("Wikidata rejected a query as malformed (HTTP 400); please report this title.")
            if status == 429 or status >= 500:
                if attempt == self._retries:
                    raise WikidataError(f"Wikidata kept returning HTTP {status}; try again in a few minutes.")
                try:
                    wait = min(float(resp_headers.get("retry-after", "")), 120.0)
                except ValueError:
                    wait = float(2 ** (attempt + 1))
                self._sleep(wait)
                continue
            raise WikidataError(f"Wikidata returned HTTP {status}.")
        raise WikidataError("Wikidata request failed.")  # pragma: no cover

    def lookup(self, title: str, year: int) -> dict | None:
        found = self._get(SPARQL_URL, query=build_film_query(title, year)) or {}
        film_id = choose_film((found.get("results") or {}).get("bindings", []), year)
        if film_id is None:
            return None

        data = self._get(API_URL, action="wbgetentities", ids=film_id, props="claims|labels",
                         languages="en", languagefallback="1") or {}
        entity = (data.get("entities") or {}).get(film_id)
        if not entity or "missing" in entity:
            return None
        claims = entity.get("claims") or {}
        director_ids = ordered_ids(claims, "P57")
        cast_ids = ordered_ids(claims, "P161")[:CAST_STORED]

        names: dict[str, str] = {}
        wanted = list(dict.fromkeys(director_ids + cast_ids))
        for start in range(0, len(wanted), 50):  # wbgetentities accepts up to 50 ids
            batch = wanted[start:start + 50]
            people = self._get(API_URL, action="wbgetentities", ids="|".join(batch), props="labels",
                               languages="en", languagefallback="1") or {}
            for person_id, person in (people.get("entities") or {}).items():
                label = label_of(person)
                if label:
                    names[person_id] = label

        def named(ids):
            return list(dict.fromkeys(names[i] for i in ids if i in names))

        return {"id": film_id, "title": label_of(entity) or title,
                "directors": named(director_ids), "cast": named(cast_ids)}
