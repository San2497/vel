"""HTML stránka pro obrazovku na patře. Ptá se vlastního /stats (ne centrály) a sama se obnovuje."""

PAGE = """<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patro {{FLOOR}} – hodnocení</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262a33; --text:#eef0f4; --muted:#8d94a3;
          --accent:#6d93ff; --bar:#2a3550; --gold:#f2c46b; --ok:#4cc38a; --err:#ff6b5e; --flash:#24365e; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f4f5f8; --panel:#fff; --line:#e1e4ea; --text:#15171c; --muted:#5d6475;
            --accent:#2557d6; --bar:#dfe7fb; --gold:#b07a00; --ok:#1d7a3e; --err:#b42318; --flash:#dbe6ff; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:clamp(15px, 1.6vw, 26px)/1.35 system-ui, "Segoe UI", sans-serif; }
  main { padding:clamp(16px, 3vw, 48px); max-width:1600px; margin:0 auto; }
  header { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap; margin-bottom:1.2em; }
  h1 { margin:0; font-size:2.1em; line-height:1.1; }
  .sub { color:var(--muted); }
  .total { text-align:right; }
  .total b { display:block; font-size:2.4em; line-height:1; font-variant-numeric:tabular-nums; }
  table { width:100%; border-collapse:collapse; background:var(--panel); border-radius:14px; overflow:hidden; }
  th, td { padding:.6em .8em; text-align:left; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; font-size:.8em; text-transform:uppercase; letter-spacing:.05em; }
  tr:last-child td { border-bottom:0; }
  td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
  .rank { color:var(--muted); width:2.5em; }
  .id { color:var(--muted); font-size:.8em; display:block; }
  .title { font-weight:600; }
  .avg { width:30%; }
  .avgwrap { display:flex; align-items:center; gap:.6em; }
  .bar { flex:1; height:.55em; background:var(--bar); border-radius:99px; overflow:hidden; }
  .bar i { display:block; height:100%; background:var(--accent); border-radius:99px; transition:width .5s; }
  .avgval { font-weight:700; min-width:2.6em; text-align:right; font-variant-numeric:tabular-nums; }
  .fav { color:var(--gold); }
  tr.flash td { animation:flash 1.6s ease-out; }
  @keyframes flash { from { background:var(--flash); } to { background:transparent; } }
  .empty { padding:2em; text-align:center; color:var(--muted); }
  footer { margin-top:1em; color:var(--muted); font-size:.75em; display:flex; align-items:center; gap:.5em; }
  .dot { width:.7em; height:.7em; border-radius:50%; background:var(--muted); }
  .dot.ok { background:var(--ok); } .dot.err { background:var(--err); }
  @media (max-width:640px) { .avg { width:auto; } .bar { display:none; } th.fav, td.fav { display:none; } }
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Patro {{FLOOR}}</h1>
      <div class="sub">Hodnocení projektů · naskenuj QR kód u stánku</div>
    </div>
    <div class="total"><b id="total">–</b><span class="sub">hlasů</span></div>
  </header>
  <table>
    <thead><tr><th class="rank">#</th><th>Projekt</th><th class="num">Hlasy</th><th class="avg">Průměr</th><th class="num fav">Favorit</th></tr></thead>
    <tbody id="rows"><tr><td colspan="5" class="empty">Načítám…</td></tr></tbody>
  </table>
  <footer><span class="dot" id="dot"></span><span id="status">Připojuji…</span></footer>
</main>
<script>
const rows = document.getElementById("rows");
const prev = new Map();  // stand_id -> "votes|favorites" pro zvýraznění změn
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]);

function render(data) {
  document.getElementById("total").textContent = data.total_votes;
  if (!data.stands.length) {
    rows.innerHTML = '<tr><td colspan="5" class="empty">Zatím žádné hlasy. Naskenuj QR kód u stánku a hlasuj.</td></tr>';
    return;
  }
  rows.innerHTML = data.stands.map((s, i) => {
    const key = s.votes + "|" + s.favorites;
    const changed = prev.has(s.stand_id) && prev.get(s.stand_id) !== key;
    prev.set(s.stand_id, key);
    return `<tr class="${changed ? "flash" : ""}">
      <td class="rank">${i + 1}</td>
      <td><span class="id">${esc(s.stand_id)}</span><span class="title">${esc(s.title)}</span></td>
      <td class="num">${s.votes}</td>
      <td class="avg"><div class="avgwrap"><div class="bar"><i style="width:${(s.avg_rating / 5) * 100}%"></i></div>
        <span class="avgval">${s.votes ? s.avg_rating.toFixed(2) : "–"}</span></div></td>
      <td class="num fav">${s.favorites ? "★ " + s.favorites : "–"}</td>
    </tr>`;
  }).join("");
}

function status(ok, text) {
  document.getElementById("dot").className = "dot " + (ok ? "ok" : "err");
  document.getElementById("status").textContent = text;
}

async function tick() {
  try {
    const [st, hl] = await Promise.all([fetch("/stats"), fetch("/health")]);
    const health = await hl.json();
    if (st.ok) render(await st.json());
    if (!health.subscription_id) status(false, "Nepřihlášeno k centrále – zkouším se připojit…");
    else if (!health.snapshot_loaded) status(false, "Načítám stav z centrály…");
    else status(true, "Přihlášeno k odběru" + (health.last_event_at ? " · poslední hlas " + new Date(health.last_event_at).toLocaleTimeString("cs-CZ") : ""));
  } catch (e) {
    status(false, "Terminál neodpovídá");
  }
}
tick();
setInterval(tick, 1000);
</script>
</body>
</html>"""
