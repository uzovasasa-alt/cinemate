from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


class ProviderError(Exception):
    """Базовая ошибка провайдера контента."""


class ProviderAuthError(ProviderError):
    """Ключ неверный или исчерпана квота."""


class ProviderNotFound(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


@dataclass
class PersonDTO:
    kinopoisk_id: int | None
    name: str
    en_name: str | None
    photo_url: str | None
    role: str            # director | actor | writer | producer | other
    sort_order: int = 0


@dataclass
class EpisodeDTO:
    number: int
    name: str = ""
    air_date: date | None = None
    duration_min: int | None = None


@dataclass
class SeasonDTO:
    number: int
    episodes_count: int
    episodes: list[EpisodeDTO] = field(default_factory=list)


@dataclass
class ContentDTO:
    kinopoisk_id: int | None
    imdb_id: str | None
    tmdb_id: int | None
    type_code: str
    is_serial: bool
    title: str
    original_title: str | None
    year: int | None
    description: str | None
    short_description: str | None
    poster_url: str | None
    rating_kp: float | None
    rating_imdb: float | None
    duration_min: int | None
    countries: list[str]
    genres: list[str]
    age_rating: int | None
    people: list[PersonDTO]
    watchability: list[dict]
    total_episodes: int = 0
    seasons_info: list[tuple[int, int]] = field(default_factory=list)   # (номер, серий)


class ContentProvider(Protocol):
    """Абстракция: основной источник — Кинопоиск, при необходимости добавляется TMDb-fallback."""

    async def search(self, query: str, limit: int = 10) -> list[ContentDTO]: ...
    async def by_kinopoisk_id(self, kp_id: int) -> ContentDTO: ...
    async def by_imdb_id(self, imdb_id: str) -> ContentDTO | None: ...
    async def seasons(self, kp_id: int) -> list[SeasonDTO]: ...
