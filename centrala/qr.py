"""QR kódy stánků. QR kód je jen URL dotazníku: {PUBLIC_URL}/s/{stand_id}."""

import io
from html import escape

import segno
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from config import PUBLIC_URL, stand_url
from data import STANDS, STANDS_BY_ID
from models import Error

router = APIRouter(tags=["qr"])

NOT_FOUND = {404: {"model": Error, "description": "Stánek neexistuje"}}


def _qr_for(stand_id: str) -> segno.QRCode:
    if stand_id not in STANDS_BY_ID:
        raise HTTPException(status_code=404, detail=f"Stánek {stand_id} neexistuje")
    return segno.make(stand_url(stand_id), error="m")


@router.get(
    "/qr/{stand_id}.svg",
    summary="QR kód stánku (SVG)",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}, "description": "QR kód s adresou dotazníku"}, **NOT_FOUND},
)
def qr_svg(stand_id: str, scale: int = Query(10, ge=1, le=50, description="Velikost jednoho modulu v px")):
    buf = io.BytesIO()
    _qr_for(stand_id).save(buf, kind="svg", scale=scale, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@router.get(
    "/qr/{stand_id}.png",
    summary="QR kód stánku (PNG)",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "QR kód s adresou dotazníku"}, **NOT_FOUND},
)
def qr_png(stand_id: str, scale: int = Query(10, ge=1, le=50, description="Velikost jednoho modulu v px")):
    buf = io.BytesIO()
    _qr_for(stand_id).save(buf, kind="png", scale=scale, border=2)
    return Response(buf.getvalue(), media_type="image/png")


@router.get(
    "/qr",
    summary="Všechny QR kódy k tisku",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}, "description": "HTML stránka s QR kódy všech stánků"}},
)
def qr_print_page(floor: int | None = Query(None, ge=0, description="Jen stánky na tomto patře")):
    stands = [s for s in STANDS if floor is None or s.floor == floor]
    cards = []
    for s in stands:
        url = stand_url(s.id)
        svg = segno.make(url, error="m").svg_inline(scale=6, border=2)
        cards.append(
            f"""<figure class="card">
  {svg}
  <figcaption>
    <div class="id">{escape(s.id)}</div>
    <div class="room">Patro {s.floor} · učebna {escape(s.room)}</div>
    <div class="title">{escape(s.title)}</div>
    <div class="url">{escape(url)}</div>
  </figcaption>
</figure>"""
        )
    return f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QR kódy stánků</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 16px; color: #111; background: #fff; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; gap: 16px; flex-wrap: wrap; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .hint {{ color: #555; font-size: .9rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; margin-top: 16px; }}
  .card {{ margin: 0; padding: 12px; border: 1px dashed #999; border-radius: 8px; text-align: center; break-inside: avoid; }}
  .card svg {{ width: 100%; max-width: 200px; height: auto; }}
  .id {{ font-size: 1.6rem; font-weight: 700; letter-spacing: .05em; }}
  .room {{ color: #444; }}
  .title {{ font-weight: 600; margin-top: 4px; }}
  .url {{ font-family: monospace; font-size: .7rem; color: #777; margin-top: 6px; word-break: break-all; }}
  button {{ font: inherit; padding: 6px 14px; cursor: pointer; }}
  @media print {{
    body {{ margin: 0; }}
    header {{ display: none; }}
    .grid {{ grid-template-columns: repeat(3, 1fr); gap: 8mm; }}
  }}
</style>
</head>
<body>
<header>
  <div>
    <h1>QR kódy stánků ({len(stands)})</h1>
    <div class="hint">Kódy vedou na <code>{escape(PUBLIC_URL)}</code>. Adresu změníte v <code>.env</code> (PUBLIC_URL).</div>
  </div>
  <button onclick="window.print()">Tisknout</button>
</header>
<main class="grid">
{"".join(cards)}
</main>
</body>
</html>"""
