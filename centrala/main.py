"""Centrála (server A) – katalog stánků, hlasování a rozesílání událostí terminálům.

Spuštění:  .venv/Scripts/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8080
Dokumentace: http://localhost:8080/docs  ·  http://localhost:8080/openapi.json
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

import db
import qr
import stats
import subscriptions
import survey
import webhooks
from data import STANDS, STANDS_BY_ID
from models import Error, Stand


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await webhooks.start()
    yield
    await webhooks.stop()


app = FastAPI(
    title="Veletrh – Centrála",
    version="1.0.0",
    description="Centrála veletrhu projektů: katalog stánků, QR kódy, dotazník, příjem hlasů, statistika a webhooky pro terminály.",
    openapi_tags=[
        {"name": "stands", "description": "Katalog stánků"},
        {"name": "votes", "description": "Příjem hlasů žáků"},
        {"name": "stats", "description": "Statistika hlasování (počítá ji centrála)"},
        {"name": "subscriptions", "description": "Odběry terminálů – kam posílat webhooky o nových hlasech"},
        {"name": "survey", "description": "Dotazník pro žáky (HTML)"},
        {"name": "qr", "description": "QR kódy vedoucí na dotazník stánku"},
    ],
    lifespan=lifespan,
)
app.include_router(survey.router)
app.include_router(stats.router)
app.include_router(subscriptions.router)
subscriptions.register_webhook_docs(app)
app.include_router(qr.router)


@app.get(
    "/api/v1/stands",
    response_model=list[Stand],
    tags=["stands"],
    summary="Seznam stánků",
)
def list_stands(
    floor: int | None = Query(None, ge=0, description="Vrátí jen stánky na tomto patře"),
) -> list[Stand]:
    """Vrátí všechny stánky, volitelně filtrované podle patra."""
    if floor is None:
        return STANDS
    return [s for s in STANDS if s.floor == floor]


@app.get(
    "/api/v1/stands/{stand_id}",
    response_model=Stand,
    tags=["stands"],
    summary="Detail stánku",
    responses={404: {"model": Error, "description": "Stánek neexistuje"}},
)
def get_stand(stand_id: str) -> Stand:
    stand = STANDS_BY_ID.get(stand_id)
    if stand is None:
        raise HTTPException(status_code=404, detail=f"Stánek {stand_id} neexistuje")
    return stand
