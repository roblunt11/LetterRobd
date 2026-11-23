import json
import os
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

from letterboxd_stats.enrich import (
    TmdbClient, TmdbError, check_key, enrich_films, normalize_title, pick_match, unmatched_titles,
)
from letterboxd_stats.parse import Film

V3_KEY = "0123456789abcdef0123456789abcdef"
V4_TOKEN = "eyJhbGciOiJIUzI1NiJ9.payload.signature"


def ok(payload):
    return 200, json.dumps(payload).encode(), {}


class FakeTmdb:
    """Stands in for the network. `routes` maps (path, year-or-None) -> payload."""

    def __init__(self, search=None, details=None, statuses=None):
        self.search = search or {}      # (title, year|None) -> list of results
        self.details = details or {}    # id -> details payload
        self.statuses = list(statuses or [])  # forced responses, consumed first
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if self.statuses:
            return self.statuses.pop(0)
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if parsed.path.endswith("/search/movie"):
            year = int(q["year"]) if "year" in q else None
            return ok({"results": self.search.get((q["query"], year), [])})
        movie_id = int(parsed.path.rsplit("/", 1)[1])
        payload = self.details.get(movie_id)
        return ok(payload) if payload else (404, b"{}", {})


def fight_club():
    return FakeTmdb(
        search={("Fight Club", 1999): [{"id": 550, "title": "Fight Club", "original_title": "Fight Club",
                                        "release_date": "1999-10-15", "popularity": 50}]},
        details={550: {"title": "Fight Club", "credits": {
            "cast": [{"name": "Edward Norton", "order": 1}, {"name": "Brad Pitt", "order": 0},
                     {"name": "Helena Bonham Carter", "order": 2}, {"name": "Meat Loaf", "order": 3}],
            "crew": [{"name": "David Fincher", "job": "Director"},
                     {"name": "Jim Uhls", "job": "Screenplay"},
                     {"name": "David Fincher", "job": "Director"}]}}},
    )


def client(fake, **kw):
    return TmdbClient(kw.pop("key", V3_KEY), http_get=fake, sleep=lambda s: None, **kw)


def film(name, year):
    return Film(name=name, year=year, watched=date(2026, 1, 1))


class MatchingTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_title("Amélie"), "amelie")
        self.assertEqual(normalize_title("Wallace & Gromit: Vengeance Most Fowl"),
                         "wallace and gromit vengeance most fowl")
        self.assertEqual(normalize_title("(500) Days of Summer"), "500 days of summer")

    def test_wrong_title_same_year_is_rejected(self):
        results = [{"id": 1, "title": "Something Else Entirely", "release_date": "2026-03-01"}]
        self.assertIsNone(pick_match(results, "Mother's Pride", 2026))

    def test_year_off_by_one_is_accepted_but_by_two_is_not(self):
        r = [{"id": 1, "title": "Heel", "release_date": "2026-01-01"}]
        self.assertEqual(pick_match(r, "Heel", 2025)["id"], 1)
        self.assertIsNone(pick_match(r, "Heel", 2024))

    def test_prefers_exact_year_then_popularity(self):
        r = [{"id": 1, "title": "It", "release_date": "1990-01-01", "popularity": 99},
             {"id": 2, "title": "It", "release_date": "2017-09-08", "popularity": 10},
             {"id": 3, "title": "It", "release_date": "2017-09-08", "popularity": 80}]
        self.assertEqual(pick_match(r, "It", 2017)["id"], 3)


class ClientTests(unittest.TestCase):
    def test_lookup_returns_directors_and_ordered_cast(self):
        result = client(fight_club()).lookup("Fight Club", 1999)
        self.assertEqual(result["tmdb_id"], 550)
        self.assertEqual(result["directors"], ["David Fincher"])  # de-duplicated, directors only
        self.assertEqual(result["cast"][:3], ["Brad Pitt", "Edward Norton", "Helena Bonham Carter"])

    def test_falls_back_to_search_without_year(self):
        fake = FakeTmdb(
            search={("Heel", None): [{"id": 7, "title": "Heel", "release_date": "2026-02-01"}]},
            details={7: {"title": "Heel", "credits": {"cast": [], "crew": [{"name": "A Director", "job": "Director"}]}}},
        )
        result = client(fake).lookup("Heel", 2025)
        self.assertEqual(result["directors"], ["A Director"])
        self.assertEqual(sum("/search/movie" in url for url, _ in fake.calls), 2)

    def test_no_match_returns_none(self):
        self.assertIsNone(client(FakeTmdb()).lookup("Nothing Here", 2026))

    def test_v3_key_goes_in_query_and_v4_token_in_header(self):
        fake = fight_club()
        client(fake, key=V3_KEY).lookup("Fight Club", 1999)
        url, headers = fake.calls[0]
        self.assertIn(f"api_key={V3_KEY}", url)
        self.assertNotIn("Authorization", headers)

        fake = fight_club()
        client(fake, key=V4_TOKEN).lookup("Fight Club", 1999)
        url, headers = fake.calls[0]
        self.assertNotIn("api_key", url)
        self.assertNotIn(V4_TOKEN, url)
        self.assertEqual(headers["Authorization"], f"Bearer {V4_TOKEN}")

    def test_missing_key_is_a_clear_error(self):
        with self.assertRaises(TmdbError) as ctx:
            TmdbClient(None)
        self.assertIn("TMDB_API_KEY", str(ctx.exception))

    def test_401_raises_without_leaking_the_key(self):
        fake = FakeTmdb(statuses=[(401, b"{}", {})])
        with self.assertRaises(TmdbError) as ctx:
            client(fake).lookup("Fight Club", 1999)
        self.assertIn("rejected", str(ctx.exception))
        self.assertNotIn(V3_KEY, str(ctx.exception))

    def test_429_is_retried_then_succeeds(self):
        fake = fight_club()
        fake.statuses = [(429, b"{}", {"retry-after": "1"})]
        waits = []
        c = TmdbClient(V3_KEY, http_get=fake, sleep=waits.append, delay=0)
        self.assertEqual(c.lookup("Fight Club", 1999)["tmdb_id"], 550)
        self.assertIn(1.0, waits)

    def test_network_failure_gives_clean_error(self):
        def boom(url, headers):
            raise urllib.error.URLError(f"cannot connect to {url}")
        c = TmdbClient(V3_KEY, http_get=boom, sleep=lambda s: None, retries=1)
        with self.assertRaises(TmdbError) as ctx:
            c.lookup("Fight Club", 1999)
        self.assertNotIn(V3_KEY, str(ctx.exception))

    def test_check_key_summary(self):
        self.assertIn("David Fincher", check_key(client(fight_club())))


class EnrichTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / ".cache" / "tmdb.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_enriches_films_and_applies_cast_limit(self):
        films = [film("Fight Club", 1999)]
        enrich_films(films, V3_KEY, self.cache, cast_limit=2, client=client(fight_club()), progress=False)
        self.assertEqual(films[0].directors, ["David Fincher"])
        self.assertEqual(films[0].cast, ["Brad Pitt", "Edward Norton"])
        self.assertEqual(films[0].tmdb_id, 550)

    def test_rewatches_cost_one_lookup(self):
        fake = fight_club()
        films = [film("Fight Club", 1999), film("Fight Club", 1999)]
        enrich_films(films, V3_KEY, self.cache, client=client(fake), progress=False)
        self.assertEqual(sum("/search/movie" in url for url, _ in fake.calls), 1)
        self.assertEqual(films[1].directors, ["David Fincher"])

    def test_second_run_uses_cache_and_needs_no_key(self):
        enrich_films([film("Fight Club", 1999)], V3_KEY, self.cache, client=client(fight_club()), progress=False)
        again = [film("Fight Club", 1999)]
        enrich_films(again, None, self.cache, progress=False)  # no key, no client: cache only
        self.assertEqual(again[0].directors, ["David Fincher"])

    def test_misses_are_cached_and_reported(self):
        fake = FakeTmdb()
        films = [film("Mother's Pride", 2026)]
        enrich_films(films, V3_KEY, self.cache, client=client(fake), progress=False)
        self.assertEqual(unmatched_titles(films), ["Mother's Pride (2026)"])
        calls = len(fake.calls)
        enrich_films([film("Mother's Pride", 2026)], V3_KEY, self.cache, client=client(fake), progress=False)
        self.assertEqual(len(fake.calls), calls)  # not asked again

    def test_refresh_ignores_the_cache(self):
        enrich_films([film("Fight Club", 1999)], V3_KEY, self.cache, client=client(fight_club()), progress=False)
        fake = fight_club()
        enrich_films([film("Fight Club", 1999)], V3_KEY, self.cache, refresh=True, client=client(fake), progress=False)
        self.assertTrue(fake.calls)

    def test_uncached_film_without_key_raises(self):
        with self.assertRaises(TmdbError):
            enrich_films([film("Fight Club", 1999)], None, self.cache, progress=False)

    def test_corrupt_cache_is_ignored(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("{not json")
        films = [film("Fight Club", 1999)]
        enrich_films(films, V3_KEY, self.cache, client=client(fight_club()), progress=False)
        self.assertEqual(films[0].tmdb_id, 550)


if __name__ == "__main__":
    unittest.main()
