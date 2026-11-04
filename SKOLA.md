# Nastavení ve škole – krok za krokem

Kód se nemění. Ve škole se mění jen adresy v souborech `.env`, pak se vytisknou QR kódy a ověří, že všechno komunikuje.

Pravidla školní sítě ([spsejecna.cz/pc](https://www.spsejecna.cz/pc)):

- povolené porty jsou jen **8080–8090** a 65525–65535,
- počítače jsou v síti `10.2.0.0/16`, tedy adresy `10.2.x.x`.

Příklady níže počítají s tím, že **centrála** běží na PC `10.2.5.17` a **terminál** na PC `10.2.5.23`. Vaše adresy budou jiné.

---

## 1. Stažení projektu

Na každém PC, kde poběží server:

```bash
git clone https://github.com/San2497/vel.git
cd vel
```

Běží-li vše na vlastním notebooku, kde projekt už je, tento krok i krok 2 přeskočte.

## 2. Instalace (Python 3.10 nebo novější)

Verzi ověříte příkazem `python --version`. Pak v obou složkách `centrala` i `terminal`:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Instalace potřebuje internet. **Když škola blokuje stahování balíčků**, připravte si je doma na flashku (stejná verze Pythonu jako ve škole, 64bit Windows), v každé složce:

```bash
# doma
.venv/Scripts/python -m pip download -r requirements.txt -d wheels
# ve škole
.venv/Scripts/python -m pip install --no-index --find-links wheels -r requirements.txt
```

Složku `.venv` mezi počítači nekopírujte – nebude fungovat, vždy ji vytvořte znovu.

## 3. Zjistit IP adresu

Na každém PC se serverem:

```bash
ipconfig
```

Hledejte řádek `IPv4 Address`, který začíná `10.2.` – třeba `10.2.5.17`.

## 4. Nastavit centrálu – `centrala/.env`

Soubor vytvořte kopií `centrala/.env.example` a upravte:

```
PUBLIC_URL=http://10.2.5.17:8080
```

`PUBLIC_URL` je adresa, kterou otevře **telefon** po naskenování QR kódu. Proto tu nesmí být `localhost` ani `127.0.0.1`.

## 5. Nastavit terminál – `terminal/.env`

Soubor vytvořte kopií `terminal/.env.example` a upravte:

```
CENTRAL_URL=http://10.2.5.17:8080
MY_URL=http://10.2.5.23:8081
FLOOR=2
MAX_SEEN_EVENTS=10000
DEBUG=0
```

| Proměnná | Co tam patří |
|---|---|
| `CENTRAL_URL` | IP a port PC, kde běží **centrála** |
| `MY_URL` | IP a port **tohoto** PC, na kterém běží terminál. Na tuhle adresu bude centrála posílat hlasy. |
| `FLOOR` | Patro, které má obrazovka ukazovat |
| `DEBUG` | Na veletrhu vždy `0` |

Varianty:

- **Centrála i terminál na stejném PC:** může zůstat `CENTRAL_URL=http://127.0.0.1:8080` a `MY_URL=http://127.0.0.1:8081`. (Na Windows `127.0.0.1`, ne `localhost` – ten je o ~2 s pomalejší.)
- **Terminál připojený k centrále jiné dvojice:** `MY_URL` musí být vaše skutečná adresa `10.2.x.x`, jinak se k vám centrála nedostane.
- **Dva terminály na jednom PC:** každý potřebuje vlastní port (`8081`, `8082`, …) a odpovídající `MY_URL`.
- **Přestěhování terminálu na jiné patro:** zastavit, změnit `FLOOR`, spustit. Sám se přihlásí k novému patru a načte jeho hlasy.

## 6. Začít s čistými daty

Před veletrhem smažte `centrala/veletrh.db` (pokud existuje). Odstraní se testovací hlasy i staré odběry terminálů. Centrála si při startu vytvoří prázdnou databázi.

## 7. Spustit servery

Nejdřív centrálu, potom terminály (terminál by na centrálu stejně počkal a zkoušel to znovu):

```bash
cd centrala
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

```bash
cd terminal
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8081
```

- `--host 0.0.0.0` je nutné – bez něj se na server nedostane nikdo jiný než vlastní PC.
- Port musí sedět s tím, co je v `.env` (`PUBLIC_URL`, `MY_URL`).
- Když se Windows zeptá, jestli povolit Pythonu přístup k síti, **povolte**.
- Vypínejte klávesami **Ctrl+C** – terminál se tím u centrály odhlásí.

## 8. Vytisknout QR kódy

Otevřete `http://10.2.5.17:8080/qr` a dejte **Tisknout**. Pod každým kódem je vidět adresa – musí začínat vaším `PUBLIC_URL`. Kódy vytištěné doma (s jinou adresou) ve škole fungovat nebudou.

Jen jedno patro: `http://10.2.5.17:8080/qr?floor=2`.

## 9. Ověřit, že všechno funguje

1. **Dokumentace:** `http://10.2.5.17:8080/docs` a `http://10.2.5.23:8081/docs` se otevřou.
2. **Terminál je přihlášený:** `http://10.2.5.17:8080/api/v1/subscriptions` – v seznamu je váš terminál se správným `callback_url` (`http://10.2.5.23:8081/webhooks/votes`) a patrem.
3. **Obrazovka:** `http://10.2.5.23:8081/` – dole svítí zelená tečka „Přihlášeno k odběru“ a jsou vidět stánky patra.
4. **Telefon:** naskenujte QR kód, odhlasujte – hlas se na obrazovce objeví do vteřiny.

## 10. Když něco nefunguje

| Problém | Pravděpodobná příčina a řešení |
|---|---|
| Telefon po naskenování stránku neotevře | Telefon není v síti, ze které vidí `10.2.x.x` (školní Wi-Fi může být oddělená od sítě učeben) – zeptejte se IT (podpora@spsejecna.cz). Jinak zkontrolujte `PUBLIC_URL`, `--host 0.0.0.0` a firewall. |
| QR kód vede na špatnou adresu | Po změně `PUBLIC_URL` restartovat centrálu a vytisknout kódy znovu. |
| Obrazovka: „Nepřihlášeno k centrále“ | Špatně `CENTRAL_URL`, nebo centrála neběží / blokuje ji firewall na PC centrály. |
| Obrazovka: „Načítám stav z centrály…“ dlouho | Terminál se přihlásil, ale nemůže stáhnout `GET /api/v1/stats` – zkontrolujte `CENTRAL_URL`. |
| Hlas se uloží, ale na obrazovce se neobjeví | Centrála se nedostane na `MY_URL` terminálu: špatná adresa nebo firewall na PC terminálu. V logu centrály uvidíte `Webhook … nedoručeno`. V `/api/v1/subscriptions` roste `failed_deliveries`. |
| V logu centrály se opakují chyby na starou adresu | Zůstal starý odběr (např. terminál spadl nebo změnil IP). Smažte ho v `/docs` přes `DELETE /api/v1/subscriptions/{id}`, nebo začněte s čistou databází (krok 6) a restartujte terminály. |
| `Address already in use` při spuštění | Na portu už něco běží – zavřete starý server, nebo použijte jiný port z rozsahu 8080–8090 (a upravte `.env`). |
| Česká písmena v logu vypadají rozbitě | Jen kódování konzole Windows, na funkci to nemá vliv. |
