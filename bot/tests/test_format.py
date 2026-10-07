import unittest

from bot.format import candidates_text, card_text, link_result_text, stats_text


class Format(unittest.TestCase):
    def test_html_is_escaped(self):
        t = card_text({"title": "<b>Хак</b> & Co", "year": 2000, "genres": ["a<b"], "description": "<script>"})
        self.assertNotIn("<script>", t)
        self.assertIn("&lt;b&gt;Хак&lt;/b&gt; &amp; Co", t)

    def test_caption_limit(self):
        self.assertLessEqual(len(card_text({"title": "X", "description": "я" * 5000})), 1000)

    def test_card_fields(self):
        t = card_text({"title": "Матрица", "year": 1999, "type_code": "movie", "rating_kp": 8.5, "duration_min": 136,
                       "genres": ["фантастика"], "directors": ["Лана Вачовски"], "actors": ["Киану Ривз"]},
                      mine_status="watched", stars_n=5)
        for s in ("Матрица", "1999", "Кинопоиск 8.5", "136 мин", "Лана Вачовски", "Просмотрено", "★★★★★"):
            self.assertIn(s, t)

    def test_candidates(self):
        t = candidates_text([{"title": "A", "year": 2000, "rating_kp": 7.1, "genres": ["драма"]}, {"title": "B"}], "Нашёл:")
        self.assertTrue(t.startswith("Нашёл:"))
        self.assertIn("1. <b>A</b> (2000) · ★7.1", t)

    def test_stats_empty_and_filled(self):
        self.assertIn("Пока пусто", stats_text({"total": 0}))
        s = {"total": 3, "by_status": {"watched": 2, "plan": 1}, "hours": 5.5, "episodes_watched": 4, "avg_stars": 4.5,
             "top_genres": [{"name": "драма", "n": 2}], "top_directors": [],
             "unfinished": [{"title": "Шерлок", "watched_eps": 2, "total_episodes": 13, "days_idle": 21}]}
        t = stats_text(s)
        self.assertIn("Шерлок — 2/13, 21 дн.", t)
        self.assertIn("средняя оценка: 4.5", t)

    def test_link_results(self):
        for st in ("linked", "invalid", "expired", "used", "rate_limited"):
            self.assertTrue(link_result_text(st, "Анна"))
        self.assertIn("Анна", link_result_text("linked", "Анна"))


if __name__ == "__main__":
    unittest.main()
