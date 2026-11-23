import json
import unittest
import urllib.error
from urllib.parse import parse_qs, urlparse

from letterboxd_stats.wikidata import (
    API_URL, SPARQL_URL, WikidataClient, WikidataError, build_film_query, choose_film,
    ordered_ids, title_variants,
)

UA = "letterboxd-stats-builder/0.1.0 (test@example.org)"


def ok(payload):
    return 200, json.dumps(payload).encode(), {}


def claim(item_id, ordinal=None, rank="normal", snaktype="value"):
    c = {"rank": rank, "mainsnak": {"snaktype": snaktype}}
    if snaktype == "value":
        c["mainsnak"]["datavalue"] = {"value": {"id": item_id}}
    if ordinal is not None:
        c["qualifiers"] = {"P1545": [{"datavalue": {"value": str(ordinal)}}]}
    return c


def binding(qid, date):
    return {"film": {"value": f"http://www.wikidata.org/entity/{qid}"}, "date": {"value": date}}


class FakeWikidata:
    """Routes SPARQL and wbgetentities calls to canned data."""

    def __init__(self, bindings=None, entities=None, statuses=None):
        self.bindings = bindings or []
        self.entities = entities or {}
        self.statuses = list(statuses or [])
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if self.statuses:
            return self.statuses.pop(0)
        parsed = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if url.startswith(SPARQL_URL):
            return ok({"results": {"bindings": self.bindings}})
        ids = q["ids"].split("|")
        return ok({"entities": {i: self.entities[i] for i in ids if i in self.entities}})


def named(label):
    return {"labels": {"en": {"language": "en", "value": label}}}


def fight_club_world():
    return FakeWikidata(
        bindings=[binding("Q190050", "1999-10-15T00:00:00Z"), binding("Q190050", "1999-09-10T00:00:00Z")],
        entities={
            "Q190050": {**named("Fight Club"), "claims": {
                "P57": [claim("Q1"), claim("Q1")],
                "P161": [claim("Q4"), claim("Q3", ordinal=2), claim("Q2", ordinal=1),
                         claim("Q9", rank="deprecated"), claim(None, snaktype="somevalue")]}},
            "Q1": named("David Fincher"), "Q2": named("Brad Pitt"),
            "Q3": named("Edward Norton"), "Q4": named("Meat Loaf"),
        },
    )


def client(fake, **kw):
    return WikidataClient(UA, http_get=fake, sleep=lambda s: None, **kw)


class QueryTests(unittest.TestCase):
    def test_variants_cover_common_spelling_differences(self):
        v = title_variants("Wallace & Gromit: What's Up – Doc")
        self.assertIn("Wallace and Gromit: What\u2019s Up - Doc", v)
        self.assertEqual(v[0], "Wallace & Gromit: What's Up – Doc")
        self.assertEqual(title_variants("Jaws"), ["Jaws"])

    def test_query_filters_by_year_window_and_escapes(self):
        q = build_film_query('Say "Hi"', 1999)
        self.assertIn('"Say \\"Hi\\""@en', q)
        self.assertIn(">= 1998", q)
        self.assertIn("<= 2000", q)
        self.assertIn("wd:Q11424", q)

    def test_choose_film_prefers_closest_year_then_older_item(self):
        rows = [binding("Q500", "2018-01-01T00:00:00Z"), binding("Q100", "2017-05-05T00:00:00Z"),
                binding("Q200", "2017-06-06T00:00:00Z")]
        self.assertEqual(choose_film(rows, 2017), "Q100")
        self.assertEqual(choose_film(rows, 2018), "Q500")
        self.assertIsNone(choose_film([], 2017))
        self.assertIsNone(choose_film([{"film": {"value": "x"}, "date": {"value": "nope"}}], 2017))


class OrderingTests(unittest.TestCase):
    def test_ordinals_first_then_stored_order_skipping_junk(self):
        claims = {"P161": [claim("Q4"), claim("Q3", ordinal=2), claim("Q2", ordinal=1),
                           claim("Q9", rank="deprecated"), claim(None, snaktype="somevalue"), claim("Q5")]}
        self.assertEqual(ordered_ids(claims, "P161"), ["Q2", "Q3", "Q4", "Q5"])

    def test_missing_property(self):
        self.assertEqual(ordered_ids({}, "P57"), [])


class ClientTests(unittest.TestCase):
    def test_lookup_end_to_end(self):
        result = client(fight_club_world()).lookup("Fight Club", 1999)
        self.assertEqual(result["id"], "Q190050")
        self.assertEqual(result["title"], "Fight Club")
        self.assertEqual(result["directors"], ["David Fincher"])
        self.assertEqual(result["cast"], ["Brad Pitt", "Edward Norton", "Meat Loaf"])

    def test_sends_compliant_headers_and_makes_three_requests(self):
        fake = fight_club_world()
        client(fake).lookup("Fight Club", 1999)
        self.assertEqual(len(fake.calls), 3)  # SPARQL, film entity, people labels
        for _, headers in fake.calls:
            self.assertEqual(headers["User-Agent"], UA)
            self.assertEqual(headers["Accept-Encoding"], "gzip")

    def test_no_match_stops_after_one_request(self):
        fake = FakeWikidata()
        self.assertIsNone(client(fake).lookup("Nothing Here", 2026))
        self.assertEqual(len(fake.calls), 1)

    def test_film_with_no_credits_is_matched_but_empty(self):
        fake = FakeWikidata(bindings=[binding("Q9", "2026-01-01T00:00:00Z")],
                            entities={"Q9": {**named("Bare Film"), "claims": {}}})
        result = client(fake).lookup("Bare Film", 2026)
        self.assertEqual((result["id"], result["directors"], result["cast"]), ("Q9", [], []))

    def test_people_without_a_label_are_skipped(self):
        fake = fight_club_world()
        del fake.entities["Q4"]  # Meat Loaf has no entity data returned
        self.assertEqual(client(fake).lookup("Fight Club", 1999)["cast"], ["Brad Pitt", "Edward Norton"])

    def test_429_honours_retry_after_then_succeeds(self):
        fake = fight_club_world()
        fake.statuses = [(429, b"{}", {"retry-after": "7"})]
        waits = []
        c = WikidataClient(UA, http_get=fake, sleep=waits.append, delay=0)
        self.assertEqual(c.lookup("Fight Club", 1999)["id"], "Q190050")
        self.assertIn(7.0, waits)

    def test_retry_after_is_capped(self):
        fake = fight_club_world()
        fake.statuses = [(429, b"{}", {"retry-after": "99999"})]
        waits = []
        WikidataClient(UA, http_get=fake, sleep=waits.append, delay=0).lookup("Fight Club", 1999)
        self.assertLessEqual(max(waits), 120.0)

    def test_403_explains_the_user_agent_policy(self):
        with self.assertRaises(WikidataError) as ctx:
            client(FakeWikidata(statuses=[(403, b"", {})])).lookup("Fight Club", 1999)
        self.assertIn("LSB_CONTACT", str(ctx.exception))

    def test_persistent_503_gives_up_cleanly(self):
        fake = FakeWikidata(statuses=[(503, b"", {})] * 10)
        with self.assertRaises(WikidataError):
            client(fake, retries=2).lookup("Fight Club", 1999)

    def test_network_failure_gives_clean_error(self):
        def boom(url, headers):
            raise urllib.error.URLError("no route")
        with self.assertRaises(WikidataError):
            WikidataClient(UA, http_get=boom, sleep=lambda s: None, retries=1).lookup("Fight Club", 1999)


if __name__ == "__main__":
    unittest.main()
