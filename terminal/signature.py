"""Ověření podpisu webhooků od centrály (ASGI middleware).

Podpis platí pro BAJTY těla, ne pro „stejný JSON“. Proto middleware přečte surové tělo ještě
před tím, než ho FastAPI rozparsuje, spočítá HMAC-SHA256 a porovná s hlavičkou `X-Signature`.
Teprve když podpis sedí, pustí požadavek dál – a předá mu přesně tytéž bajty.

    X-Signature: sha256=<hex HMAC-SHA256(secret, surové tělo)>

Klíč je `secret` jako text (UTF-8 bajty), stejně jako `openssl dgst -sha256 -hmac "<secret>" soubor`.
"""

import hashlib
import hmac
import json
from collections.abc import Callable

MAX_BODY = 64 * 1024  # událost má pár set bajtů; víc nečteme


def expected_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def check(secret: str | None, header: str | None, body: bytes) -> str | None:
    """Vrátí důvod odmítnutí, nebo None, když je podpis v pořádku."""
    if secret is None:
        return "Terminál ještě není přihlášen k odběru – nemá secret, nemůže ověřit podpis"
    if not header:
        return "Chybí hlavička X-Signature"
    if not header.startswith("sha256="):
        return "X-Signature musí mít tvar sha256=<hex>"
    # compare_digest = porovnání v konstantním čase (útočník nepozná, kolik znaků trefil)
    if not hmac.compare_digest(expected_signature(secret, body), "sha256=" + header[7:].strip().lower()):
        return "Neplatný podpis"
    return None


class SignatureMiddleware:
    def __init__(self, app, path: str, get_secret: Callable[[], str | None]) -> None:
        self.app = app
        self.path = path
        self.get_secret = get_secret

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            return await self.app(scope, receive, send)

        # 1) Surové tělo – před jakýmkoli parsováním.
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY:
                return await _reject(send, 413, "Tělo je příliš velké")

        # 2) Ověřit podpis nad těmito bajty.
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        reason = check(self.get_secret(), headers.get("x-signature"), body)
        if reason:
            return await _reject(send, 401, reason)

        # 3) Podpis sedí → teprve teď pustit dál (FastAPI tělo rozparsuje), se stejnými bajty.
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _reject(send, status: int, detail: str) -> None:
    payload = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
    })
    await send({"type": "http.response.body", "body": payload})
