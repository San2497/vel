"""Úložiště hlasů v SQLite – hlasy přežijí restart centrály."""

import os
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from models import Subscription, SubscriptionCreated, Vote

DB_PATH = os.getenv("DB_PATH") or str(Path(__file__).with_name("veletrh.db"))


class AlreadyVoted(Exception):
    pass


def utc_now() -> str:
    """Aktuální čas v UTC, ISO 8601 (např. 2026-10-22T08:15:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def username_key(username: str) -> str:
    """Klíč pro porovnání jmen: bez diakritiky a bez ohledu na velikost písmen (Novák.Jan == novak.jan)."""
    decomposed = unicodedata.normalize("NFKD", username)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        # Migrace: starší verze měla subscriptions.floor NOT NULL – teď smí být NULL (= všechna patra).
        cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(subscriptions)")}
        if cols.get("floor") is not None and cols["floor"]["notnull"]:
            conn.execute("ALTER TABLE subscriptions RENAME TO subscriptions_old")
            _create_tables(conn)
            conn.execute("INSERT INTO subscriptions SELECT * FROM subscriptions_old")
            conn.execute("DROP TABLE subscriptions_old")
        # Migrace: votes dostává sloupec seq (AUTOINCREMENT = číslo se nikdy nepoužije znovu, ani po smazání).
        vote_cols = {r["name"] for r in conn.execute("PRAGMA table_info(votes)")}
        if vote_cols and "seq" not in vote_cols:
            conn.execute("ALTER TABLE votes RENAME TO votes_old")
            _create_tables(conn)
            conn.execute(
                "INSERT INTO votes (seq, id, stand_id, username, username_key, rating, favorite, created_at)"
                " SELECT rowid, id, stand_id, username, username_key, rating, favorite, created_at"
                " FROM votes_old ORDER BY rowid"
            )
            conn.execute("DROP TABLE votes_old")
        _create_tables(conn)


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS votes (
            seq          INTEGER PRIMARY KEY AUTOINCREMENT,  -- pořadové číslo hlasu, roste a neopakuje se
            id           TEXT NOT NULL UNIQUE,
            stand_id     TEXT NOT NULL,
            username     TEXT NOT NULL,
            username_key TEXT NOT NULL,
            rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            favorite     INTEGER NOT NULL,
            created_at   TEXT NOT NULL,
            UNIQUE (stand_id, username_key)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS subscriptions (
            id                TEXT PRIMARY KEY,
            callback_url      TEXT NOT NULL UNIQUE,
            floor             INTEGER,  -- NULL = všechna patra
            secret            TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            last_delivery_at  TEXT,
            failed_deliveries INTEGER NOT NULL DEFAULT 0
        )"""
    )


def add_vote(stand_id: str, username: str, rating: int, favorite: bool) -> tuple[Vote, int]:
    """Uloží hlas. Vrací (hlas, seq) – seq je rostoucí pořadové číslo hlasu (nikdy se neopakuje)."""
    vote = Vote(
        id=str(uuid.uuid4()),
        stand_id=stand_id,
        username=username,
        rating=rating,
        favorite=favorite,
        created_at=utc_now(),
    )
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO votes (id, stand_id, username, username_key, rating, favorite, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (vote.id, stand_id, username, username_key(username), rating, int(favorite), vote.created_at),
            )
    except sqlite3.IntegrityError as e:
        raise AlreadyVoted from e
    return vote, cur.lastrowid


def vote_totals() -> tuple[dict[str, tuple[int, int, int]], int]:
    """Pro každý stánek s aspoň jedním hlasem: (počet hlasů, součet hodnocení, počet favoritů),
    a k tomu seq posledního započítaného hlasu. Obojí jedním SQL dotazem = jeden konzistentní stav."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT stand_id, COUNT(*), SUM(rating), SUM(favorite), (SELECT MAX(seq) FROM votes)"
            " FROM votes GROUP BY stand_id"
        ).fetchall()
    last_seq = rows[0][4] if rows else 0
    return {r[0]: (r[1], r[2], r[3]) for r in rows}, last_seq


# ---------- Odběry terminálů ----------

_SUB_COLUMNS = "id, callback_url, floor, created_at, last_delivery_at, failed_deliveries"


def add_subscription(callback_url: str, floor: int | None) -> SubscriptionCreated:
    """Založí odběr. Stejná callback_url nahradí starý odběr (restart terminálu, přesun na jiné patro)."""
    sub = SubscriptionCreated(
        id=str(uuid.uuid4()),
        callback_url=callback_url,
        floor=floor,
        created_at=utc_now(),
        secret=secrets.token_hex(32),  # 32 bajtů z kryptografického generátoru
    )
    with _connect() as conn:
        conn.execute("DELETE FROM subscriptions WHERE callback_url = ?", (callback_url,))
        conn.execute(
            "INSERT INTO subscriptions (id, callback_url, floor, secret, created_at) VALUES (?, ?, ?, ?, ?)",
            (sub.id, sub.callback_url, sub.floor, sub.secret, sub.created_at),
        )
    return sub


def list_subscriptions(floor: int | None = None) -> list[Subscription]:
    with _connect() as conn:
        if floor is None:
            rows = conn.execute(f"SELECT {_SUB_COLUMNS} FROM subscriptions ORDER BY created_at").fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_SUB_COLUMNS} FROM subscriptions WHERE floor = ? ORDER BY created_at", (floor,)
            ).fetchall()
    return [Subscription(**dict(r)) for r in rows]


def delete_subscription(sub_id: str) -> bool:
    with _connect() as conn:
        return conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,)).rowcount > 0


def subscribers_for_floor(floor: int) -> list[sqlite3.Row]:
    """Odběry, kterým patří událost z daného patra: stejné patro nebo NULL (všechna patra). Včetně secret."""
    with _connect() as conn:
        return conn.execute(
            "SELECT id, callback_url, secret FROM subscriptions WHERE floor = ? OR floor IS NULL", (floor,)
        ).fetchall()


def record_delivery(sub_id: str, ok: bool) -> None:
    with _connect() as conn:
        if ok:
            conn.execute(
                "UPDATE subscriptions SET last_delivery_at = ?, failed_deliveries = 0 WHERE id = ?", (utc_now(), sub_id)
            )
        else:
            conn.execute("UPDATE subscriptions SET failed_deliveries = failed_deliveries + 1 WHERE id = ?", (sub_id,))
