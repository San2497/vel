"""Dotazník pro žáky (cíl QR kódu) a příjem hlasů."""

from html import escape

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse

import db
import webhooks
from data import STANDS_BY_ID
from models import Error, Vote, VoteIn

router = APIRouter()


@router.post(
    "/api/v1/stands/{stand_id}/votes",
    tags=["votes"],
    summary="Odeslat hlas pro stánek",
    status_code=201,
    response_model=Vote,
    responses={
        201: {"description": "Hlas uložen"},
        404: {"model": Error, "description": "Stánek neexistuje"},
        409: {"model": Error, "description": "Tento žák už pro stánek hlasoval"},
        422: {"description": "Neplatné tělo – odpověď říká, které pole a proč"},
    },
)
def create_vote(stand_id: str, vote: VoteIn, background: BackgroundTasks) -> Vote:
    """Uloží hlas žáka. Každý žák může pro jeden stánek hlasovat jen jednou
    (jméno se porovnává bez ohledu na velká/malá písmena a diakritiku).

    Po odeslání odpovědi centrála rozešle událost `vote.created` terminálům, které odebírají patro stánku
    (viz *Webhooks* dole a `POST /api/v1/subscriptions`). Nedostupný terminál uložení hlasu neovlivní."""
    stand = STANDS_BY_ID.get(stand_id)
    if stand is None:
        raise HTTPException(status_code=404, detail=f"Stánek {stand_id} neexistuje")
    try:
        saved, seq = db.add_vote(stand_id, vote.username, vote.rating, vote.favorite)
    except db.AlreadyVoted:
        raise HTTPException(
            status_code=409, detail=f"Uživatel {vote.username} už pro stánek {stand_id} hlasoval"
        ) from None
    background.add_task(webhooks.dispatch_vote, saved, stand, seq)  # poběží až po odeslání odpovědi
    return saved


@router.get(
    "/s/{stand_id}",
    tags=["survey"],
    summary="Dotazník stánku (cíl QR kódu)",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}, "description": "HTML stránka s formulářem"}, 404: {"description": "Stánek neexistuje"}},
)
def survey_page(stand_id: str):
    """Mobilní stránka s informacemi o projektu a formulářem. Formulář posílá JSON na `POST /api/v1/stands/{stand_id}/votes`."""
    stand = STANDS_BY_ID.get(stand_id)
    if stand is None:
        return HTMLResponse(
            f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<h1>Stánek {escape(stand_id)} neexistuje</h1>",
            status_code=404,
        )
    return _PAGE.format(
        id=escape(stand.id),
        title=escape(stand.title),
        authors=escape(", ".join(stand.authors)),
        class_name=escape(stand.class_name),
        room=escape(stand.room),
        floor=stand.floor,
    )


_PAGE = """<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{id} – hodnocení</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --text:#16181d; --muted:#5b6170; --line:#dde0e6; --accent:#2557d6; --accent-text:#fff;
           --ok:#1d7a3e; --ok-bg:#e6f4ea; --warn:#8a5a00; --warn-bg:#fff4dc; --err:#b42318; --err-bg:#fdecea; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#111317; --card:#1b1e24; --text:#eceef2; --muted:#9aa1b0; --line:#2c313a; --accent:#6d93ff; --accent-text:#0b1020;
             --ok:#7bd99a; --ok-bg:#16301f; --warn:#f2c46b; --warn-bg:#33280f; --err:#ff8a80; --err-bg:#3a1714; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width:480px; margin:0 auto; padding:16px; }}
  .meta {{ color:var(--muted); font-size:.9rem; }}
  h1 {{ font-size:1.45rem; line-height:1.25; margin:.25rem 0 .35rem; }}
  .authors {{ margin:0 0 16px; }}
  form {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; display:grid; gap:18px; }}
  label.field {{ display:grid; gap:6px; font-weight:600; }}
  input[type=text] {{ font:inherit; padding:12px; border:1px solid var(--line); border-radius:10px; background:var(--bg); color:var(--text); }}
  input[type=text]:focus {{ outline:2px solid var(--accent); outline-offset:1px; }}
  .hint {{ font-weight:400; color:var(--muted); font-size:.85rem; }}
  fieldset {{ border:0; padding:0; margin:0; }}
  legend {{ font-weight:600; margin-bottom:8px; padding:0; }}
  .stars {{ display:grid; grid-template-columns:repeat(5, 1fr); gap:8px; }}
  .stars input {{ position:absolute; opacity:0; pointer-events:none; }}
  .stars label {{ display:grid; place-items:center; min-height:52px; border:1px solid var(--line); border-radius:10px;
                  font-size:1.25rem; font-weight:700; cursor:pointer; user-select:none; background:var(--bg); }}
  .stars input:checked + label {{ background:var(--accent); color:var(--accent-text); border-color:var(--accent); }}
  .stars input:focus-visible + label {{ outline:2px solid var(--accent); outline-offset:2px; }}
  .scale {{ display:flex; justify-content:space-between; color:var(--muted); font-size:.8rem; margin-top:4px; }}
  .fav {{ display:flex; align-items:center; gap:10px; font-weight:600; cursor:pointer; min-height:44px; }}
  .fav input {{ width:22px; height:22px; accent-color:var(--accent); }}
  button {{ font:inherit; font-weight:700; padding:14px; border:0; border-radius:10px; background:var(--accent); color:var(--accent-text); cursor:pointer; }}
  button:disabled {{ opacity:.6; cursor:wait; }}
  #result {{ margin-top:16px; padding:14px; border-radius:12px; display:none; }}
  #result.show {{ display:block; }}
  #result.ok {{ background:var(--ok-bg); color:var(--ok); }}
  #result.warn {{ background:var(--warn-bg); color:var(--warn); }}
  #result.err {{ background:var(--err-bg); color:var(--err); }}
  #result ul {{ margin:.4rem 0 0; padding-left:1.2rem; }}
</style>
</head>
<body>
<main>
  <div class="meta">Stánek {id} · patro {floor} · učebna {room}</div>
  <h1>{title}</h1>
  <p class="authors">{authors} <span class="meta">({class_name})</span></p>

  <form id="vote" data-stand="{id}" novalidate>
    <label class="field">Uživatelské jméno
      <input type="text" name="username" required minlength="3" maxlength="32" autocomplete="username"
             autocapitalize="none" spellcheck="false" placeholder="novak.jan">
      <span class="hint">3–32 znaků: písmena, číslice, tečka, podtržítko, pomlčka</span>
    </label>

    <fieldset>
      <legend>Hodnocení</legend>
      <div class="stars">
        <input type="radio" name="rating" id="r1" value="1"><label for="r1">1</label>
        <input type="radio" name="rating" id="r2" value="2"><label for="r2">2</label>
        <input type="radio" name="rating" id="r3" value="3"><label for="r3">3</label>
        <input type="radio" name="rating" id="r4" value="4"><label for="r4">4</label>
        <input type="radio" name="rating" id="r5" value="5"><label for="r5">5</label>
      </div>
      <div class="scale"><span>nejhorší</span><span>nejlepší</span></div>
    </fieldset>

    <label class="fav"><input type="checkbox" name="favorite"> Tohle je můj favorit</label>

    <button type="submit">Odeslat hodnocení</button>
  </form>

  <div id="result" role="status" aria-live="polite"></div>
</main>
<script>
const form = document.getElementById("vote");
const result = document.getElementById("result");
const nameInput = form.elements.username;
const FIELD = {{ username: "Jméno", rating: "Hodnocení", favorite: "Favorit" }};
const MSG = {{
  missing: "chybí",
  string_too_short: "aspoň 3 znaky",
  string_too_long: "nejvýš 32 znaků",
  string_pattern_mismatch: "jen písmena, číslice, tečka, podtržítko a pomlčka",
  int_type: "vyber 1 až 5",
  greater_than_equal: "vyber 1 až 5",
  less_than_equal: "vyber 1 až 5",
  bool_type: "musí být ano/ne",
}};

try {{ nameInput.value = localStorage.getItem("veletrh.username") || ""; }} catch (e) {{}}

function show(kind, html) {{
  result.className = "show " + kind;
  result.innerHTML = html;
  result.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
}}
function esc(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }})[c]);
}}

form.addEventListener("submit", async (ev) => {{
  ev.preventDefault();
  const checked = form.querySelector("input[name=rating]:checked");
  const body = {{
    username: nameInput.value.trim(),
    rating: checked ? Number(checked.value) : null,
    favorite: form.elements.favorite.checked,
  }};
  const button = form.querySelector("button");
  button.disabled = true;
  try {{
    const res = await fetch("/api/v1/stands/" + encodeURIComponent(form.dataset.stand) + "/votes", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(body),
    }});
    const data = await res.json().catch(() => ({{}}));
    if (res.status === 201) {{
      try {{ localStorage.setItem("veletrh.username", body.username); }} catch (e) {{}}
      show("ok", "<strong>Děkujeme, hlas je uložen.</strong><br>Hodnocení " + data.rating + "/5" + (data.favorite ? " · favorit ★" : ""));
      form.querySelectorAll("input, button").forEach(el => el.disabled = true);
      return;
    }} else if (res.status === 409) {{
      show("warn", "<strong>Už jsi hlasoval.</strong><br>Uživatel " + esc(body.username) + " už tento stánek hodnotil.");
    }} else if (res.status === 422 && Array.isArray(data.detail)) {{
      const items = data.detail.map(d => {{
        const field = d.loc[d.loc.length - 1];
        return "<li>" + esc(FIELD[field] || field) + ": " + esc(MSG[d.type] || d.msg) + "</li>";
      }}).join("");
      show("err", "<strong>Formulář není vyplněný správně.</strong><ul>" + items + "</ul>");
    }} else {{
      show("err", "<strong>Chyba " + res.status + ".</strong> " + esc(data.detail || ""));
    }}
  }} catch (e) {{
    show("err", "<strong>Nepodařilo se spojit s centrálou.</strong> Zkus to znovu.");
  }}
  button.disabled = false;
}});
</script>
</body>
</html>"""
