"""Odběry terminálů – kam má centrála posílat události o nových hlasech."""

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Response

import db
from models import Error, Subscription, SubscriptionCreated, SubscriptionIn, VoteEvent

router = APIRouter(tags=["subscriptions"])


def register_webhook_docs(app: FastAPI) -> None:
    """Popis webhooku v OpenAPI (sekce `webhooks`) – co centrála posílá terminálům. Není to endpoint centrály."""

    @app.webhooks.post(
        "vote.created",
        summary="Nový hlas (centrála → terminál)",
        tags=["subscriptions"],
        responses={
            200: {"description": "Terminál událost přijal (jakýkoli 2xx = doručeno)"},
            401: {"description": "Terminál odmítl podpis (např. má starý secret) – počítá se jako nedoručeno"},
        },
    )
    def vote_created(
        event: VoteEvent,
        x_event_id: str = Header(description="ID události, stejné jako `id` v těle"),
        x_event_type: str = Header(description="Typ události, `vote.created`"),
        x_signature: str = Header(
            description="`sha256=` + hex HMAC-SHA256 surového těla; klíč = `secret` odběru jako text. "
            "Terminál ověří před parsováním, jinak `401`."
        ),
    ) -> None:
        """Centrála pošle `POST` na `callback_url` každého odběru, jehož `floor` je patro stánku nebo `null`.
        Posílá se až po odeslání odpovědi žákovi. Doručeno = `2xx` do 3 s; jinak opakování po 1, 2 a 4 s
        se stejným tělem i podpisem. Terminál musí duplicitu (stejné `id`) potvrdit `200` a nezapočítat."""


@router.post(
    "/api/v1/subscriptions",
    status_code=201,
    response_model=SubscriptionCreated,
    summary="Přihlásit terminál k odběru",
    responses={
        201: {"description": "Odběr založen. Odpověď obsahuje `secret` – vrací se jen teď."},
        422: {"description": "Neplatné tělo (např. `callback_url` není http/https adresa)"},
    },
)
def create_subscription(body: SubscriptionIn) -> SubscriptionCreated:
    """Terminál se při startu přihlásí: „tady je moje adresa, zajímá mě patro N“ (`floor: null` = všechna patra).

    - `secret` (32 náhodných bajtů, hex) se vrací **jen v této odpovědi**, uložte si ho spolu s `id`.
    - Přihlásí-li se znovu stejná `callback_url` (restart, přesun na jiné patro), starý odběr zanikne
      a vznikne nový s novým `id` i `secret`.
    - Při vypnutí terminál zavolá `DELETE /api/v1/subscriptions/{id}`.

    ### Co centrála posílá na `callback_url`

    Po každém uloženém hlasu na patře odběru (nebo na libovolném patře, je-li `floor: null`) přijde:

    ```
    POST {callback_url}
    Content-Type: application/json
    X-Event-Id: 0d6f3c7a-2a51-4c1e-9a7e-4f3b8f0e2d11
    X-Event-Type: vote.created
    X-Signature: sha256=5d1c…(64 hex znaků)

    {"id": "0d6f3c7a-2a51-4c1e-9a7e-4f3b8f0e2d11",
     "type": "vote.created",
     "created_at": "2026-11-05T09:15:00Z",
     "data": {"vote_id": "ff5186bd-…", "seq": 43, "stand_id": "S201",
              "title": "Rezervační systém pro školní učebny", "floor": 2,
              "rating": 5, "favorite": true, "created_at": "2026-11-05T09:15:00Z"}}
    ```

    #### Podpis `X-Signature`

    `X-Signature: sha256=<hex>`, kde `<hex>` = HMAC-SHA256 nad **surovými bajty těla**, klíč = `secret`
    tohoto odběru jako text (UTF-8 bajty 64znakového hex řetězce). Tělo se serializuje jednou; podepisují se
    a odesílají tytéž bajty. Terminál musí podpis ověřit **před** parsováním JSON (jiný serializátor = jiné bajty)
    a při chybějícím nebo neplatném podpisu odpovědět `401`. Ruční kontrola:
    `openssl dgst -sha256 -hmac "<secret>" telo.json`.

    #### Doručení

    - Doručeno = odpověď `2xx` do 3 s. Cokoli jiného (i `4xx`) nebo timeout = neúspěšný pokus.
    - Neúspěšný pokus se opakuje po 1 s, 2 s a 4 s (celkem 4 pokusy) se **stejným tělem i `X-Signature`**.
      Pak to centrála vzdá, zaloguje `id` nedoručené události a zvýší `failed_deliveries` odběru.
      Uložení hlasu tím ovlivněno není.
    - **Terminál musí být idempotentní:** stejná událost (stejné `id`) může přijít víckrát – třeba když terminál
      hlas zpracoval, ale jeho `200` se do 3 s nevrátilo. Už známé `id` → odpovědět `200` a nic nepřičítat.
      (Ne `409` – to by centrála brala jako chybu a opakovala by dál.)
    - Událost obsahuje jeden hlas – terminál ho přičte: `votes += 1`, `rating_sum += rating`,
      `favorites += favorite`, `avg_rating = rating_sum / votes`.
    - Jméno žáka se neposílá.
    - **Start terminálu:** nejdřív přihlásit odběr, potom stáhnout snapshot `GET /api/v1/stats?floor=N` a z něj nastavit
      stav. Události s `data.seq <= last_vote_seq` snapshotu už v něm jsou – nepřičítat. (Obráceně – snapshot před
      odběrem – by se hlas, který přijde mezi tím, ztratil.)
    - Úplné schéma je v sekci **Webhooks → vote.created** na konci této stránky.
    """
    return db.add_subscription(str(body.callback_url), body.floor)


@router.get(
    "/api/v1/subscriptions",
    response_model=list[Subscription],
    summary="Seznam odběrů",
)
def list_subscriptions(floor: int | None = Query(None, ge=0, description="Jen odběry pro toto patro")) -> list[Subscription]:
    """Všechny přihlášené terminály (bez `secret`), seřazené podle času přihlášení."""
    return db.list_subscriptions(floor)


@router.delete(
    "/api/v1/subscriptions/{subscription_id}",
    status_code=204,
    summary="Zrušit odběr",
    response_class=Response,
    responses={
        204: {"description": "Odběr zrušen"},
        404: {"model": Error, "description": "Odběr s tímto id neexistuje (nebo už byl zrušen)"},
    },
)
def delete_subscription(subscription_id: str) -> Response:
    """Terminál se odhlašuje (typicky při vypnutí)."""
    if not db.delete_subscription(subscription_id):
        raise HTTPException(status_code=404, detail=f"Odběr {subscription_id} neexistuje")
    return Response(status_code=204)
