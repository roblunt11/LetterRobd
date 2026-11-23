import unittest
from pathlib import Path

from letterboxd_stats.config import Config
from letterboxd_stats.enrich import SourceError
from letterboxd_stats.sources import check_source, make_client_factory, user_agent
from letterboxd_stats.tmdb import TmdbError
from letterboxd_stats.wikidata import WikidataClient


def config(**kw):
    base = dict(input=Path("data"), out=Path("dist"), period="all", calendar_year=None, as_of=None,
                enrich=True, cast_limit=5, refresh_cache=False, check_source=False, source="wikidata",
                contact=None, tmdb_api_key=None, cache_path=Path(".cache/x.json"))
    base.update(kw)
    return Config(**base)


class SourceTests(unittest.TestCase):
    def test_default_source_needs_no_key(self):
        self.assertIsInstance(make_client_factory(config())(), WikidataClient)

    def test_tmdb_without_key_fails_only_when_the_client_is_built(self):
        factory = make_client_factory(config(source="tmdb"))  # building the factory is free
        with self.assertRaises(TmdbError):
            factory()

    def test_user_agent_has_name_version_and_contact(self):
        ua = user_agent("me@example.org")
        self.assertTrue(ua.startswith("letterboxd-stats-builder/"))
        self.assertIn("(me@example.org)", ua)
        self.assertIn("github.com", user_agent(None))

    def test_check_source_reports_or_raises(self):
        class Good:
            name = "fake"
            def lookup(self, t, y): return {"title": "Fight Club", "directors": ["David Fincher"]}
        class Empty:
            name = "fake"
            def lookup(self, t, y): return None
        self.assertIn("David Fincher", check_source(Good()))
        with self.assertRaises(SourceError):
            check_source(Empty())


if __name__ == "__main__":
    unittest.main()
