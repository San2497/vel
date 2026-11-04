"""Rozesílání událostí terminálům (webhooky).

Běží jako background task – až PO odeslání odpovědi žákovi. Chyba doručení se jen zaloguje
a započítá do `failed_deliveries` odběru; uložený hlas tím nijak neovlivní.

Doručení = odpověď 2xx do 3 s. Jinak opakujeme po 1 s, 2 s a 4 s (celkem 4 pokusy) se stejným
tělem i podpisem; pak to vzdáme a zalogujeme id události. Terminál musí být idempotentní (podle `id`).
"""

import asyncio
import hashlib
import hmac
import logging
import uuid

import httpx

import db
from models import Stand, Vote, VoteEvent, VoteEventData

log = logging.getLogger("uvicorn.error")  # ať je to vidět v logu uvicornu

DEADLINE = 3.0             # celý pokus (spojení + odpověď) musí stihnout do 3 s
RETRY_DELAYS = (1, 2, 4)   # pauzy před 2., 3. a 4. pokusem
TIMEOUT = httpx.Timeout(DEADLINE)

# Jeden sdílený klient na celou dobu běhu (otevírá/zavírá ho lifespan v main.py).
# Vytvoření klienta trvá stovky ms (SSL kontext) – kdyby vznikal při každém hlasu, zablokoval by
# event loop dřív, než se odpověď žákovi skutečně odešle.
_client: httpx.AsyncClient | None = None


async def start() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=TIMEOUT)


async def stop() -> None:
    if _client is not None:
        await _client.aclose()


def build_event(vote: Vote, stand: Stand, seq: int) -> VoteEvent:
    return VoteEvent(
        id=str(uuid.uuid4()),
        type="vote.created",
        created_at=db.utc_now(),
        data=VoteEventData(
            vote_id=vote.id,
            seq=seq,
            stand_id=stand.id,
            title=stand.title,
            floor=stand.floor,
            rating=vote.rating,
            favorite=vote.favorite,
            created_at=vote.created_at,
        ),
    )


def sign(secret: str, body: bytes) -> str:
    """Podpis těla: `sha256=` + hex HMAC-SHA256. Klíč = `secret` jako text (UTF-8 bajty hex řetězce),
    stejně jako `openssl dgst -sha256 -hmac "<secret>"`."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _attempt(client: httpx.AsyncClient, url: str, body: bytes, headers: dict) -> str | None:
    """Jeden pokus. Vrací None při úspěchu (2xx do 3 s), jinak popis chyby."""
    try:
        r = await asyncio.wait_for(client.post(url, content=body, headers=headers), DEADLINE)
    except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException):
        return f"timeout {DEADLINE:.0f} s"
    except httpx.HTTPError as e:
        return type(e).__name__
    return None if 200 <= r.status_code < 300 else f"HTTP {r.status_code}"


async def _deliver(client: httpx.AsyncClient, sub, event: VoteEvent, body: bytes) -> None:
    # Podepisujeme přesně ty bajty, které odešleme (content=body) – žádná další serializace.
    # Tělo i hlavičky se spočítají jednou a při opakování se posílají beze změny.
    headers = {
        "Content-Type": "application/json",
        "X-Event-Id": event.id,
        "X-Event-Type": event.type,
        "X-Signature": sign(sub["secret"], body),
    }
    url = sub["callback_url"]
    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(1, attempts + 1):
        error = await _attempt(client, url, body, headers)
        if error is None:
            if attempt > 1:
                log.info("Webhook %s -> %s: doručeno na %d. pokus", event.id, url, attempt)
            db.record_delivery(sub["id"], True)
            return
        if attempt < attempts:
            delay = RETRY_DELAYS[attempt - 1]
            log.warning("Webhook %s -> %s: %s (pokus %d/%d), znovu za %d s", event.id, url, error, attempt, attempts, delay)
            await asyncio.sleep(delay)
        else:
            log.error("Webhook %s -> %s: %s (pokus %d/%d) – VZDÁVÁM, nedoručená událost id=%s",
                      event.id, url, error, attempt, attempts, event.id)
    db.record_delivery(sub["id"], False)


async def dispatch_vote(vote: Vote, stand: Stand, seq: int) -> None:
    """Pošle událost `vote.created` všem odběrům pro patro stánku (a odběrům se `floor = null`)."""
    await asyncio.sleep(0)  # nejdřív nechat event loop dopsat odpověď žákovi do socketu
    subs = db.subscribers_for_floor(stand.floor)
    if not subs:
        return
    event = build_event(vote, stand, seq)
    body = event.model_dump_json().encode()  # serializujeme JEDNOU; tytéž bajty se podepíší i odešlou
    await asyncio.gather(*(_deliver(_client, s, event, body) for s in subs))
