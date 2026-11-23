import os
import tempfile
import unittest
from pathlib import Path

from letterboxd_stats.config import build_parser, load_dotenv

KEYS = ("LSB_TEST_A", "LSB_TEST_B", "LSB_TEST_C", "LSB_TEST_D")


class DotenvTests(unittest.TestCase):
    def setUp(self):
        for k in KEYS:
            os.environ.pop(k, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".env"

    def tearDown(self):
        for k in KEYS:
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_parses_comments_quotes_and_export(self):
        self.path.write_text('# comment\nLSB_TEST_A=plain\nLSB_TEST_B="quoted value"\nexport LSB_TEST_C=\'single\'\n')
        load_dotenv(self.path)
        self.assertEqual(os.environ["LSB_TEST_A"], "plain")
        self.assertEqual(os.environ["LSB_TEST_B"], "quoted value")
        self.assertEqual(os.environ["LSB_TEST_C"], "single")

    def test_existing_env_wins_and_blank_values_are_skipped(self):
        os.environ["LSB_TEST_A"] = "from-shell"
        self.path.write_text("LSB_TEST_A=from-file\nLSB_TEST_D=\n")
        load_dotenv(self.path)
        self.assertEqual(os.environ["LSB_TEST_A"], "from-shell")
        self.assertNotIn("LSB_TEST_D", os.environ)

    def test_missing_file_is_fine(self):
        load_dotenv(Path(self.tmp.name) / "nope.env")


class ParserTests(unittest.TestCase):
    def test_new_flags(self):
        args = build_parser().parse_args(["--cast-limit", "3", "--refresh-cache", "--check-tmdb"])
        self.assertEqual((args.cast_limit, args.refresh_cache, args.check_tmdb), (3, True, True))


if __name__ == "__main__":
    unittest.main()
