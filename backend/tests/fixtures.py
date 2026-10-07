"""Ответы в формате, описанном в документации api.kinopoisk.dev v1.4 ([Предположение]: поля сверены по докам, не по живому API)."""
MATRIX = {
    "id": 301, "name": "Матрица", "alternativeName": "The Matrix", "enName": None, "type": "movie", "year": 1999,
    "description": "Жизнь Томаса Андерсона разделена на две части.", "shortDescription": "Хакер узнаёт правду.",
    "rating": {"kp": 8.5123, "imdb": 8.7}, "movieLength": 136, "ageRating": 16,
    "poster": {"url": "https://img/matrix.jpg", "previewUrl": "https://img/matrix_s.jpg"},
    "genres": [{"name": "фантастика"}, {"name": "боевик"}],
    "countries": [{"name": "США"}],
    "externalId": {"imdb": "tt0133093", "tmdb": 603},
    "persons": [
        {"id": 1, "name": "Лана Вачовски", "enName": "Lana Wachowski", "enProfession": "director", "photo": "p1"},
        {"id": 2, "name": "Киану Ривз", "enName": "Keanu Reeves", "enProfession": "actor", "photo": "p2"},
        {"id": 3, "name": "Кэрри-Энн Мосс", "enName": "Carrie-Anne Moss", "enProfession": "actor"},
        {"id": 4, "name": "Композитор", "enProfession": "composer"},
    ],
    "watchability": {"items": [{"name": "Okko", "url": "https://okko.tv/x", "logo": {"url": "https://l/okko.png"}},
                               {"name": "Без ссылки"}]},
}
SERIES = {
    "id": 464963, "name": "Игра в кальмара", "alternativeName": "Ojingeo geim", "type": "tv-series", "year": 2021,
    "seriesLength": 55, "genres": [{"name": "триллер"}, {"name": "драма"}],
    "seasonsInfo": [{"number": 1, "episodesCount": 9}, {"number": 2, "episodesCount": 7}],
    "rating": {"kp": 7.7, "imdb": 0},
}
DOC = {"id": 77, "name": "Планета Земля", "type": "tv-series", "year": 2006, "genres": [{"name": "Документальный"}]}
SEASONS = {"docs": [
    {"number": 0, "episodesCount": 1, "episodes": [{"number": 1, "name": "Спецвыпуск"}]},
    {"number": 2, "episodesCount": 2, "episodes": [{"number": 1, "name": "Б", "airDate": "2022-01-02T00:00:00.000Z"},
                                                   {"number": 2, "name": "В", "airDate": "мусор"}]},
    {"number": 1, "episodesCount": 2, "episodes": [{"number": 1, "name": "А", "duration": 50}, {"number": 2}]},
]}
