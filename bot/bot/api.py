import httpx


class BotApiError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail

    @property
    def not_linked(self) -> bool:
        return self.status == 403 and self.detail == "not_linked"

    @property
    def message(self) -> str:
        if isinstance(self.detail, dict):
            return self.detail.get("message", "Ошибка")
        return str(self.detail)


class Api:
    def __init__(self, base_url: str, token: str):
        self._c = httpx.AsyncClient(base_url=base_url, headers={"X-Internal-Token": token}, timeout=25.0)

    async def post(self, path: str, **payload):
        try:
            r = await self._c.post("/api/internal" + path, json=payload)
        except httpx.HTTPError as e:
            raise BotApiError(503, "Сервис временно недоступен") from e
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise BotApiError(r.status_code, detail)
        return r.json()

    async def close(self):
        await self._c.aclose()
