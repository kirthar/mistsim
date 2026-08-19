"""Reproductor de partida: línea de tiempo turno a turno sobre el log de eventos."""
from __future__ import annotations

from typing import Any

from mistsim.content.loader import Content
from mistsim.domain.metals import BASE_METALS, KEYWORDS
from mistsim.domain.missions import TRACK_LENGTH
from mistsim.engine.game import GameResult
from mistsim.io import serial
from mistsim.report.web import theme
from mistsim.report.web.jsonutil import embed_json
from mistsim.report.web.replay import build_timeline

PAGE_TITLE = "mistsim - reproductor de partida"

_HOMEBREW_NOTICE = (
    "<b>Aviso de datos:</b> las 8 cartas de Misión y el mazo del Lord Ruler son "
    "<i>homebrew</i> (sólo se conocen los nombres, ver README del proyecto). Las "
    "posiciones en las pistas de Misión y cualquier partida en modo Cooperativo que "
    "veas aquí dependen de esa reconstrucción, no de datos verificados del juego real."
)


def build_game_payload(result: GameResult, index: int) -> dict[str, Any]:
    summary = serial.result_to_dict(result, include_log=False)
    summary["index"] = index
    return {"summary": summary, "timeline": build_timeline(result)}


def render_empty_player_page(*, reason: str, cards_page_href: str = "cartas.html") -> str:
    """Página válida cuando no hay ninguna partida que mostrar (corpus vacío o ausente)."""
    return f"""<meta charset="utf-8">
<title>{PAGE_TITLE}</title>
<style>{theme.BASE_CSS}</style>
<header class="page">
  <h1>Reproductor de partida</h1>
  <nav><a href="{cards_page_href}">Explorador de cartas</a></nav>
</header>
<main>
  <p class="card-box" style="padding:1rem">{reason}</p>
  <p>Genera un corpus con log completo y vuelve a correr
    <span class="mono">mistsim report</span>:</p>
  <pre class="card-box mono" style="padding:1rem; overflow-x:auto">
mistsim batch -n 20 -p 2 --save corpus.jsonl
mistsim report --corpus corpus.jsonl --out informe/</pre>
</main>
"""


def render_player_page(results: list[GameResult], content: Content,
                       *, cards_page_href: str = "cartas.html",
                       truncated: bool = False) -> str:
    if not results:
        return render_empty_player_page(
            reason="El corpus no traía ninguna partida que mostrar.",
            cards_page_href=cards_page_href)

    games = [build_game_payload(r, i) for i, r in enumerate(results)]
    games_json = embed_json(games)
    characters_json = embed_json([
        {"id": c.id, "name": c.name, "title": c.title, "signature_metal": c.signature_metal}
        for c in content.characters
    ])
    metal_keywords_json = embed_json({str(m): KEYWORDS[m] for m in BASE_METALS})
    base_metals_json = embed_json([str(m) for m in BASE_METALS])

    missions_ok = content.provenance.get("missions")
    lord_ruler_ok = content.provenance.get("lord_ruler")
    show_homebrew = not (missions_ok and lord_ruler_ok)
    notice_html = f'<div class="notice">{_HOMEBREW_NOTICE}</div>' if show_homebrew else ""
    truncated_html = (
        f'<div class="notice">Se muestran las primeras {len(results)} partidas del '
        "corpus; hay más, recortadas para mantener la página en un tamaño razonable "
        "(usa <span class='mono'>--max-games</span> para cambiarlo).</div>"
        if truncated else ""
    )

    return f"""<meta charset="utf-8">
<title>{PAGE_TITLE}</title>
<meta name="description" content="Reproductor turno a turno de partidas de Mistborn:
  The Deckbuilding Game simuladas por mistsim.">
<style>
{theme.BASE_CSS}
{_PAGE_CSS}
</style>
<script type="application/json" id="games-data">{games_json}</script>
<script type="application/json" id="characters-data">{characters_json}</script>
<script type="application/json" id="metal-keywords-data">{metal_keywords_json}</script>
<script type="application/json" id="base-metals-data">{base_metals_json}</script>
<header class="page">
  <h1>Reproductor de partida</h1>
  <nav><a href="{cards_page_href}">Explorador de cartas</a></nav>
  <label>Partida
    <select id="game-select"></select>
  </label>
</header>
{notice_html}
{truncated_html}
<main>
  <section id="result-summary" class="card-box"
    style="padding:.75rem 1rem; margin-bottom:1rem"></section>

  <section class="transport card-box">
    <button id="btn-first" title="al principio">|&laquo;</button>
    <button id="btn-prev" title="paso anterior">&laquo;</button>
    <button id="btn-play" class="primary" title="reproducir">&#9654; reproducir</button>
    <button id="btn-next" title="paso siguiente">&raquo;</button>
    <button id="btn-last" title="al final">&raquo;|</button>
    <input type="range" id="scrub" min="0" max="0" value="0" style="flex:1">
    <select id="speed">
      <option value="1200">1x</option>
      <option value="600">2x</option>
      <option value="250">4x</option>
    </select>
    <span id="step-label" class="pill mono"></span>
  </section>

  <section class="layout">
    <div class="card-box log-panel">
      <div class="log-header">
        <h2 style="margin:0; font-size:1rem">Eventos</h2>
        <label class="small">
          <input type="checkbox" id="show-noisy"> mostrar eventos tecnicos
        </label>
      </div>
      <ol id="event-list"></ol>
    </div>
    <div id="players-panel" class="players-panel"></div>
  </section>

  <section class="card-box" style="padding:1rem; margin-top:1rem">
    <p class="muted" style="margin:0">
      El log no registra el contenido exacto de la mano en cada turno (solo cuantas
      cartas se roban) ni la fila del Mercado carta a carta en cada instante: se
      muestra lo que el log sí garantiza -metales, pistas de Mision, salud y qué se
      compra o juega, en orden.
    </p>
  </section>
</main>
<footer class="page">Generado por <span class="mono">mistsim report</span>.</footer>
<script>
const GAMES = JSON.parse(document.getElementById('games-data').textContent);
const CHARACTERS = JSON.parse(document.getElementById('characters-data').textContent);
const METAL_KEYWORDS = JSON.parse(document.getElementById('metal-keywords-data').textContent);
const BASE_METALS = JSON.parse(document.getElementById('base-metals-data').textContent);
const TRACK_LENGTH = {TRACK_LENGTH};
{_PAGE_JS}
</script>
"""


_PAGE_CSS = """
header.page select{margin-left:.4rem}
.transport{
  display:flex; flex-wrap:wrap; gap:.5rem; align-items:center; padding:.6rem .8rem;
  margin-bottom:1rem; position:sticky; top:0; z-index:5;
}
.layout{display:grid; grid-template-columns:1fr; gap:1rem}
@media(min-width:1000px){
  .layout{grid-template-columns:minmax(0,1.1fr) minmax(0,1.4fr)}
}
.log-panel{padding:.8rem; max-height:70vh; overflow:auto}
.log-header{
  display:flex; justify-content:space-between; align-items:center;
  margin-bottom:.4rem; gap:.5rem; flex-wrap:wrap;
}
.log-header .small{font-size:.8rem; color:var(--ink-dim)}
#event-list{list-style:none; margin:0; padding:0; font-size:.88rem}
#event-list li{padding:.25rem .3rem; border-bottom:1px dashed var(--border)}
#event-list li.noisy{color:var(--ink-dim); font-size:.82rem}
#event-list li b{color:var(--accent)}
.players-panel{
  display:grid; gap:.8rem; grid-template-columns:repeat(auto-fit, minmax(15rem,1fr));
  align-content:start;
}
.player-card{padding:.7rem .8rem}
.player-card h3{margin:0 0 .3rem; font-size:.95rem}
.player-card .role{font-size:.78rem; color:var(--ink-dim); margin-bottom:.5rem}
.bar-row{display:flex; align-items:center; gap:.5rem; margin:.35rem 0; font-size:.8rem}
.bar-track{
  flex:1; height:.55rem; border-radius:999px; background:var(--bg);
  border:1px solid var(--border); overflow:hidden;
}
.bar-fill{height:100%; background:var(--ok)}
.bar-fill.tr{background:var(--accent)}
.metals-row{display:flex; flex-wrap:wrap; gap:.3rem; margin:.4rem 0}
.metal-chip{
  font-size:.72rem; padding:.08rem .4rem; border-radius:4px; border:1px solid var(--border);
  color:var(--ink); cursor:default;
}
.metal-chip.ready{color:var(--metal-ready); border-color:var(--metal-ready)}
.metal-chip.burned{background:var(--metal-burned); color:#fff; border-color:var(--metal-burned)}
.metal-chip.flared{background:var(--metal-flared); color:#fff; border-color:var(--metal-flared)}
.tracks{margin-top:.5rem}
.track-row{font-size:.76rem; margin:.3rem 0}
.track-row .name{color:var(--ink-dim)}
.purchases{font-size:.78rem; margin-top:.5rem; max-height:6rem; overflow:auto}
.purchases .pill{margin:.1rem .15rem 0 0}
"""

_PAGE_JS = r"""
let gameIndex = 0;
let stepIndex = 0;
let playing = null;

function charLabel(id) {
  const c = CHARACTERS.find(x => x.id === id);
  return c ? c.name : id;
}

function currentGame() { return GAMES[gameIndex]; }

function populateGameSelect() {
  const sel = document.getElementById("game-select");
  sel.innerHTML = "";
  GAMES.forEach((g, i) => {
    const rawChars = g.timeline.blocks[0].events[0].data.characters || [];
    const chars = rawChars.map(charLabel).join(" vs ");
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `#${i} - ${chars} (${g.summary.turns}t, ${g.summary.reason})`;
    sel.appendChild(opt);
  });
  sel.addEventListener("change", e => {
    gameIndex = Number(e.target.value); stepIndex = 0; onGameChange();
  });
}

function renderSummary() {
  const g = currentGame();
  const s = g.summary;
  const winner = s.winner === null
    ? "sin ganador"
    : `P${s.winner} (${charLabel(s.players[s.winner].character)})`;
  const box = document.getElementById("result-summary");
  box.innerHTML =
    `<b>Resultado:</b> ${winner} &middot; motivo <span class="mono">${s.reason}</span>` +
    ` &middot; ${s.turns} turnos &middot; salud final ` +
    Object.entries(s.final_health).map(([p, h]) => `P${p}=${h}`).join(", ");
}

function onGameChange() {
  document.getElementById("game-select").value = gameIndex;
  const blocks = currentGame().timeline.blocks;
  const scrub = document.getElementById("scrub");
  scrub.max = blocks.length - 1;
  scrub.value = stepIndex;
  renderSummary();
  renderStep();
}

function stepLabel(block) {
  if (block.owner === null && block.turn === 0) return "Arranque de la partida";
  return `Turno ${block.turn} - P${block.owner}`;
}

function renderEvents(block) {
  const showNoisy = document.getElementById("show-noisy").checked;
  const list = document.getElementById("event-list");
  list.innerHTML = "";
  block.events.forEach(ev => {
    if (ev.noisy && !showNoisy) return;
    const li = document.createElement("li");
    if (ev.noisy) li.className = "noisy";
    const who = ev.player !== null ? `<b>P${ev.player}</b> ` : "";
    li.innerHTML = who + ev.desc;
    list.appendChild(li);
  });
  if (!list.children.length) {
    list.innerHTML = "<li class='noisy'>(sin eventos visibles en este paso)</li>";
  }
}

function metalBoard(snap) {
  return `<div class="metals-row">` + BASE_METALS.map(m => {
    const st = snap.metals[m] || "ready";
    return `<span class="metal-chip ${st}" title="${METAL_KEYWORDS[m]}">${m}</span>`;
  }).join("") + `</div>`;
}

function tracksBlock(snap, trackNames) {
  if (!trackNames.length) return "";
  return `<div class="tracks">` + trackNames.map(t => {
    const pos = snap.tracks[t] || 0;
    const pct = Math.min(100, (pos / TRACK_LENGTH) * 100);
    return `<div class="track-row"><span class="name">${t}</span>: ${pos}/${TRACK_LENGTH}
      <div class="bar-track"><div class="bar-fill tr" style="width:${pct}%"></div></div></div>`;
  }).join("") + `</div>`;
}

function renderPlayers(block) {
  const g = currentGame();
  const trackNames = g.timeline.tracks;
  const panel = document.getElementById("players-panel");
  panel.innerHTML = "";
  g.summary.players.forEach(pr => {
    const snap = block.snapshot[pr.player_id] || block.snapshot[String(pr.player_id)];
    const health = snap && snap.health !== null ? snap.health : "-";
    const healthPct = typeof health === "number"
      ? Math.max(0, Math.min(100, (health / 40) * 100)) : 0;
    const training = snap ? snap.training : 0;
    const trainingPct = (training / 8) * 100;
    const purchases = snap ? snap.purchases : [];
    const purchasesHtml = purchases.length
      ? "compras: " + purchases.map(c => `<span class="pill">${c}</span>`).join("")
      : "sin compras todavia";
    const div = document.createElement("div");
    div.className = "player-card card-box";
    div.innerHTML = `
      <h3>P${pr.player_id} - ${charLabel(pr.character)}</h3>
      <div class="role">${pr.strategy}${pr.won ? " &middot; <b>gana</b>" : ""}</div>
      <div class="bar-row">salud ${health}/40
        <div class="bar-track"><div class="bar-fill" style="width:${healthPct}%"></div></div>
      </div>
      <div class="bar-row">entrenamiento ${training}/8
        <div class="bar-track"><div class="bar-fill tr" style="width:${trainingPct}%"></div></div>
      </div>
      ${snap ? metalBoard(snap) : ""}
      ${snap ? tracksBlock(snap, trackNames) : ""}
      <div class="purchases">${purchasesHtml}</div>
    `;
    panel.appendChild(div);
  });
}

function renderStep() {
  const blocks = currentGame().timeline.blocks;
  stepIndex = Math.max(0, Math.min(blocks.length - 1, stepIndex));
  const block = blocks[stepIndex];
  document.getElementById("scrub").value = stepIndex;
  const total = blocks.length;
  document.getElementById("step-label").textContent =
    `${stepIndex + 1}/${total} - ${stepLabel(block)}`;
  renderEvents(block);
  renderPlayers(block);
  document.getElementById("btn-prev").disabled = stepIndex === 0;
  document.getElementById("btn-first").disabled = stepIndex === 0;
  document.getElementById("btn-next").disabled = stepIndex === blocks.length - 1;
  document.getElementById("btn-last").disabled = stepIndex === blocks.length - 1;
}

function stop() {
  if (!playing) return;
  clearInterval(playing);
  playing = null;
  document.getElementById("btn-play").innerHTML = "&#9654; reproducir";
}
function play() {
  const blocks = currentGame().timeline.blocks;
  if (stepIndex >= blocks.length - 1) stepIndex = 0;
  document.getElementById("btn-play").innerHTML = "&#10074;&#10074; pausa";
  playing = setInterval(() => {
    stepIndex++;
    if (stepIndex >= blocks.length) { stop(); return; }
    renderStep();
  }, Number(document.getElementById("speed").value));
}

document.getElementById("btn-first").addEventListener("click", () => {
  stop(); stepIndex = 0; renderStep();
});
document.getElementById("btn-last").addEventListener("click", () => {
  stop(); stepIndex = currentGame().timeline.blocks.length - 1; renderStep();
});
document.getElementById("btn-prev").addEventListener("click", () => {
  stop(); stepIndex--; renderStep();
});
document.getElementById("btn-next").addEventListener("click", () => {
  stop(); stepIndex++; renderStep();
});
document.getElementById("btn-play").addEventListener("click", () => { playing ? stop() : play(); });
document.getElementById("scrub").addEventListener("input", e => {
  stop(); stepIndex = Number(e.target.value); renderStep();
});
document.getElementById("show-noisy").addEventListener("change", () => {
  renderEvents(currentGame().timeline.blocks[stepIndex]);
});

populateGameSelect();
onGameChange();
"""
