import unittest

from app.linkparse import parse_input


class LinkParse(unittest.TestCase):
    def test_kinopoisk_film(self):
        p = parse_input("https://www.kinopoisk.ru/film/301/")
        self.assertEqual((p.kind, p.value), ("kp_id", "301"))

    def test_kinopoisk_series_and_level(self):
        self.assertEqual(parse_input("kinopoisk.ru/series/464963/").value, "464963")
        self.assertEqual(parse_input("https://www.kinopoisk.ru/level/1/film/326/").value, "326")

    def test_imdb(self):
        p = parse_input("смотри https://www.imdb.com/title/tt0133093/?ref_=x")
        self.assertEqual((p.kind, p.value), ("imdb", "tt0133093"))

    def test_streaming_slug_is_guess(self):
        p = parse_input("https://www.ivi.ru/watch/blade-runner-2049")
        self.assertEqual(p.kind, "query")
        self.assertTrue(p.guessed)
        self.assertEqual(p.service, "ivi")
        self.assertIn("blade runner", p.value)

    def test_streaming_url_without_title(self):
        self.assertIsNone(parse_input("https://hd.kinopoisk.ru/"))

    def test_plain_title(self):
        p = parse_input("  Бегущий по лезвию  ")
        self.assertEqual((p.kind, p.value, p.guessed), ("query", "Бегущий по лезвию", False))

    def test_number_title_is_not_kp_id(self):
        p = parse_input("1917")
        self.assertEqual((p.kind, p.value), ("query", "1917"))

    def test_explicit_kp_prefix(self):
        self.assertEqual(parse_input("kp:326").kind, "kp_id")

    def test_empty(self):
        self.assertIsNone(parse_input("   "))


if __name__ == "__main__":
    unittest.main()
