import json
import unittest
import urllib.error
from urllib.parse import parse_qs, urlparse

from letterboxd_stats.enrich import normalize_title
from letterboxd_stats.tmdb import TmdbClient, TmdbError, pick_match

V3_KEY = "0123456789abcdef0123456789abcdef"
V4_TOKEN = "eyJhbGciOiJIUzI1NiJ9.payload.signature"


def ok(payload):
    return 200, json.dumps(payload).encode(), {}


class FakeTmdb:
    def __init__(self, search=None, details=None, statuses=None):
        self.search = search or {}
        self.details = details or {}
        self.statuses = list(statuses or [])
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if self.statuses:
            return self.statuses.pop(0)
        parsed = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if parsed.path.endswith("/search/movie"):
            year = int(q["year"]) if "year" in q else None
            return ok({"results": self.search.get((q["query"], year), [])})
        payload = self.details.get(int(parsed.path.rsplit("/", 1)[1]))
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
        self.assertEqual(result["id"], "550")
        self.assertEqual(result["directors"], ["David Fincher"])
        self.assertEqual(result["cast"][:3], ["Brad Pitt", "Edward Norton", "Helena Bonham Carter"])

    def test_falls_back_to_search_without_year(self):
        fake = FakeTmdb(
            search={("Heel", None): [{"id": 7, "title": "Heel", "release_date": "2026-02-01"}]},
            details={7: {"title": "Heel", "credits": {"cast": [], "crew": [{"name": "A Director", "job": "Director"}]}}},
        )
        self.assertEqual(client(fake).lookup("Heel", 2025)["directors"], ["A Director"])
        self.assertEqual(sum("/search/movie" in url for url, _ in fake.calls), 2)

    def test_no_match_returns_none(self):
        self.assertIsNone(client(FakeTmdb()).lookup("Nothing Here", 2026))

    def test_v3_key_in_query_v4_token_in_header(self):
        fake = fight_club()
        client(fake, key=V3_KEY).lookup("Fight Club", 1999)
        url, headers = fake.calls[0]
        self.assertIn(f"api_key={V3_KEY}", url)
        self.assertNotIn("Authorization", headers)

        fake = fight_club()
        client(fake, key=V4_TOKEN).lookup("Fight Club", 1999)
        url, headers = fake.calls[0]
        self.assertNotIn(V4_TOKEN, url)
        self.assertEqual(headers["Authorization"], f"Bearer {V4_TOKEN}")

    def test_missing_key_points_to_the_keyless_default(self):
        with self.assertRaises(TmdbError) as ctx:
            TmdbClient(None)
        self.assertIn("TMDB_API_KEY", str(ctx.exception))
        self.assertIn("wikidata", str(ctx.exception))

    def test_401_raises_without_leaking_the_key(self):
        with self.assertRaises(TmdbError) as ctx:
            client(FakeTmdb(statuses=[(401, b"{}", {})])).lookup("Fight Club", 1999)
        self.assertNotIn(V3_KEY, str(ctx.exception))

    def test_429_is_retried_then_succeeds(self):
        fake = fight_club()
        fake.statuses = [(429, b"{}", {"retry-after": "1"})]
        waits = []
        c = TmdbClient(V3_KEY, http_get=fake, sleep=waits.append, delay=0)
        self.assertEqual(c.lookup("Fight Club", 1999)["id"], "550")
        self.assertIn(1.0, waits)

    def test_network_failure_gives_clean_error(self):
        def boom(url, headers):
            raise urllib.error.URLError(f"cannot connect to {url}")
        c = TmdbClient(V3_KEY, http_get=boom, sleep=lambda s: None, retries=1)
        with self.assertRaises(TmdbError) as ctx:
            c.lookup("Fight Club", 1999)
        self.assertNotIn(V3_KEY, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
