"""Konfigurace terminálu – z proměnných prostředí, případně ze souboru .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# Adresa centrály (bez lomítka na konci). Ve škole jen porty 8080–8090 a 65525–65535.
CENTRAL_URL: str = os.getenv("CENTRAL_URL", "http://127.0.0.1:8080").rstrip("/")
# Patro, které terminál zobrazuje.
FLOOR: int = int(os.getenv("FLOOR", "2"))
# Veřejná adresa tohoto terminálu, jak ji vidí centrála (musí sedět s portem, na kterém běží).
MY_URL: str = os.getenv("MY_URL", "http://127.0.0.1:8081").rstrip("/")
# Kolik id zpracovaných událostí si pamatovat (ochrana proti duplicitám; starší se zapomínají).
MAX_SEEN_EVENTS: int = int(os.getenv("MAX_SEEN_EVENTS", "10000"))
# DEBUG=1 zapne ladicí endpointy (/debug/slow – simulace výpadku). Na veletrhu nechte vypnuté.
DEBUG: bool = os.getenv("DEBUG", "0").lower() in ("1", "true", "yes")
