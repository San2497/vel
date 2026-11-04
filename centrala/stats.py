"""Statistika – počítá ji jen centrála, terminály ji čtou."""

from fastapi import APIRouter, HTTPException, Query

import db
from data import STANDS, STANDS_BY_ID
from models import Error, Stand, Stats, StandStats

router = APIRouter(tags=["stats"])


def _stand_stats(stand: Stand, totals: dict[str, tuple[int, int, int]]) -> StandStats:
    votes, rating_sum, favorites = totals.get(stand.id, (0, 0, 0))
    return StandStats(
        stand_id=stand.id,
        title=stand.title,
        floor=stand.floor,
        votes=votes,
        rating_sum=rating_sum,
        avg_rating=round(rating_sum / votes, 2) if votes else 0.0,
        favorites=favorites,
    )


@router.get("/api/v1/stats", response_model=Stats, summary="Statistika všech stánků")
def get_stats(floor: int | None = Query(None, ge=0, description="Jen stánky na tomto patře")) -> Stats:
    """Statistika všech stánků (i těch bez hlasu) v pořadí katalogu, volitelně jen pro jedno patro.
    `total_votes` je součet hlasů vrácených stánků.

    **Snapshot pro terminál:** terminál se nejdřív přihlásí k odběru, pak si stáhne tenhle stav a dál jen přičítá
    události z webhooků. `last_vote_seq` říká, kterým hlasem snapshot končí – událost s `data.seq <= last_vote_seq`
    už je ve snapshotu započítaná a terminál ji nesmí přičíst podruhé."""
    totals, last_seq = db.vote_totals()
    stands = [_stand_stats(s, totals) for s in STANDS if floor is None or s.floor == floor]
    return Stats(generated_at=db.utc_now(), total_votes=sum(s.votes for s in stands), last_vote_seq=last_seq, stands=stands)


@router.get(
    "/api/v1/stats/{stand_id}",
    response_model=StandStats,
    summary="Statistika jednoho stánku",
    responses={404: {"model": Error, "description": "Stánek neexistuje"}},
)
def get_stand_stats(stand_id: str) -> StandStats:
    """Jeden prvek pole `stands` ze statistiky."""
    stand = STANDS_BY_ID.get(stand_id)
    if stand is None:
        raise HTTPException(status_code=404, detail=f"Stánek {stand_id} neexistuje")
    return _stand_stats(stand, db.vote_totals()[0])
