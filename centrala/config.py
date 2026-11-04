"""Konfigurace centrály – čte se z proměnných prostředí, případně ze souboru .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# Veřejná adresa centrály, jak ji vidí telefon (žádné lomítko na konci).
# Ve škole jsou povolené porty 8080–8090 a 65525–65535 (https://www.spsejecna.cz/pc).
PUBLIC_URL: str = os.getenv("PUBLIC_URL", "http://localhost:8080").rstrip("/")


def stand_url(stand_id: str) -> str:
    """Adresa dotazníku pro daný stánek – právě tohle je zakódované v QR kódu."""
    return f"{PUBLIC_URL}/s/{stand_id}"
