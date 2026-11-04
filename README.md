# Veletrh projektů – hodnocení stánků

Žáci naskenují QR kód u stánku, vyplní dotazník a odešlou hlas. Obrazovka na každém patře okamžitě ukazuje statistiku.

- **`centrala/`** – server A: katalog stánků, QR kódy, dotazník, příjem hlasů, statistika, odběry a webhooky pro terminály.
- **`terminal/`** – server B: přihlásí se k odběru jednoho patra, načte snapshot, přijímá podepsané webhooky a zobrazuje obrazovku.

Oba servery mají dokumentaci generovanou z kódu na `/docs` (Swagger UI) a `/openapi.json`.

> **Ve škole:** podrobný postup nastavení, spuštění a řešení problémů je v [SKOLA.md](SKOLA.md).

## Instalace (na každém PC zvlášť, Python 3.10+)

V obou složkách `centrala` i `terminal`:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env      # a upravte adresy
```

## Konfigurace

Ve škole jsou povolené jen porty **8080–8090** a 65525–65535, síť `10.2.0.0/16`. Svou IP zjistíte příkazem `ipconfig`.

`centrala/.env`

| Proměnná | Význam |
|---|---|
| `PUBLIC_URL` | Adresa centrály, kterou otevře telefon (je v QR kódech), např. `http://10.2.5.17:8080` |

`terminal/.env`

| Proměnná | Význam |
|---|---|
| `CENTRAL_URL` | Adresa centrály, např. `http://10.2.5.17:8080` |
| `MY_URL` | Adresa tohoto terminálu, jak ji vidí centrála, např. `http://10.2.5.23:8081` |
| `FLOOR` | Patro, které terminál zobrazuje |
| `MAX_SEEN_EVENTS` | Kolik id událostí si pamatovat kvůli duplicitám (výchozí 10000) |
| `DEBUG` | `1` zapne `/debug/slow` pro simulaci výpadku; na veletrhu `0` |

## Spuštění

```bash
cd centrala
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

```bash
cd terminal
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8081
```

- QR kódy k tisku: `http://<centrála>:8080/qr`
- Obrazovka patra: `http://<terminál>:8081/`
- Odběry terminálů: `http://<centrála>:8080/api/v1/subscriptions`

Bez `--host 0.0.0.0` je server dostupný jen z vlastního PC. Po změně `PUBLIC_URL` je potřeba QR kódy vytisknout znovu.

## Hlavní endpointy

**Centrála**

| Metoda a cesta | Popis |
|---|---|
| `GET /api/v1/stands?floor=` | Seznam stánků |
| `GET /qr/{id}.svg`, `.png`, `GET /qr` | QR kódy |
| `GET /s/{id}` | Dotazník pro telefon |
| `POST /api/v1/stands/{id}/votes` | Hlas – `201`, `404`, `409` už hlasoval, `422` neplatné tělo |
| `GET /api/v1/stats?floor=`, `GET /api/v1/stats/{id}` | Statistika (snapshot pro terminál, včetně `rating_sum` a `last_vote_seq`) |
| `POST/GET /api/v1/subscriptions`, `DELETE /api/v1/subscriptions/{id}` | Odběry terminálů |

**Terminál**

| Metoda a cesta | Popis |
|---|---|
| `POST /webhooks/votes` | Příjem události `vote.created` |
| `GET /stats` | Co terminál zobrazuje, seřazeno podle průměru |
| `GET /` | Obrazovka |
| `GET /health` | Stav odběru a snapshotu |

## Webhook

Po uložení hlasu centrála pošle `POST` na `callback_url` každého odběru pro dané patro (nebo `floor: null`):

- hlavičky `X-Event-Id`, `X-Event-Type: vote.created`, `X-Signature: sha256=<hex>`
- podpis = HMAC-SHA256 nad surovými bajty těla, klíč = `secret` z odběru jako text
  (ruční kontrola: `openssl dgst -sha256 -hmac "<secret>" telo.json`)
- doručeno = `2xx` do 3 s, jinak opakování po 1, 2 a 4 s se stejným tělem i podpisem
- terminál ověří podpis před parsováním (jinak `401`) a duplicitní `id` potvrdí `200` bez započítání

Terminál při startu nejdřív přihlásí odběr, pak stáhne snapshot `GET /api/v1/stats?floor=N` a dál přičítá jen události s `data.seq` větším než `last_vote_seq` ze snapshotu.
