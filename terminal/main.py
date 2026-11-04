"""Terminál (server B) – zobrazuje statistiku jednoho patra.

REST pro stav, webhook pro změny: při startu se terminál přihlásí k odběru, POTOM si jednou stáhne
snapshot GET /api/v1/stats?floor=N a dál jen přičítá události, které mu centrála posílá na POST /webhooks/votes.

Spuštění:  .venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8081
Dokumentace: http://localhost:8081/docs  ·  http://localhost:8081/openapi.json
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

import config
from page import PAGE
from signature import SignatureMiddleware

log = logging.getLogger("uvicorn.error")


# ---------- Událost od centrály (čteme jen, co potřebujeme; cizí pole ignorujeme) ----------

class VoteEventData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    seq: int | None = Field(None, description="Pořadové číslo hlasu (porovnává se s last_vote_seq snapshotu)", examples=[43])
    stand_id: str = Field(examples=["S201"])
    title: str = Field(examples=["Rezervační systém pro školní učebny"])
    floor: int = Field(examples=[2])
    rating: int = Field(ge=1, le=5, examples=[5])
    favorite: bool = Field(examples=[True])


class VoteEvent(BaseModel):
    """Událost `vote.created` tak, jak ji posílá centrála."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": "0d6f3c7a-2a51-4c1e-9a7e-4f3b8f0e2d11",
                "type": "vote.created",
                "created_at": "2026-11-05T09:15:00Z",
                "data": {"vote_id": "ff5186bd-b771-4f19-9c6c-058a248e7e21", "stand_id": "S201",
                         "title": "Rezervační systém pro školní učebny", "floor": 2,
                         "rating": 5, "favorite": True, "created_at": "2026-11-05T09:15:00Z"},
            }
        },
    )
    id: str
    type: Literal["vote.created"]
    data: VoteEventData


class SnapshotStand(BaseModel):
    model_config = ConfigDict(extra="ignore")
    stand_id: str
    title: str
    floor: int | None = None
    votes: int
    rating_sum: int | None = None  # kdyby ho centrála neposílala, dopočítáme z průměru
    avg_rating: float
    favorites: int


class Snapshot(BaseModel):
    """Odpověď centrály na GET /api/v1/stats?floor=N."""

    model_config = ConfigDict(extra="ignore")
    last_vote_seq: int | None = None
    stands: list[SnapshotStand]


class WebhookAck(BaseModel):
    applied: bool = Field(description="true = hlas byl přičten do statistiky; false = událost ignorována")
    detail: str


# ---------- Co terminál vystavuje ----------

class TerminalStand(BaseModel):
    stand_id: str = Field(examples=["S201"])
    title: str = Field(examples=["Rezervační systém pro školní učebny"])
    votes: int = Field(ge=0, examples=[2])
    avg_rating: float = Field(ge=0, le=5, examples=[4.5])
    favorites: int = Field(ge=0, examples=[1])


class TerminalStats(BaseModel):
    """Co terminál právě zobrazuje: stánky jeho patra seřazené podle průměru (sestupně)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "floor": 2,
                "total_votes": 3,
                "stands": [
                    {"stand_id": "S201", "title": "Rezervační systém pro školní učebny",
                     "votes": 2, "avg_rating": 4.5, "favorites": 1}
                ],
            }
        }
    )

    floor: int = Field(description="Patro tohoto terminálu", examples=[2])
    total_votes: int = Field(ge=0, description="Součet hlasů na patře")
    stands: list[TerminalStand] = Field(description="Seřazeno podle avg_rating sestupně, pak podle počtu hlasů")


class Health(BaseModel):
    floor: int
    central_url: str
    my_url: str = Field(description="Veřejná adresa terminálu (MY_URL)")
    subscription_id: str | None = Field(description="ID odběru u centrály, null dokud se nepodařilo přihlásit")
    events_applied: int = Field(description="Kolik hlasů terminál od startu přičetl")
    events_ignored: int = Field(description="Kolik událostí ignoroval (jiné patro)")
    events_duplicate: int = Field(description="Kolik duplicitních událostí (už známé id) potvrdil bez započítání")
    events_in_snapshot: int = Field(description="Kolik událostí přeskočil, protože hlas už byl ve snapshotu")
    snapshot_loaded: bool = Field(description="Je načtený počáteční stav z centrály?")
    snapshot_seq: int | None = Field(description="last_vote_seq načteného snapshotu")
    seen_event_ids: int = Field(description=f"Kolik id událostí si terminál pamatuje (max {config.MAX_SEEN_EVENTS})")
    last_event_at: str | None = Field(description="Kdy přišla poslední událost (UTC, ISO 8601)")


# ---------- Stav v paměti ----------

@dataclass
class StandTally:
    title: str
    votes: int = 0
    rating_sum: int = 0
    favorites: int = 0


class State:
    def __init__(self) -> None:
        self.stands: dict[str, StandTally] = {}
        self.subscription_id: str | None = None
        self.secret: str | None = None  # pro ověření podpisu webhooků (#8); nikdy ho nevystavujeme ven
        self.events_applied = 0
        self.events_ignored = 0
        self.events_duplicate = 0
        self.events_in_snapshot = 0
        # Snapshot: dokud není načtený, události se jen odkládají do fronty.
        self.snapshot_loaded = False
        self.snapshot_seq: int | None = None
        self.pending: list[VoteEventData] = []
        self.last_event_at: str | None = None
        # id zpracovaných událostí, nejstarší první; omezené na MAX_SEEN_EVENTS
        self.seen: OrderedDict[str, None] = OrderedDict()
        # simulace výpadku (jen s DEBUG=1): kolik příštích odpovědí na webhook zdržet a o kolik sekund
        self.slow_count = 0
        self.slow_seconds = 0.0

    def remember(self, event_id: str) -> bool:
        """Zapamatuje si id. Vrátí False, pokud ho už znal (= duplicita)."""
        if event_id in self.seen:
            return False
        self.seen[event_id] = None
        if len(self.seen) > config.MAX_SEEN_EVENTS:
            self.seen.popitem(last=False)  # zapomeň nejstarší
        return True


state = State()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_stats() -> TerminalStats:
    stands = [
        TerminalStand(
            stand_id=sid,
            title=t.title,
            votes=t.votes,
            avg_rating=round(t.rating_sum / t.votes, 2) if t.votes else 0.0,
            favorites=t.favorites,
        )
        for sid, t in state.stands.items()
    ]
    stands.sort(key=lambda s: (-s.avg_rating, -s.votes, s.stand_id))
    return TerminalStats(floor=config.FLOOR, total_votes=sum(s.votes for s in stands), stands=stands)


def apply_vote(d: VoteEventData) -> bool:
    """Přičte hlas do statistiky. Vrátí False, když už je ve snapshotu (seq <= last_vote_seq)."""
    if state.snapshot_seq is not None and d.seq is not None and d.seq <= state.snapshot_seq:
        state.events_in_snapshot += 1
        return False
    tally = state.stands.setdefault(d.stand_id, StandTally(title=d.title))
    tally.title = d.title
    tally.votes += 1
    tally.rating_sum += d.rating
    tally.favorites += int(d.favorite)
    state.events_applied += 1
    return True


def set_snapshot(snap: Snapshot) -> None:
    """Nastaví stav ze snapshotu a dorovná události, které přišly během stahování.
    Běží celé bez await – žádný webhook se mezi tím nemůže vklínit."""
    state.stands = {
        s.stand_id: StandTally(
            title=s.title,
            votes=s.votes,
            rating_sum=s.rating_sum if s.rating_sum is not None else round(s.avg_rating * s.votes),
            favorites=s.favorites,
        )
        for s in snap.stands
        if s.floor is None or s.floor == config.FLOOR  # pojistka, kdyby centrála filtr patra ignorovala
    }
    state.snapshot_seq = snap.last_vote_seq
    pending, state.pending = state.pending, []
    for d in pending:
        if d.seq is None:
            # Centrála bez seq: událost přišla dřív než snapshot, takže v něm skoro jistě je.
            state.events_in_snapshot += 1
        else:
            apply_vote(d)
    state.snapshot_loaded = True
    log.info("Snapshot patra %s načten: %d hlasů, last_vote_seq=%s, dorovnáno %d událostí z fronty",
             config.FLOOR, sum(t.votes for t in state.stands.values()), snap.last_vote_seq, len(pending))


async def load_snapshot() -> None:
    """GET /api/v1/stats?floor=N – jednou po přihlášení. Když centrála neodpovídá, zkouší to znovu."""
    delay = 1.0
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                r = await client.get(f"{config.CENTRAL_URL}/api/v1/stats", params={"floor": config.FLOOR})
                r.raise_for_status()
                set_snapshot(Snapshot.model_validate(r.json()))
                return
            except Exception as e:
                log.warning("Snapshot se nepodařilo načíst (%s: %s), zkusím znovu za %.0f s", type(e).__name__, e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


# ---------- Odběr u centrály ----------

SUBSCRIPTIONS_URL = f"{config.CENTRAL_URL}/api/v1/subscriptions"
CALLBACK_URL = f"{config.MY_URL}/webhooks/votes"
# id a secret si terminál ukládá i do souboru vedle sebe (není v gitu) – kvůli ručnímu ověření podpisu.
SUBSCRIPTION_FILE = Path(__file__).with_name(f".subscription-{urlparse(config.MY_URL).port or 80}.json")


async def subscribe() -> None:
    """Přihlásí terminál k odběru. Když centrála neodpovídá, zkouší to znovu, dokud se to nepovede."""
    delay = 1.0
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                r = await client.post(SUBSCRIPTIONS_URL, json={"callback_url": CALLBACK_URL, "floor": config.FLOOR})
                r.raise_for_status()
                data = r.json()
                state.subscription_id, state.secret = data["id"], data["secret"]
                SUBSCRIPTION_FILE.write_text(json.dumps(
                    {"id": data["id"], "secret": data["secret"], "callback_url": CALLBACK_URL,
                     "floor": config.FLOOR, "central_url": config.CENTRAL_URL}, indent=2), encoding="utf-8")
                log.info("Přihlášen k odběru patra %s: id=%s, callback=%s", config.FLOOR, state.subscription_id, CALLBACK_URL)
                return
            except Exception as e:
                log.warning("Přihlášení k odběru se nepovedlo (%s: %s), zkusím znovu za %.0f s", type(e).__name__, e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


async def unsubscribe() -> None:
    """Při vypnutí se odhlásí. Když to nevyjde (centrála nedostupná), nevadí: další přihlášení
    se stejnou callback_url starý odběr na centrále nahradí."""
    if state.subscription_id is None:
        return
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.delete(f"{SUBSCRIPTIONS_URL}/{state.subscription_id}")
        log.info("Odhlášen z odběru %s (HTTP %s)", state.subscription_id, r.status_code)
        SUBSCRIPTION_FILE.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Odhlášení se nepovedlo: %s: %s", type(e).__name__, e)


async def connect() -> None:
    # Pořadí je důležité: NEJDŘÍV odběr, POTOM snapshot. Obráceně by se hlas mezi tím ztratil.
    await subscribe()
    await load_snapshot()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(connect())
    yield
    task.cancel()
    await unsubscribe()


app = FastAPI(
    title=f"Veletrh – Terminál (patro {config.FLOOR})",
    version="1.0.0",
    description=f"Terminál pro patro {config.FLOOR}. Při startu se přihlásí k odběru u centrály `{config.CENTRAL_URL}` "
    ", stáhne si snapshot `GET /api/v1/stats?floor=N` a dál přičítá události z webhooků.",
    lifespan=lifespan,
)
# Každý POST /webhooks/votes musí mít platný podpis – jinak 401 a do endpointu se vůbec nedostane.
app.add_middleware(SignatureMiddleware, path="/webhooks/votes", get_secret=lambda: state.secret)


# ---------- Endpointy ----------

@app.post(
    "/webhooks/votes",
    response_model=WebhookAck,
    tags=["webhooks"],
    summary="Příjem události od centrály",
    responses={
        401: {"description": "Chybí nebo nesedí `X-Signature` (nic se nezapočítá)"},
        422: {"description": "Podpis sedí, ale tělo není platná událost `vote.created`"},
    },
)
async def receive_vote(
    event: VoteEvent,
    x_signature: str = Header(
        description="`sha256=` + hex HMAC-SHA256 surového těla, klíč = `secret` z odběru (jako text). "
        "Ověřuje middleware ještě před parsováním JSON.",
        examples=["sha256=3f0a…"],
    ),
    x_event_id: str | None = Header(None, description="ID události (stejné jako `id` v těle)"),
) -> WebhookAck:
    """Centrála sem po každém hlasu pošle událost `vote.created`.

    Nejdřív se ověří podpis nad surovými bajty těla (middleware): chybí nebo nesedí → `401` a nic se nezapočítá.

    Hlas se přičte hned při přijetí – ještě před odpovědí, takže `200` znamená „započítáno“.
    Dokud není načtený snapshot, události se odkládají do fronty a po načtení se dorovnají
    (přičtou se jen ty s `data.seq` větším než `last_vote_seq` snapshotu).
    Událost z jiného patra se ignoruje (také `200`, ať ji centrála neposílá znovu).

    **Idempotence:** terminál si pamatuje `id` zpracovaných událostí (posledních `MAX_SEEN_EVENTS`).
    Stejné `id` podruhé → `200` a statistika beze změny. Ne `409`: centrála by to brala jako chybu
    doručení a opakovala by, ačkoli terminál událost už má."""
    d = event.data
    state.last_event_at = utc_now()
    # Mezi kontrolou a zápisem není žádný await → dvě souběžné kopie téže události se nemohou předběhnout.
    if not state.remember(event.id):
        state.events_duplicate += 1
        return WebhookAck(applied=False, detail=f"Duplicitní událost {event.id} – už započítána, beze změny")
    if d.floor != config.FLOOR:
        state.events_ignored += 1
        return WebhookAck(applied=False, detail=f"Stánek {d.stand_id} je na patře {d.floor}, terminál zobrazuje patro {config.FLOOR}")
    if not state.snapshot_loaded:
        state.pending.append(d)
        return WebhookAck(applied=False, detail="Přijato do fronty – započítá se po načtení snapshotu, pokud v něm hlas ještě není")
    if not apply_vote(d):
        return WebhookAck(applied=False, detail=f"Hlas seq={d.seq} už je ve snapshotu – beze změny")
    if state.slow_count > 0:  # simulace zaseklé sítě: hlas už je započítaný, jen odpověď přijde pozdě
        state.slow_count -= 1
        await asyncio.sleep(state.slow_seconds)
    return WebhookAck(applied=True, detail=f"Hlas pro {d.stand_id} přičten")


@app.get(
    "/stats",
    response_model=TerminalStats,
    tags=["stats"],
    summary="Co terminál právě zobrazuje",
    responses={503: {"description": "Terminál ještě nenačetl snapshot z centrály"}},
)
async def get_stats() -> TerminalStats:
    """Statistika patra tohoto terminálu, seřazená podle průměrného hodnocení (sestupně).
    Ze snapshotu jsou tu všechny stánky patra, i ty zatím bez hlasu."""
    if not state.snapshot_loaded:
        raise HTTPException(status_code=503, detail="Načítám stav z centrály")
    return current_stats()


@app.get("/health", response_model=Health, tags=["stats"], summary="Stav terminálu a odběru")
async def health() -> Health:
    return Health(
        floor=config.FLOOR,
        central_url=config.CENTRAL_URL,
        my_url=config.MY_URL,
        subscription_id=state.subscription_id,
        events_applied=state.events_applied,
        events_ignored=state.events_ignored,
        events_duplicate=state.events_duplicate,
        events_in_snapshot=state.events_in_snapshot,
        snapshot_loaded=state.snapshot_loaded,
        snapshot_seq=state.snapshot_seq,
        seen_event_ids=len(state.seen),
        last_event_at=state.last_event_at,
    )


if config.DEBUG:

    class SlowMode(BaseModel):
        count: int
        seconds: float

    @app.post("/debug/slow", response_model=SlowMode, tags=["debug"], summary="Simulace výpadku (jen DEBUG=1)")
    async def debug_slow(
        seconds: float = Query(5, ge=0, le=60, description="O kolik sekund zdržet odpověď"),
        count: int = Query(1, ge=0, le=100, description="Kolik příštích přijatých hlasů se zdrží"),
    ) -> SlowMode:
        """Příštích `count` přijatých hlasů terminál normálně započítá, ale odpoví až po `seconds` s –
        jako když se odpověď zasekne na Wi-Fi. Centrála ohlásí timeout a pošle událost znovu."""
        state.slow_count, state.slow_seconds = count, seconds
        return SlowMode(count=count, seconds=seconds)


@app.get(
    "/",
    response_class=HTMLResponse,
    tags=["screen"],
    summary="Stránka pro obrazovku",
    responses={200: {"content": {"text/html": {}}, "description": "Tabulka stánků, sama se obnovuje z /stats"}},
)
def screen():
    return PAGE.replace("{{FLOOR}}", str(config.FLOOR))
