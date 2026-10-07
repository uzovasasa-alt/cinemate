"""Разбор того, что пользователь прислал боту: ссылка Кинопоиска/IMDb/стриминга или название."""
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

KP_RE = re.compile(r"kinopoisk\.(?:ru|dev)/(?:level/\d+/)?(?:film|series|movie)/(\d+)", re.I)
IMDB_RE = re.compile(r"imdb\.com/(?:[a-z]{2}/)?title/(tt\d{6,10})", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)

# Стриминги: достать из ссылки можно только «похожее на название» — результат всегда нужно подтверждать.
STREAMING_HOSTS = {
    "ivi.ru": "ivi", "okko.tv": "Okko", "kion.ru": "KION", "wink.ru": "Wink",
    "premier.one": "PREMIER", "start.ru": "START", "more.tv": "more.tv",
    "hd.kinopoisk.ru": "Кинопоиск HD", "netflix.com": "Netflix",
    "primevideo.com": "Prime Video", "youtube.com": "YouTube", "rutube.ru": "RuTube",
}


@dataclass
class Parsed:
    kind: str               # kp_id | imdb | query
    value: str
    service: str | None = None   # название стриминга, если ссылка оттуда
    guessed: bool = False         # название вытащено из slug — нужен выбор из списка


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _slug_to_title(url: str) -> str:
    path = unquote(urlparse(url).path)
    parts = [p for p in path.split("/") if p]
    skip = {"watch", "movie", "movies", "film", "films", "series", "serial", "show", "video",
            "ru", "en", "title", "details", "play", "watch_id"}
    for seg in reversed(parts):
        seg = seg.lower()
        if seg in skip:
            continue
        seg = re.sub(r"[-_]+", " ", seg)
        seg = re.sub(r"\b[0-9a-f]{8,}\b", " ", seg)          # хэши
        seg = re.sub(r"\b\d{4,}\b", " ", seg)               # числовые id
        seg = re.sub(r"\s+", " ", seg).strip()
        if len(seg) >= 2 and not seg.isdigit():
            return seg
    return ""


def parse_input(text: str) -> Parsed | None:
    text = (text or "").strip()
    if not text:
        return None
    if m := KP_RE.search(text):
        return Parsed("kp_id", m.group(1))
    if m := IMDB_RE.search(text):
        return Parsed("imdb", m.group(1).lower())
    if um := URL_RE.search(text):
        url = um.group(0).rstrip(").,;")
        host = _host(url)
        service = next((v for k, v in STREAMING_HOSTS.items() if host == k or host.endswith("." + k)), None)
        title = _slug_to_title(url)
        if title:
            return Parsed("query", title, service=service, guessed=True)
        return None
    if m := re.fullmatch(r"kp[:\s]*(\d{2,9})", text, re.I):   # «kp:326»; голые числа не трогаем: «1917» — это название
        return Parsed("kp_id", m.group(1))
    if re.fullmatch(r"tt\d{6,10}", text, re.I):
        return Parsed("imdb", text.lower())
    return Parsed("query", text[:200])
