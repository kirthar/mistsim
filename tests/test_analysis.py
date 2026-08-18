"""Tests de la minería de combos.

La pregunta que responden no es "¿corre el código?" sino "¿mide lo que dice medir?".
Por eso casi todos parten de un **corpus sintético con sinergia conocida**: se fabrica
una población en la que la respuesta correcta está escrita a mano y se comprueba que el
estimador la recupera, y sobre todo que NO recupera sinergia donde sólo hay dinero.

La lección de la Fase A —tres fallos del motor destapados por un test de copia— se
aplica aquí igual: el corpus sintético es la implementación de referencia contra la que
se contrasta el estimador.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from mistsim.agents import archetypes
from mistsim.analysis import corpus as corpus_mod
from mistsim.analysis import mining, report, rules, stats
from mistsim.analysis.corpus import CorpusSpec, Observation
from mistsim.analysis.stats import Cell

# --- utilidades para fabricar corpus sintéticos ------------------------------


def obs(cards, won, *, strategy="equilibrado", players=3, mode="pvp") -> Observation:
    return Observation(strategy=strategy, players=players, mode=mode,
                       cards=frozenset(cards), won=won)


def population(cards, wins: int, losses: int, **kwargs) -> list[Observation]:
    """`wins` ganadores y `losses` perdedores con exactamente ese mazo."""
    return ([obs(cards, True, **kwargs)] * wins) + ([obs(cards, False, **kwargs)] * losses)


def cell_block(n: int, rate: float) -> Cell:
    return Cell(n=n, wins=round(n * rate))


def synthetic(rng: random.Random, n: int, *, p_a: float, p_b: float, base: float,
              effect_a: float, effect_b: float, interaction: float,
              filler: int = 0, strategy: str = "equilibrado") -> list[Observation]:
    """Corpus con una estructura causal escrita a mano.

    P(ganar) = base · effect_a^[A] · effect_b^[B] · interaction^[A∧B]

    `interaction=1` significa *literalmente* "sin sinergia": A y B se multiplican y ya.
    Ese es el caso que un estimador honesto tiene que devolver como lift ≈ 1 aunque A y
    B aparezcan juntas todo el rato.
    """
    rows = []
    for _ in range(n):
        has_a = rng.random() < p_a
        has_b = rng.random() < p_b
        p = base * (effect_a if has_a else 1) * (effect_b if has_b else 1)
        if has_a and has_b:
            p *= interaction
        cards = {"A"} if has_a else set()
        if has_b:
            cards.add("B")
        # Relleno para que los mazos no sean sólo A y B: sin él todos los pares del
        # corpus son el mismo par y la estratificación no tiene nada que hacer.
        for i in range(filler):
            if rng.random() < 0.4:
                cards.add(f"F{i}")
        rows.append(obs(cards, rng.random() < min(p, 0.99), strategy=strategy))
    return rows


# --- estadística básica ------------------------------------------------------


def test_wilson_cubre_la_proporcion_y_no_se_sale_del_intervalo():
    low, high = stats.wilson_interval(5, 10)
    assert low < 0.5 < high
    # En los extremos Wilson no se sale de [0, 1], que es donde Wald sí lo hace.
    assert stats.wilson_interval(0, 5)[0] == 0.0
    assert stats.wilson_interval(5, 5)[1] == 1.0
    # Más datos, intervalo más estrecho.
    low_10, high_10 = stats.wilson_interval(5, 10)
    low_1000, high_1000 = stats.wilson_interval(500, 1000)
    assert (high_1000 - low_1000) < (high_10 - low_10)


def test_interaccion_es_simetrica_al_intercambiar_las_cartas():
    both, only_a, only_b, neither = (Cell(40, 30), Cell(60, 24), Cell(50, 15), Cell(200, 40))
    psi_ab, var_ab = stats.interaction(both, only_a, only_b, neither)
    psi_ba, var_ba = stats.interaction(both, only_b, only_a, neither)
    assert psi_ab == pytest.approx(psi_ba)
    assert var_ab == pytest.approx(var_ba)


def test_interaccion_es_cero_cuando_los_efectos_solo_se_multiplican():
    """Tabla construida a mano: p11 = p10·p01/p00 exactamente."""
    p00, ra, rb = 0.20, 2.0, 1.5
    strata = [(cell_block(400, p00 * ra * rb), cell_block(400, p00 * ra),
               cell_block(400, p00 * rb), cell_block(400, p00))]
    estimate = stats.estimate_from_strata(strata)
    assert estimate.lift == pytest.approx(1.0, abs=0.05)
    assert estimate.ci_low < 1.0 < estimate.ci_high


def test_interaccion_recupera_un_lift_conocido():
    p00, ra, rb, inter = 0.15, 1.6, 1.4, 2.0
    strata = [(cell_block(600, p00 * ra * rb * inter), cell_block(600, p00 * ra),
               cell_block(600, p00 * rb), cell_block(600, p00))]
    estimate = stats.estimate_from_strata(strata)
    assert estimate.lift == pytest.approx(inter, rel=0.10)
    assert estimate.ci_low > 1.0


def test_pool_pondera_por_inverso_de_la_varianza():
    """El estrato con más datos manda; el ruidoso apenas mueve la aguja."""
    psi, var = stats.pool([(2.0, 0.01), (-2.0, 4.0)])
    assert psi > 1.9
    assert var < 0.01


def test_una_estimacion_sin_estratos_no_es_lift_uno():
    """"No se pudo medir" y "medido y da 1" son cosas distintas y el tipo lo refleja."""
    estimate = stats.estimate_from_strata([])
    assert not estimate.estimated
    assert math.isnan(estimate.lift)
    assert not estimate.significant
    assert not estimate.robust()


def test_spearman_detecta_orden_perfecto_y_ausencia_de_orden():
    assert stats.spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]) == pytest.approx(1.0)
    assert stats.spearman([1.0, 2.0, 3.0, 4.0], [40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


# --- el confusor: dinero, no sinergia ----------------------------------------


#: Relleno que hace que los mazos "ricos" sean estrictamente más grandes que los
#: "pobres". Sin esta separación limpia, el corte por cuantiles mezcla los dos grupos y
#: el control de tamaño no llega a controlar nada.
RICO = ["D1", "D2", "D3", "D4", "D5"]


def poblacion_con_confusor_de_dinero() -> list[Observation]:
    """Dos cartas caras SIN ninguna interacción, y un confusor que las junta.

    En el estrato pobre casi nadie tiene A ni B y se gana poco. En el rico todo el mundo
    tiene de todo y se gana mucho, pero dentro de él A y B se multiplican limpiamente:
    la respuesta correcta es lift 1.
    """
    rows: list[Observation] = []
    rows += population(["C"], 20, 180)
    rows += population(["A", "C"], 4, 26)
    rows += population(["B", "C"], 4, 26)
    rows += population(["A", "B", "C"], 1, 6)
    rows += population(["C", *RICO], 30, 70)
    rows += population(["A", "C", *RICO], 60, 60)
    rows += population(["B", "C", *RICO], 60, 60)
    rows += population(["A", "B", "C", *RICO], 96, 24)
    return rows


def test_el_lift_ingenuo_se_deja_enganar_por_el_dinero_y_el_estratificado_no():
    """El test central de todo el módulo.

    El estimador ingenuo canta sinergia donde sólo hay dinero; el estratificado dice
    que no hay nada, que es la verdad con la que se construyó la población.
    """
    index = mining.build_index(poblacion_con_confusor_de_dinero(), size_control=True,
                               size_buckets=2)
    pairs = {p.cards: p for p in mining.mine_pairs(index, min_support=20, min_cell=5)}
    ab = pairs[("A", "B")]

    assert ab.naive > 1.5, "el estimador ingenuo debería morder el anzuelo"
    assert ab.synergy.estimated and ab.synergy.strata_used == 2
    assert ab.synergy.lift == pytest.approx(1.0, abs=0.35)
    assert ab.synergy.ci_low < 1.0 < ab.synergy.ci_high


def test_la_estratificacion_cambia_el_resultado_cuando_debe():
    """Mismos datos, con y sin control de tamaño de mazo: el número tiene que moverse.

    Si no se moviera, el control no estaría controlando nada y toda la sección de
    estratificación del informe sería decorativa. Nótese la dirección: aquí el confusor
    sesga el contraste de interacción hacia ABAJO, no hacia arriba. Mezclar poblaciones
    con tasas base distintas deja las celdas "sólo A" y "sólo B" como mezclas de las dos
    y eso aplasta el contraste. Confundir no es sinónimo de inflar.
    """
    rows = poblacion_con_confusor_de_dinero()
    con = mining.build_index(rows, size_control=True, size_buckets=2)
    sin = mining.build_index(rows, size_control=False)
    assert con.size_edges and not sin.size_edges
    assert len(con.strata) > len(sin.strata)

    lift_con = {p.cards: p for p in mining.mine_pairs(con, min_support=20)}[("A", "B")]
    lift_sin = {p.cards: p for p in mining.mine_pairs(sin, min_support=20)}[("A", "B")]
    assert lift_sin.synergy.estimated and lift_con.synergy.estimated
    assert lift_sin.synergy.strata_used == 1

    # El estratificado acierta la verdad (1,0) y el no estratificado se aleja de ella.
    assert lift_con.synergy.lift == pytest.approx(1.0, abs=0.35)
    assert abs(math.log(lift_sin.synergy.lift)) > 2 * abs(math.log(lift_con.synergy.lift))
    assert abs(lift_sin.synergy.lift - lift_con.synergy.lift) > 0.2


def test_estratificar_por_arquetipo_separa_poblaciones_distintas():
    rows = (population(["A", "B"], 40, 10, strategy="aggro-combate")
            + population(["A"], 10, 40, strategy="aggro-combate")
            + population(["B"], 10, 40, strategy="aggro-combate")
            + population(["Z"], 20, 80, strategy="aggro-combate")
            + population(["A", "B"], 10, 40, strategy="rush-mision")
            + population(["A"], 40, 10, strategy="rush-mision")
            + population(["B"], 40, 10, strategy="rush-mision")
            + population(["Z"], 60, 40, strategy="rush-mision"))
    index = mining.build_index(rows, size_control=False)
    assert {key[0] for key in (s.key for s in index.strata)} == {"aggro-combate", "rush-mision"}
    ab = {p.cards: p for p in mining.mine_pairs(index, min_support=20)}[("A", "B")]
    # Los dos arquetipos empujan en sentidos opuestos y se cancelan al agregarlos.
    assert ab.synergy.estimated
    assert ab.synergy.strata_used == 2


# --- soporte mínimo ----------------------------------------------------------


def test_el_soporte_minimo_filtra_los_pares_anecdoticos():
    rows = population(["A", "B"], 3, 0) + population(["C", "D"], 40, 40) + population(["E"], 5, 5)
    index = mining.build_index(rows, size_control=False)
    con_filtro = {p.cards for p in mining.mine_pairs(index, min_support=30)}
    sin_filtro = {p.cards for p in mining.mine_pairs(index, min_support=1)}
    assert ("A", "B") not in con_filtro
    assert ("A", "B") in sin_filtro
    assert ("C", "D") in con_filtro


def test_min_cell_descarta_los_estratos_con_una_celda_vacia():
    """Un estrato en el que nadie tuvo las dos cartas no informa sobre la interacción."""
    completo = (cell_block(50, 0.5), cell_block(50, 0.3), cell_block(50, 0.3),
                cell_block(50, 0.2))
    cojo = (Cell(1, 1), cell_block(50, 0.3), cell_block(50, 0.3), cell_block(50, 0.2))
    solo_completo = stats.estimate_from_strata([completo], min_cell=5)
    con_cojo = stats.estimate_from_strata([completo, cojo], min_cell=5)
    assert con_cojo.strata_used == 1
    assert con_cojo.lift == pytest.approx(solo_completo.lift)
    # Bajando el umbral, el estrato cojo sí entra y mueve el número.
    permisivo = stats.estimate_from_strata([completo, cojo], min_cell=1)
    assert permisivo.strata_used == 2


def test_robusto_exige_soporte_significacion_e_intervalo_util():
    ancho = stats.Estimate(lift=40.0, ci_low=1.2, ci_high=900.0, log_lift=3.7,
                           variance=3.0, strata_used=4, support=200)
    assert ancho.significant
    assert not ancho.robust(), "un IC de 1,2 a 900 es ruido con signo"
    corto = stats.Estimate(lift=2.0, ci_low=1.5, ci_high=2.7, log_lift=0.7,
                           variance=0.02, strata_used=4, support=5)
    assert not corto.robust(min_support=30)
    bueno = stats.Estimate(lift=2.0, ci_low=1.5, ci_high=2.7, log_lift=0.7,
                           variance=0.02, strata_used=4, support=200)
    assert bueno.robust(min_support=30)


# --- corpus generado a partir del modelo causal ------------------------------


def test_corpus_sintetico_sin_interaccion_da_lift_uno():
    rng = random.Random(11)
    rows = synthetic(rng, 12000, p_a=0.5, p_b=0.5, base=0.15, effect_a=1.8,
                     effect_b=1.6, interaction=1.0, filler=4)
    index = mining.build_index(rows, size_control=False)
    ab = {p.cards: p for p in mining.mine_pairs(index, min_support=30)}[("A", "B")]
    assert ab.synergy.lift == pytest.approx(1.0, abs=0.20)
    assert not ab.synergy.significant


def test_corpus_sintetico_con_interaccion_conocida_la_recupera():
    rng = random.Random(12)
    rows = synthetic(rng, 12000, p_a=0.5, p_b=0.5, base=0.12, effect_a=1.3,
                     effect_b=1.2, interaction=2.2, filler=4)
    index = mining.build_index(rows, size_control=False)
    ab = {p.cards: p for p in mining.mine_pairs(index, min_support=30)}[("A", "B")]
    assert ab.synergy.ci_low < 2.2 < ab.synergy.ci_high
    assert ab.synergy.robust()
    # Y el par sinérgico manda en el ranking frente a los pares de relleno.
    ranking = mining.mine_pairs(index, min_support=30)
    assert ranking[0].cards == ("A", "B")


def test_una_antisinergia_sale_con_lift_por_debajo_de_uno():
    rng = random.Random(13)
    rows = synthetic(rng, 12000, p_a=0.5, p_b=0.5, base=0.30, effect_a=1.5,
                     effect_b=1.5, interaction=0.4, filler=3)
    index = mining.build_index(rows, size_control=False)
    ab = {p.cards: p for p in mining.mine_pairs(index, min_support=30)}[("A", "B")]
    assert ab.synergy.lift < 1.0
    assert ab.synergy.ci_high < 1.0


# --- tríos -------------------------------------------------------------------


def _trio_rows(rng: random.Random, n: int, *, boost_ab: float, boost_abc: float):
    rows = []
    for _ in range(n):
        cards = {c for c in "ABC" if rng.random() < 0.5}
        p = 0.15
        if {"A", "B"} <= cards:
            p *= boost_ab
        if {"A", "B", "C"} <= cards:
            p *= boost_abc
        for i in range(3):
            if rng.random() < 0.4:
                cards.add(f"F{i}")
        rows.append(obs(cards, rng.random() < min(p, 0.98)))
    return rows


def test_un_trio_que_solo_arrastra_un_buen_par_no_puntua_como_trio():
    """A+B sinergian de verdad; C es inerte. El trío no debe aparecer como hallazgo."""
    rng = random.Random(21)
    rows = _trio_rows(rng, 16000, boost_ab=2.5, boost_abc=1.0)
    index = mining.build_index(rows, size_control=False)
    pairs = mining.mine_pairs(index, min_support=30)
    assert {p.cards: p for p in pairs}[("A", "B")].synergy.lift > 1.7

    triples = {t.cards: t for t in mining.mine_triples(index, pairs, min_support=30)}
    abc = triples[("A", "B", "C")]
    assert abc.synergy.estimated
    assert abc.synergy.lift == pytest.approx(1.0, abs=0.35)
    assert not abc.synergy.robust(min_support=20)


def test_un_trio_con_sinergia_de_tercer_orden_si_puntua():
    rng = random.Random(22)
    rows = _trio_rows(rng, 16000, boost_ab=1.0, boost_abc=2.6)
    index = mining.build_index(rows, size_control=False)
    pairs = mining.mine_pairs(index, min_support=30)
    triples = {t.cards: t for t in mining.mine_triples(index, pairs, min_support=30)}
    abc = triples[("A", "B", "C")]
    assert abc.synergy.lift > 1.6
    assert abc.synergy.ci_low > 1.0


# --- plan de corpus y lectura ------------------------------------------------


def test_el_plan_cubre_todos_los_arquetipos_y_todos_los_tamanos_de_mesa():
    plan = corpus_mod.plan_batches(CorpusSpec(games=2000, games_per_batch=25))
    vistos = {name for batch, _ in plan for name in batch.strategies}
    assert vistos == set(archetypes.names())
    assert {batch.config.num_players for batch, _ in plan} == {2, 3, 4}
    assert sum(games for _, games in plan) == 2000
    # Ningún arquetipo puede quedarse en un solo asiento.
    asientos = {name: set() for name in archetypes.names()}
    for batch, _ in plan:
        for seat, name in enumerate(batch.strategies):
            asientos[name].add(seat)
    assert all(len(seats) > 1 for seats in asientos.values())


def test_el_plan_es_determinista_y_no_repite_semillas():
    spec = CorpusSpec(games=500, games_per_batch=25)
    uno = [(b.strategies, b.base_seed, n) for b, n in corpus_mod.plan_batches(spec)]
    dos = [(b.strategies, b.base_seed, n) for b, n in corpus_mod.plan_batches(spec)]
    assert uno == dos
    semillas = {b.base_seed for b, _ in corpus_mod.plan_batches(spec)}
    assert len(semillas) == len(uno)


def test_las_observaciones_se_limitan_a_las_cartas_de_mercado(tmp_path: Path):
    """`purchases` puede traer Entrenamientos y Financiaciones rescatados con Soar.

    Como todo el mundo empieza con ellos, como ítem de una regla de asociación no dicen
    nada, y colarlos inventaría pares con soporte enorme y lift 1.
    """
    linea = {
        "schema": 1, "winner": 0, "reason": "all-missions", "turns": 20,
        "final_health": {}, "mission_positions": {},
        "players": [
            {"player_id": 0, "strategy": "equilibrado", "character": "vin", "won": True,
             "rank": 1, "final_health": 20,
             "purchases": ["Rebel", "Rioter", "Funding", "Training (Iron)", "Rebel"],
             "damage_dealt": 0, "damage_taken": 0, "mission_points_spent": 0,
             "tracks_topped": 3, "cards_eliminated": 0, "training": 0},
            {"player_id": 1, "strategy": "aggro-combate", "character": "kelsier",
             "won": False, "rank": 2, "final_health": 10, "purchases": ["Strike"],
             "damage_dealt": 5, "damage_taken": 2, "mission_points_spent": 0,
             "tracks_topped": 0, "cards_eliminated": 0, "training": 0},
        ],
    }
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(linea, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = list(corpus_mod.read_observations(path))
    assert len(rows) == 2
    assert rows[0].cards == frozenset({"Rebel", "Rioter"}), "sin starters y sin duplicados"
    assert rows[0].won and rows[0].players == 2 and rows[0].mode == "pvp"
    assert rows[1].cards == frozenset({"Strike"})


def test_una_partida_coop_se_reconoce_por_tener_varios_ganadores(tmp_path: Path):
    linea = {
        "schema": 1, "winner": None, "reason": "lord-ruler-defeated", "turns": 20,
        "final_health": {}, "mission_positions": {},
        "players": [
            {"player_id": i, "strategy": "equilibrado", "character": "vin", "won": True,
             "rank": 1, "final_health": 20, "purchases": ["Rebel"], "damage_dealt": 0,
             "damage_taken": 0, "mission_points_spent": 0, "tracks_topped": 0,
             "cards_eliminated": 0, "training": 0}
            for i in range(2)
        ],
    }
    path = tmp_path / "coop.jsonl"
    path.write_text(json.dumps(linea, ensure_ascii=False) + "\n", encoding="utf-8")
    assert {o.mode for o in corpus_mod.read_observations(path)} == {"coop"}


# --- contraste con las reglas escritas a mano --------------------------------


def test_las_reglas_escritas_a_mano_disparan_en_los_pares_obvios(content):
    by_name = rules.cards_by_name(content)
    rebel_rioter = dict(rules.pair_rules(by_name["Rebel"], by_name["Rioter"]))
    assert "riot-necesita-aliados" in rebel_rioter
    # La regla se detecta en las dos direcciones, no sólo en la que la escribieron.
    assert dict(rules.pair_rules(by_name["Rioter"], by_name["Rebel"])) == rebel_rioter

    confrontation = dict(rules.pair_rules(by_name["Confrontation"], by_name["Preserve"]))
    assert "confrontation-quiere-atium" in confrontation
    assert rules.pair_rules(by_name["Strike"], by_name["Steelpush"]) == ()


def test_el_contraste_por_regla_cuenta_confirmados_y_contradichos(content):
    class FakePair:
        def __init__(self, cards, lift, low, high, support=100):
            self.cards = cards
            self.support = support
            self.rules = ()
            self.synergy = stats.Estimate(lift, low, high, math.log(lift), 0.01, 3, support)

    pairs = [
        FakePair(("Rebel", "Rioter"), 2.0, 1.4, 2.9),      # confirma
        FakePair(("Rebel", "Soother"), 0.5, 0.3, 0.8),     # contradice
        FakePair(("Strike", "Steelpush"), 3.0, 2.0, 4.5),  # ninguna regla lo cubre
    ]
    checks = {c.rule: c for c in rules.check_rules(pairs, content, min_support=10)}
    riot = checks["riot-necesita-aliados"]
    assert riot.measured == 2 and riot.confirmed == 1 and riot.contradicted == 1
    assert checks["confrontation-quiere-atium"].measured == 0

    rules.annotate(pairs, content)
    assert pairs[0].rules and not pairs[2].rules
    assert [p.cards for p in rules.undiscovered(pairs)] == [("Strike", "Steelpush")]


# --- integración de punta a punta --------------------------------------------


def test_corpus_real_pequeno_de_punta_a_punta(tmp_path: Path):
    """Juega partidas de verdad, las persiste y las mina. Lento pero corto.

    No comprueba ningún lift concreto —con 24 partidas no hay ninguno que creerse—,
    sino que las piezas encajan: `run_batch` → `write_corpus` → observaciones → índice
    → pares → informe, sin que ninguna se coma los datos por el camino.
    """
    path = tmp_path / "mini.jsonl"
    spec = CorpusSpec(games=24, players=(2, 3), games_per_batch=8, max_turns=30, seed=5)
    escritas = corpus_mod.generate(path, spec, workers=1)
    assert escritas == 24
    assert sum(1 for _ in path.open(encoding="utf-8")) == 24

    rows = list(corpus_mod.read_observations(path))
    assert len(rows) == 8 * 2 + 8 * 3 + 8 * 2  # el plan alterna 2/3 jugadores
    universo = corpus_mod.market_names()
    assert all(o.cards <= universo for o in rows)

    index = mining.build_index(rows, size_control=True, size_buckets=2)
    assert index.observations == len(rows)
    assert index.wins == sum(1 for o in rows if o.won)
    pairs = mining.mine_pairs(index, min_support=2, costs=corpus_mod.card_costs())
    rules.annotate(pairs)
    triples = mining.mine_triples(index, pairs, min_support=2)
    checks = rules.check_rules(pairs, min_support=2)
    texto = report.render(index, pairs, triples, checks, corpus_path=str(path),
                          size_control=True, top=5, min_support=2)
    assert "MINERÍA DE COMBOS" in texto
    assert "HOMEBREW" in texto
    assert "QUÉ ES ROBUSTO Y QUÉ NO" in texto


def test_el_corpus_generado_es_reproducible(tmp_path: Path):
    """Dos corridas del mismo CorpusSpec dan el mismo fichero, byte a byte.

    Sin esto ningún hallazgo se puede volver a comprobar, que es lo mismo que no tenerlo.
    """
    spec = CorpusSpec(games=12, players=(2,), games_per_batch=6, max_turns=25, seed=3)
    uno, dos = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    corpus_mod.generate(uno, spec, workers=1)
    corpus_mod.generate(dos, spec, workers=1)
    assert uno.read_text(encoding="utf-8") == dos.read_text(encoding="utf-8")


# --- multiplicidad y calibración ---------------------------------------------


def test_benjamini_hochberg_corrige_por_multiplicidad():
    """2 000 contrastes al 5% regalan 100 hallazgos aunque no exista ninguno."""
    rng = random.Random(99)
    # Ruido de verdad: ψ sacado del nulo, no una rampa determinista.
    ruido = [stats.Estimate(lift=1.0, ci_low=0.9, ci_high=1.1,
                            log_lift=rng.gauss(0.0, 0.1), variance=0.01,
                            strata_used=3, support=100)
             for _ in range(2000)]
    real = stats.Estimate(lift=3.0, ci_low=2.4, ci_high=3.8, log_lift=1.1,
                          variance=0.005, strata_used=8, support=500)
    todos = [*ruido, real]
    descubrimientos = stats.control_fdr(todos, alpha=0.05)
    assert real.q_value < 0.05
    assert descubrimientos <= 3, "la FDR tiene que aplastar el ruido"
    # Sin corregir, el 5% de 2 000 contrastes nulos pasa: ~100 falsos hallazgos.
    sin_corregir = sum(1 for e in ruido if e.p_value <= 0.05)
    assert 50 < sin_corregir < 160
    # Las q son monótonas respecto a las p, por construcción del procedimiento.
    ordenados = sorted((e for e in todos if math.isfinite(e.p_value)),
                       key=lambda e: e.p_value)
    assert all(a.q_value <= b.q_value + 1e-12
               for a, b in zip(ordenados, ordenados[1:], strict=False))


def test_una_estimacion_deja_de_ser_robusta_si_no_sobrevive_a_la_fdr():
    estimate = stats.Estimate(lift=1.6, ci_low=1.05, ci_high=2.4, log_lift=0.47,
                              variance=0.045, strata_used=5, support=200)
    assert estimate.robust(), "antes de corregir por multiplicidad pasaría"
    estimate.q_value = 0.4
    assert not estimate.robust()


def _poblacion_sin_ninguna_sinergia(n: int, seed: int = 1) -> list[Observation]:
    """Población en la que la victoria depende SÓLO de la riqueza, nunca de qué cartas.

    Ninguna pareja interactúa con ninguna otra: la respuesta correcta para los 91 pares
    es lift 1. La riqueza tiene cola larga y actúa de forma convexa, que es justo la
    forma del corpus real —mazos de 2 a 60 cartas—.
    """
    rng = random.Random(seed)
    cartas = [f"C{i}" for i in range(14)]
    out = []
    for _ in range(n):
        riqueza = rng.random() ** 3
        mazo = frozenset(c for c in cartas if rng.random() < 0.15 + 0.8 * riqueza)
        gana = rng.random() < 0.10 + 0.75 * riqueza ** 2
        out.append(Observation("equilibrado", 3, "pvp", mazo, gana))
    return out


def test_sin_control_de_tamano_el_dinero_inventa_sinergias_en_todo_el_ranking():
    """Regresión del sesgo que encontró la calibración sobre el corpus real.

    Con terciles de tamaño de mazo el tramo alto va de 8 a 60 cartas y dentro de él
    seguía mandando el tamaño: la mediana del lift de TODOS los pares salía en 1,15 y
    600 pares parecían sinérgicos. Aquí se reproduce en una población en la que, por
    construcción, no hay ni una sola sinergia.
    """
    data = _poblacion_sin_ninguna_sinergia(30000)

    def mediana(size_buckets: int) -> mining.Calibration:
        index = mining.build_index(data, size_control=size_buckets > 1,
                                   size_buckets=size_buckets)
        return mining.calibration(mining.mine_pairs(index, min_support=30, min_cell=5))

    sin_control = mediana(1)
    grueso = mediana(3)
    fino = mediana(mining.DEFAULT_SIZE_BUCKETS)

    assert sin_control.median_lift > 1.15, "sin control, sinergia donde no la hay"
    assert not sin_control.well_centred
    assert sin_control.discoveries > 20, "y encima 'significativas' tras la FDR"
    assert grueso.median_lift < sin_control.median_lift, "terciles ayudan, pero no bastan"
    assert fino.well_centred, "con tramos finos la mediana vuelve al 1 que corresponde"
    assert fino.significant_fraction < 0.12
    assert fino.discoveries <= 2


def test_la_calibracion_no_tapa_una_sinergia_de_verdad():
    """El control fino no puede ser tan agresivo que borre lo que sí existe."""
    rng = random.Random(31)
    rows = synthetic(rng, 20000, p_a=0.5, p_b=0.5, base=0.12, effect_a=1.3,
                     effect_b=1.2, interaction=2.2, filler=6)
    index = mining.build_index(rows, size_control=True,
                               size_buckets=mining.DEFAULT_SIZE_BUCKETS)
    pairs = mining.mine_pairs(index, min_support=30, min_cell=5)
    ab = {p.cards: p for p in pairs}[("A", "B")]
    assert ab.synergy.lift > 1.6
    assert ab.synergy.q_value < 0.05
    assert ab.synergy.robust()


def test_el_diagnostico_del_confusor_separa_los_dos_rankings():
    rows = poblacion_con_confusor_de_dinero()
    index = mining.build_index(rows, size_control=True, size_buckets=2)
    check = mining.cost_correlation(mining.mine_pairs(index, min_support=20))
    assert check.pairs > 0
    assert math.isnan(check.naive_vs_cost) or -1.0 <= check.naive_vs_cost <= 1.0
