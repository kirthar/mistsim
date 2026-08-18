"""Explorador de cartas y combos: filtro por metal/coste/etiqueta/efecto + sinergias."""
from __future__ import annotations

from typing import Any

from mistsim.agents.synergy import explain
from mistsim.agents.tags import tags_for
from mistsim.content.loader import Content
from mistsim.domain.cards import Ability, Card, CardType
from mistsim.report.web import theme
from mistsim.report.web.images import ImageRef
from mistsim.report.web.jsonutil import embed_json

PAGE_TITLE = "mistsim - explorador de cartas"

#: Proporcion (ancho/alto) de respaldo cuando no se conoce el tamano real del PNG.
#: Las cartas de Accion son verticales y las de Aliado apaisadas: usar una sola
#: proporcion para todas es justo lo que recortaba a los Aliados por el lado derecho.
_FALLBACK_ASPECT = {CardType.ACTION.value: (300, 422), CardType.ALLY.value: (300, 215)}


def _ability_dict(ability: Ability | None) -> dict[str, Any] | None:
    if ability is None:
        return None
    return {
        "metal": str(ability.metal) if ability.metal is not None else None,
        "effects": dict(ability.effects),
        "extra_burns": ability.extra_burns,
    }


def _card_to_dict(card: Card, market: tuple[Card, ...],
                  images: dict[str, ImageRef | None]) -> dict[str, Any]:
    others = [c for c in market if c.name != card.name]
    synergies = [
        {"rule": name, "value": round(value, 2), "why": why}
        for name, value, why in explain(card, others)
    ]
    ref = images.get(card.name)
    fallback_w, fallback_h = _FALLBACK_ASPECT.get(card.type.value, (300, 422))
    return {
        "name": card.name,
        "type": card.type.value,
        "cost": card.cost,
        "copies": card.copies,
        "number": card.card_number,
        "defense": card.defense,
        "metals": [str(m) for m in card.metal_pair],
        "tags": sorted(t.value for t in tags_for(card)),
        "primary": _ability_dict(card.primary),
        "secondary": _ability_dict(card.secondary),
        "savant": dict(card.savant) if card.savant else None,
        "off_turn": dict(card.off_turn) if card.off_turn else None,
        "ongoing": card.ongoing,
        "image": ref.path if ref else None,
        # Ancho/alto reales del PNG cuando se conocen; si no, una proporcion por
        # tipo de carta -- nunca la misma proporcion vertical para todas.
        "image_w": (ref.width if ref and ref.width else fallback_w),
        "image_h": (ref.height if ref and ref.height else fallback_h),
        "synergies": synergies,
    }


def build_cards_data(content: Content,
                     images: dict[str, ImageRef | None]) -> list[dict[str, Any]]:
    market = tuple(sorted(content.market, key=lambda c: (c.cost, c.name)))
    return [_card_to_dict(c, market, images) for c in market]


def render_cards_page(content: Content, images: dict[str, ImageRef | None],
                      combos: list[dict[str, Any]] | None = None,
                      *, player_page_href: str = "partida.html") -> str:
    cards = build_cards_data(content, images)
    cards_json = embed_json(cards)
    combos_json = embed_json(combos or [])
    has_combos = bool(combos)

    return f"""<meta charset="utf-8">
<title>{PAGE_TITLE}</title>
<meta name="description" content="Explorador de las 65 cartas de Mercado de Mistborn:
  The Deckbuilding Game, con filtros y desglose de sinergias.">
<style>
{theme.BASE_CSS}
{_PAGE_CSS}
</style>
<script type="application/json" id="cards-data">{cards_json}</script>
<script type="application/json" id="combos-data">{combos_json}</script>
<header class="page">
  <h1>Explorador de cartas</h1>
  <nav><a href="{player_page_href}">Reproductor de partida</a></nav>
  <span class="pill">{len(cards)} cartas de Mercado</span>
</header>
<main>
  <section class="filters card-box">
    <div class="filter-row">
      <label>Buscar<br>
        <input type="text" id="f-search" placeholder="nombre o efecto..."></label>
      <label>Coste maximo<br>
        <input type="number" id="f-cost" min="0" max="10" placeholder="cualquiera"></label>
      <label>Tipo<br>
        <select id="f-type">
          <option value="">cualquiera</option>
          <option value="Action">Accion</option>
          <option value="Ally">Aliado</option>
        </select>
      </label>
    </div>
    <div class="filter-row">
      <div id="f-metals" class="chip-group" aria-label="filtro por metal"></div>
    </div>
    <div class="filter-row">
      <div id="f-tags" class="chip-group" aria-label="filtro por etiqueta"></div>
    </div>
    <div class="filter-row">
      <span id="f-count" class="pill"></span>
      <button id="f-reset">limpiar filtros</button>
    </div>
  </section>

  <section class="explorer">
    <div id="grid" class="grid" role="list"></div>
    <aside id="detail" class="card-box detail-panel">
      <p class="muted">Elige una carta del Mercado para ver su ficha completa y sus sinergias.</p>
    </aside>
  </section>

  <section id="combos-section" class="card-box combos-panel">
    <h2>Combos por mineria estadistica</h2>
    <div id="combos-body"></div>
  </section>
</main>
<footer class="page">
  Las 65 cartas de Mercado estan verificadas contra sus imagenes
  (ver <span class="mono">data/verify/DIFF.md</span> en el repositorio).
  Generado por <span class="mono">mistsim report</span>.
</footer>
<script>
const CARDS = JSON.parse(document.getElementById('cards-data').textContent);
const COMBOS = JSON.parse(document.getElementById('combos-data').textContent);
const HAS_COMBOS = {str(has_combos).lower()};
{_PAGE_JS}
</script>
"""


_PAGE_CSS = """
.filters{margin:1rem 0; padding:1rem}
.filter-row{display:flex; flex-wrap:wrap; gap:1rem; align-items:flex-end; margin-bottom:.6rem}
.filter-row label{font-size:.82rem; color:var(--ink-dim)}
.filter-row input, .filter-row select{display:block; margin-top:.2rem; width:11rem}
.chip-group{display:flex; flex-wrap:wrap; gap:.4rem}
.chip{
  border:1px solid var(--border); border-radius:999px; padding:.15rem .65rem;
  font-size:.8rem; cursor:pointer; user-select:none; background:var(--bg);
}
.chip[data-active="1"]{
  background:var(--accent); color:var(--accent-ink); border-color:var(--accent);
}
.explorer{display:grid; grid-template-columns:1fr; gap:1rem}
@media(min-width:900px){.explorer{grid-template-columns:1fr 22rem}}
.grid{
  display:grid; gap:.75rem;
  grid-template-columns:repeat(auto-fill, minmax(9.5rem, 1fr));
}
.tile{
  cursor:pointer; overflow:hidden; display:flex; flex-direction:column;
  transition:border-color .1s;
}
.tile:hover, .tile:focus{border-color:var(--accent); outline:none}
.tile[aria-selected="true"]{border-color:var(--accent); box-shadow:0 0 0 2px var(--accent)}
/* La proporcion real (vertical para Accion, apaisada para Aliado) llega por
   estilo en linea desde image_w/image_h; object-fit:contain para que ninguna
   carta se recorte aunque el dato de proporcion sea el de respaldo. */
.tile img{width:100%; object-fit:contain; display:block; background:var(--bg)}
.tile .ph{
  width:100%; display:flex; align-items:center; justify-content:center;
  text-align:center; font-size:.8rem; padding:.5rem; color:var(--ink-dim); background:var(--bg);
}
.tile .meta{padding:.4rem .5rem; font-size:.8rem}
.tile .meta b{display:block; font-size:.82rem; margin-bottom:.15rem}
.detail-panel{
  padding:1rem; align-self:start; position:sticky; top:.75rem; max-height:90vh; overflow:auto;
}
.detail-panel h2{margin:.2rem 0 .1rem; font-size:1.05rem}
.detail-panel .sub{color:var(--ink-dim); font-size:.85rem; margin-bottom:.6rem}
.detail-panel img{max-width:100%; border-radius:6px; margin-bottom:.6rem}
.ability-block{
  border:1px solid var(--border); border-radius:6px; padding:.5rem .6rem; margin:.5rem 0;
  font-size:.85rem;
}
.ability-block .label{
  font-size:.72rem; text-transform:uppercase; letter-spacing:.03em; color:var(--ink-dim);
}
.eff-list{margin:.3rem 0 0; padding-left:1.1rem}
.syn-row{border-bottom:1px solid var(--border); padding:.4rem 0}
.syn-row:last-child{border-bottom:none}
.syn-row .val{color:var(--ok); font-weight:600}
.combos-panel{padding:1rem; margin-top:1.5rem}
.combo-row{
  display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; padding:.5rem 0;
  border-bottom:1px solid var(--border);
}
.combo-row:last-child{border-bottom:none}
.combo-cards{display:flex; flex-wrap:wrap; gap:.3rem}
.muted{color:var(--ink-dim)}
"""

_PAGE_JS = r"""
const state = { search: "", cost: null, type: "", metals: new Set(), tags: new Set() };

function allMetals() {
  const s = new Set();
  CARDS.forEach(c => c.metals.forEach(m => s.add(m)));
  return [...s].sort();
}
function allTags() {
  const s = new Set();
  CARDS.forEach(c => c.tags.forEach(t => s.add(t)));
  return [...s].sort();
}

function buildChips(container, values, activeSet) {
  container.innerHTML = "";
  values.forEach(v => {
    const el = document.createElement("span");
    el.className = "chip";
    el.textContent = v;
    el.dataset.active = activeSet.has(v) ? "1" : "0";
    el.addEventListener("click", () => {
      if (activeSet.has(v)) activeSet.delete(v); else activeSet.add(v);
      el.dataset.active = activeSet.has(v) ? "1" : "0";
      render();
    });
    container.appendChild(el);
  });
}

function matches(card) {
  if (state.search) {
    const q = state.search.toLowerCase();
    const inEffects = a => Object.keys(a ? a.effects : {}).some(k => k.toLowerCase().includes(q));
    const hay = card.name.toLowerCase().includes(q) ||
      inEffects(card.primary) || inEffects(card.secondary) ||
      card.tags.some(t => t.toLowerCase().includes(q));
    if (!hay) return false;
  }
  if (state.cost !== null && !isNaN(state.cost) && card.cost > state.cost) return false;
  if (state.type && card.type !== state.type) return false;
  if (state.metals.size && !card.metals.some(m => state.metals.has(m))) return false;
  if (state.tags.size && !card.tags.some(t => state.tags.has(t))) return false;
  return true;
}

function cardTile(card) {
  const el = document.createElement("div");
  el.className = "tile card-box";
  el.setAttribute("role", "listitem");
  el.tabIndex = 0;
  el.dataset.name = card.name;
  const ratio = `${card.image_w}/${card.image_h}`;
  const img = card.image
    ? `<img loading="lazy" alt="${card.name}" src="${card.image}" style="aspect-ratio:${ratio}">`
    : `<div class="ph" style="aspect-ratio:${ratio}">${card.name}</div>`;
  const metals = card.metals.join("/") || "-";
  el.innerHTML = `${img}<div class="meta"><b>${card.name}</b>${card.cost} pts &middot; `
    + `${metals}</div>`;
  el.addEventListener("click", () => selectCard(card.name));
  el.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") selectCard(card.name);
  });
  return el;
}

function effectList(effects) {
  const keys = Object.keys(effects || {});
  if (!keys.length) return "";
  return "<ul class='eff-list'>" + keys.map(k => {
    const v = effects[k];
    const shown = v === true ? "" : `: ${Array.isArray(v) ? v.join(", ") : v}`;
    return `<li><span class="mono">${k}</span>${shown}</li>`;
  }).join("") + "</ul>";
}

function cardsInCombosFor(name) {
  return COMBOS.filter(c => c.cards.includes(name));
}

function selectCard(name) {
  document.querySelectorAll(".tile").forEach(t => {
    t.setAttribute("aria-selected", t.dataset.name === name);
  });
  const card = CARDS.find(c => c.name === name);
  const panel = document.getElementById("detail");
  if (!card) { panel.innerHTML = "<p class='muted'>No se encontro la carta.</p>"; return; }

  const pill = t => `<span class="pill">${t}</span>`;
  let html = "";
  if (card.image) html += `<img alt="${card.name}" src="${card.image}">`;
  html += `<h2>${card.name}</h2>`;
  const kind = card.type === "Ally" ? "Aliado" : "Accion";
  html += `<div class="sub">${kind} &middot; coste ${card.cost}`
        + (card.defense !== null ? ` &middot; defensa ${card.defense}` : "")
        + (card.number ? ` &middot; ${card.number}/82` : "")
        + (card.copies > 1 ? ` &middot; ${card.copies} copias` : "") + "</div>";
  html += `<div>${card.metals.map(pill).join(" ")}</div>`;

  if (card.primary) {
    const label = "primaria" + (card.primary.metal ? " &middot; " + card.primary.metal : "");
    html += `<div class="ability-block"><span class="label">${label}</span>`
          + `${effectList(card.primary.effects)}</div>`;
  }
  if (card.secondary) {
    const secMetal = card.secondary.metal || "";
    const label = `secundaria &middot; +${card.secondary.extra_burns} ${secMetal}`;
    html += `<div class="ability-block"><span class="label">${label}</span>`
          + `${effectList(card.secondary.effects)}</div>`;
  }
  if (card.savant) {
    html += `<div class="ability-block"><span class="label">savant (de lado como metal)</span>`
          + `${effectList(card.savant)}</div>`;
  }
  if (card.off_turn) {
    html += `<div class="ability-block"><span class="label">fuera de turno</span>`
          + `${effectList(card.off_turn)}</div>`;
  }
  if (card.ongoing) {
    html += `<div class="ability-block"><span class="label">permanente</span>${card.ongoing}</div>`;
  }
  if (card.tags.length) {
    html += `<div style="margin:.5rem 0">${card.tags.map(pill).join(" ")}</div>`;
  }

  if (card.synergies.length) {
    html += "<h3>Sinergias (contra todo el Mercado)</h3>";
    card.synergies.forEach(s => {
      html += `<div class="syn-row"><span class="val">+${s.value.toFixed(1)}</span> ${s.rule}<br>`
            + `<span class="muted">${s.why}</span></div>`;
    });
  }

  if (HAS_COMBOS) {
    const inCombos = cardsInCombosFor(card.name);
    if (inCombos.length) {
      html += "<h3>Aparece en combos minados</h3>";
      inCombos.slice(0, 8).forEach(c => {
        const badge = c.score !== null
          ? ` <span class="val">(${c.score_field}=${c.score})</span>` : "";
        html += `<div class="syn-row">${c.cards.join(" + ")}` + badge + "</div>";
      });
    }
  }

  panel.innerHTML = html;
}

function render() {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  const filtered = CARDS.filter(matches);
  document.getElementById("f-count").textContent =
    filtered.length + " / " + CARDS.length + " cartas";
  filtered.forEach(c => grid.appendChild(cardTile(c)));
}

function renderCombos() {
  const body = document.getElementById("combos-body");
  if (!HAS_COMBOS) {
    body.innerHTML = "<p class='muted'>Todavia no hay un ranking de combos minado. " +
      "Se genera con <span class='mono'>mistsim report --combos ranking.json</span>; " +
      "esta seccion aparece sola cuando ese fichero exista.</p>";
    return;
  }
  let html = "<div class='scroll-x'>";
  COMBOS.slice(0, 60).forEach(c => {
    html += `<div class="combo-row"><div class="combo-cards">` +
      c.cards.map(n => `<span class="pill">${n}</span>`).join("") + `</div>` +
      (c.score !== null ? `<span class="val mono">${c.score_field} = ${c.score}</span>` : "") +
      (c.note ? `<span class="muted">${c.note}</span>` : "") + `</div>`;
  });
  html += "</div>";
  body.innerHTML = html;
}

buildChips(document.getElementById("f-metals"), allMetals(), state.metals);
buildChips(document.getElementById("f-tags"), allTags(), state.tags);
document.getElementById("f-search").addEventListener("input", e => {
  state.search = e.target.value; render();
});
document.getElementById("f-cost").addEventListener("input", e => {
  state.cost = e.target.value === "" ? null : Number(e.target.value);
  render();
});
document.getElementById("f-type").addEventListener("change", e => {
  state.type = e.target.value; render();
});
document.getElementById("f-reset").addEventListener("click", () => {
  state.search = ""; state.cost = null; state.type = "";
  state.metals.clear(); state.tags.clear();
  document.getElementById("f-search").value = "";
  document.getElementById("f-cost").value = "";
  document.getElementById("f-type").value = "";
  buildChips(document.getElementById("f-metals"), allMetals(), state.metals);
  buildChips(document.getElementById("f-tags"), allTags(), state.tags);
  render();
});

render();
renderCombos();
"""
