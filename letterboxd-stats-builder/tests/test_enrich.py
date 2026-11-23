import tempfile
import unittest
from datetime import date
from pathlib import Path

from letterboxd_stats.enrich import enrich_films, uncredited_titles, unmatched_titles
from letterboxd_stats.parse import Film

FIGHT_CLUB = {"id": "Q190050", "title": "Fight Club", "directors": ["David Fincher"],
              "cast": ["Brad Pitt", "Edward Norton", "Helena Bonham Carter", "Meat Loaf", "Jared Leto", "Zach Grenier"]}


class FakeClient:
    name = "fake"

    def __init__(self, known):
        self.known = known
        self.calls = []

    def lookup(self, title, year):
        self.calls.append((title, year))
        return self.known.get((title, year))


def film(name, year):
    return Film(name=name, year=year, watched=date(2026, 1, 1))


class EnrichTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / ".cache" / "fake.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_enrich(self, films, client, **kw):
        return enrich_films(films, lambda: client, self.cache, progress=False, **kw)

    def test_fills_credits_and_applies_cast_limit(self):
        films = [film("Fight Club", 1999)]
        self.run_enrich(films, FakeClient({("Fight Club", 1999): FIGHT_CLUB}), cast_limit=2)
        self.assertEqual(films[0].directors, ["David Fincher"])
        self.assertEqual(films[0].cast, ["Brad Pitt", "Edward Norton"])
        self.assertEqual(films[0].source_id, "Q190050")

    def test_rewatches_cost_one_lookup(self):
        client = FakeClient({("Fight Club", 1999): FIGHT_CLUB})
        films = [film("Fight Club", 1999), film("Fight Club", 1999)]
        self.run_enrich(films, client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(films[1].directors, ["David Fincher"])

    def test_second_run_uses_cache_and_never_builds_a_client(self):
        self.run_enrich([film("Fight Club", 1999)], FakeClient({("Fight Club", 1999): FIGHT_CLUB}))

        def explode():
            raise AssertionError("client should not be needed")
        again = [film("Fight Club", 1999)]
        enrich_films(again, explode, self.cache, progress=False)
        self.assertEqual(again[0].directors, ["David Fincher"])

    def test_misses_are_cached_and_reported(self):
        client = FakeClient({})
        films = [film("Mother's Pride", 2026)]
        self.run_enrich(films, client)
        self.assertEqual(unmatched_titles(films), ["Mother's Pride (2026)"])
        self.run_enrich([film("Mother's Pride", 2026)], client)
        self.assertEqual(len(client.calls), 1)  # not asked again

    def test_matched_but_bare_films_are_reported_separately(self):
        bare = {"id": "Q9", "title": "Bare", "directors": [], "cast": []}
        films = [film("Bare", 2026), film("Fight Club", 1999)]
        self.run_enrich(films, FakeClient({("Bare", 2026): bare, ("Fight Club", 1999): FIGHT_CLUB}))
        self.assertEqual(unmatched_titles(films), [])
        self.assertEqual(uncredited_titles(films), ["Bare (2026)"])

    def test_refresh_ignores_the_cache(self):
        self.run_enrich([film("Fight Club", 1999)], FakeClient({("Fight Club", 1999): FIGHT_CLUB}))
        client = FakeClient({("Fight Club", 1999): FIGHT_CLUB})
        self.run_enrich([film("Fight Club", 1999)], client, refresh=True)
        self.assertTrue(client.calls)

    def test_partial_progress_is_saved_when_a_lookup_fails(self):
        class Flaky(FakeClient):
            def lookup(self, title, year):
                if title == "Second":
                    raise RuntimeError("boom")
                return super().lookup(title, year)

        client = Flaky({("First", 2020): {"id": "Q1", "title": "First", "directors": ["A"], "cast": []}})
        with self.assertRaises(RuntimeError):
            self.run_enrich([film("First", 2020), film("Second", 2021)], client)
        again = FakeClient({})
        films = [film("First", 2020)]
        self.run_enrich(films, again)
        self.assertEqual(films[0].directors, ["A"])
        self.assertEqual(again.calls, [])

    def test_corrupt_cache_is_ignored(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("{not json")
        films = [film("Fight Club", 1999)]
        self.run_enrich(films, FakeClient({("Fight Club", 1999): FIGHT_CLUB}))
        self.assertEqual(films[0].source_id, "Q190050")


if __name__ == "__main__":
    unittest.main()
