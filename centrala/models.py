from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Stand(BaseModel):
    """Jeden stánek na veletrhu."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "S201",
                "title": "Rezervační systém pro školní učebny",
                "authors": ["Marek Horák"],
                "class_name": "C4a",
                "floor": 2,
                "room": "201",
            }
        }
    )

    id: str = Field(description="Kód stánku (je i v QR kódu)", examples=["S201"])
    title: str = Field(description="Název projektu")
    authors: list[str] = Field(description="Autoři projektu")
    class_name: str = Field(description="Třída autorů", examples=["C4a"])
    floor: int = Field(ge=0, description="Patro, na kterém stánek stojí", examples=[2])
    room: str = Field(description="Učebna", examples=["201"])


USERNAME_PATTERN = r"^[\w.-]+$"


class VoteIn(BaseModel):
    """Hlas žáka pro jeden stánek. Pravidla jsou tady – platí pro validaci i dokumentaci."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={"example": {"username": "novak.jan", "rating": 5, "favorite": True}},
    )

    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=USERNAME_PATTERN,
        description=(
            "Uživatelské jméno žáka, 3–32 znaků: písmena (i s diakritikou), číslice, tečka, podtržítko, pomlčka. "
            "Jeden žák hlasuje pro stánek jen jednou; jména se porovnávají bez ohledu na velikost písmen a diakritiku "
            "(`Novák.Jan` = `novak.jan`)."
        ),
        examples=["novak.jan"],
    )
    rating: int = Field(strict=True, ge=1, le=5, description="Hodnocení 1 (nejhorší) až 5 (nejlepší), celé číslo")
    favorite: bool = Field(strict=True, description="Je to žákův favorit? `true` / `false`")


class Vote(BaseModel):
    """Uložený hlas."""

    id: str = Field(description="ID hlasu (UUID)")
    stand_id: str = Field(examples=["S201"])
    username: str = Field(examples=["novak.jan"])
    rating: int = Field(ge=1, le=5, examples=[5])
    favorite: bool
    created_at: str = Field(description="Čas uložení, ISO 8601 v UTC", examples=["2026-11-05T09:15:00Z"])


class StandStats(BaseModel):
    """Statistika jednoho stánku."""

    stand_id: str = Field(examples=["S201"])
    title: str = Field(examples=["Rezervační systém pro školní učebny"])
    floor: int = Field(examples=[2])
    votes: int = Field(ge=0, description="Počet hlasů", examples=[2])
    rating_sum: int = Field(ge=0, description="Součet hodnocení", examples=[9])
    avg_rating: float = Field(
        ge=0, le=5, description="Průměrné hodnocení zaokrouhlené na 2 desetinná místa; 0.0, pokud stánek nemá hlas", examples=[4.5]
    )
    favorites: int = Field(ge=0, description="Kolikrát byl stánek označen jako favorit", examples=[1])


class Stats(BaseModel):
    """Statistika veletrhu (případně jen jednoho patra). Obsahuje všechny stánky, i ty bez hlasů."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "generated_at": "2026-10-22T08:15:00Z",
                "total_votes": 3,
                "last_vote_seq": 42,
                "stands": [
                    {"stand_id": "S201", "title": "Rezervační systém pro školní učebny", "floor": 2,
                     "votes": 2, "rating_sum": 9, "avg_rating": 4.5, "favorites": 1},
                    {"stand_id": "S202", "title": "Mobilní aplikace pro jídelníček", "floor": 2,
                     "votes": 1, "rating_sum": 3, "avg_rating": 3.0, "favorites": 0},
                ],
            }
        }
    )

    generated_at: str = Field(description="Čas vygenerování, ISO 8601 v UTC", examples=["2026-10-22T08:15:00Z"])
    total_votes: int = Field(ge=0, description="Součet hlasů přes všechny vrácené stánky")
    last_vote_seq: int = Field(
        ge=0,
        description="Pořadové číslo (`seq`) posledního hlasu, který je v této statistice započítaný; 0 = žádný hlas. "
        "Terminál po načtení snapshotu přičítá jen události s `data.seq` větším než tato hodnota.",
        examples=[42],
    )
    stands: list[StandStats]


class SubscriptionIn(BaseModel):
    """Přihlášení terminálu k odběru událostí jednoho patra."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"callback_url": "http://10.2.0.21:8081/webhooks/votes", "floor": 2}}
    )

    callback_url: HttpUrl = Field(
        description="Kam má centrála posílat události (webhook) – adresa terminálu, typicky `{MY_URL}/webhooks/votes`. "
        "Přihlásí-li se znovu stejná adresa (restart, přesun na jiné patro), starý odběr se nahradí.",
        examples=["http://10.2.0.21:8081/webhooks/votes"],
    )
    floor: int | None = Field(
        None, ge=0, description="Patro, jehož hlasy terminál zajímají; `null` = všechna patra", examples=[2]
    )


class Subscription(BaseModel):
    """Odběr terminálu (bez tajného klíče)."""

    id: str = Field(description="ID odběru (UUID) – použijte pro DELETE", examples=["5b7d1c1e-8a7e-4a57-9f55-3f1f0b3c2a10"])
    callback_url: str = Field(examples=["http://10.2.0.21:8081/webhooks/votes"])
    floor: int | None = Field(description="Patro odběru; `null` = všechna patra", examples=[2])
    created_at: str = Field(description="Čas přihlášení, ISO 8601 v UTC", examples=["2026-11-05T07:55:00Z"])
    last_delivery_at: str | None = Field(None, description="Čas posledního úspěšně doručeného webhooku (UTC), jinak null")
    failed_deliveries: int = Field(0, description="Počet po sobě jdoucích nedoručených webhooků")


class SubscriptionCreated(Subscription):
    """Odpověď na přihlášení – jediné místo, kde se vrací `secret`."""

    secret: str = Field(
        description="Tajný klíč pro ověření podpisu webhooků (HMAC). 32 náhodných bajtů jako 64 hex znaků. "
        "Vrací se JEN v této odpovědi – terminál si ho musí uložit.",
        examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"],
    )


class VoteEventData(BaseModel):
    """Nový hlas – vše, co terminál potřebuje, aby ho přičetl do statistiky (bez jména žáka)."""

    vote_id: str = Field(description="ID hlasu (UUID)", examples=["ff5186bd-b771-4f19-9c6c-058a248e7e21"])
    seq: int = Field(
        ge=1, description="Rostoucí pořadové číslo hlasu. Porovnejte s `last_vote_seq` ze snapshotu `GET /api/v1/stats`.",
        examples=[43],
    )
    stand_id: str = Field(examples=["S201"])
    title: str = Field(description="Název projektu, aby terminál nemusel znát katalog", examples=["Rezervační systém pro školní učebny"])
    floor: int = Field(description="Patro stánku", examples=[2])
    rating: int = Field(ge=1, le=5, examples=[5])
    favorite: bool = Field(examples=[True])
    created_at: str = Field(description="Kdy byl hlas uložen, ISO 8601 v UTC", examples=["2026-11-05T09:15:00Z"])


class VoteEvent(BaseModel):
    """Událost, kterou centrála posílá jako `POST` na `callback_url` odběru."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "0d6f3c7a-2a51-4c1e-9a7e-4f3b8f0e2d11",
                "type": "vote.created",
                "created_at": "2026-11-05T09:15:00Z",
                "data": {
                    "vote_id": "ff5186bd-b771-4f19-9c6c-058a248e7e21",
                    "seq": 43,
                    "stand_id": "S201",
                    "title": "Rezervační systém pro školní učebny",
                    "floor": 2,
                    "rating": 5,
                    "favorite": True,
                    "created_at": "2026-11-05T09:15:00Z",
                },
            }
        }
    )

    id: str = Field(description="ID události (UUID), stejné jako hlavička `X-Event-Id`. Podle něj terminál pozná duplicitu.")
    type: Literal["vote.created"] = Field(description="Typ události, stejný jako hlavička `X-Event-Type`")
    created_at: str = Field(description="Kdy událost vznikla, ISO 8601 v UTC")
    data: VoteEventData


class Error(BaseModel):
    detail: str
