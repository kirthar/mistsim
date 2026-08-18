"""El solver de turno óptimo.

Tres cosas hay que comprobar de un buscador que devuelve secuencias, y son
independientes entre sí:

1. Que lo que devuelve **es jugable**: se aplica de verdad sobre el estado y ninguna
   acción se cae. Un solver que puntúa alto una secuencia ilegal es peor que no tenerlo.
2. Que **no pierde el óptimo por el camino**: en un turno pequeño construido a mano, el
   haz con todas sus podas encuentra lo mismo que la búsqueda exhaustiva, y el
   branch-and-bound además lo demuestra.
3. Que respeta la **no conmutatividad de las conversiones**. Es el caso que rompe la
   poda por permutaciones: `House War` sólo convierte el combate acumulado HASTA ese
   instante, así que colapsar los órdenes daría planes que parecen mejores de lo que son.
"""
from __future__ import annotations

import pytest

from mistsim.agents import archetypes
from mistsim.agents.solver_agent import SolverAgent, objective_from_profile
from mistsim.domain.cards import CardInstance
from mistsim.domain.metals import Metal, TokenState
from mistsim.domain.state import GameConfig
from mistsim.engine import solver
from mistsim.engine import turn as turn_engine
from mistsim.engine.actions import Action, ActionKind, legal_actions
from mistsim.engine.choices import GreedyChooser
from mistsim.engine.events import EventLog
from mistsim.engine.game import GameEngine
from mistsim.engine.setup import new_game

# --- utilidades --------------------------------------------------------------


def card_named(content, name):
    """Busca una carta por nombre en el Mercado y, si no está, en los mazos iniciales."""
    try:
        return content.market_by_name(name)
    except KeyError:
        for char_id in ("vin", "kelsier"):
            for card in content.starting_deck(char_id):
                if card.name == name:
                    return card
        raise


def build_hand(game, content, names, uid_base=9000):
    """Sustituye la mano del jugador activo por cartas concretas."""
    player = game.players[game.active]
    player.hand.clear()
    instances = []
    for offset, name in enumerate(names):
        inst = CardInstance(uid=uid_base + offset, card=card_named(content, name))
        player.hand.append(inst)
        instances.append(inst)
    return instances


def controlled_turn(content, log, names, *, burn_limit=1, deck=()):
    """Un turno de laboratorio: mano conocida, mazo conocido y nada más en mesa."""
    import random

    state = new_game(content, GameConfig(num_players=2, max_turns=40),
                     ["vin", "kelsier"], random.Random(11), log)
    player = state.players[0]
    state.active = 0
    turn_engine.start_turn(state, player, log)
    player.in_play.clear()
    player.allies.clear()
    player.deck = [CardInstance(uid=8000 + i, card=card_named(content, n))
                   for i, n in enumerate(deck)]
    player.tokens.burn_limit = burn_limit
    build_hand(state, content, names)
    return state


def replay_counting(plan, state, chooser=None):
    """Aplica el plan sobre un clon y devuelve (aplicadas, total)."""
    work = state.clone()
    applied = plan.replay(work, EventLog(keep=frozenset()), chooser or GreedyChooser())
    return applied, len(plan.actions), work


#: Jugar la partida de la que salen los estados cuesta, y varios tests quieren los
#: mismos: se juega una vez y se reparten clones.
_SNAPSHOT_CACHE: dict[int, list] = {}

#: Configuración barata para los tests que comprueban legalidad, no optimalidad.
FAST = solver.SolverConfig(beam_width=8, exact_nodes=0)


def mid_game_states(content, count=6, seed=5):
    """Estados reales al principio de un turno, sacados de una partida jugada."""
    from mistsim.agents.utility import UtilityAgent

    if seed in _SNAPSHOT_CACHE:
        return [s.clone() for s in _SNAPSHOT_CACHE[seed][:count]]

    snapshots = []

    class Snapshot(UtilityAgent):
        def choose_action(self, state, actions):
            key = (state.turn, state.active)
            if key not in seen:
                seen.add(key)
                snapshots.append(state.clone())
            return super().choose_action(state, actions)

    seen: set[tuple[int, int]] = set()
    log = EventLog(keep=frozenset())
    engine = GameEngine(content=content, config=GameConfig(num_players=2, max_turns=25),
                        seed=seed, log=log)
    engine.run([Snapshot(archetypes.get("aggro-combate"), seed=1),
                Snapshot(archetypes.get("rush-mision"), seed=2)])
    _SNAPSHOT_CACHE[seed] = snapshots[2:]
    return [s.clone() for s in _SNAPSHOT_CACHE[seed][:count]]


# --- 1. lo que devuelve es jugable -------------------------------------------


@pytest.mark.parametrize("objective", ["damage", "mission", "coin"])
def test_el_plan_se_aplica_entero_sobre_el_estado_real(content, objective):
    """Cada acción del plan vuelve a ser legal al replicarla sobre el estado de verdad.

    No basta con que el solver crea que su secuencia vale mucho: las acciones apuntan a
    las `CardInstance` de un CLON, y si no se vuelven a atar por `uid` el motor marcaría
    las activaciones sobre las copias. Este test es el que destapó justo eso.
    """
    for state in mid_game_states(content):
        plan = solver.solve_turn(state, objective, config=FAST)
        applied, total, _ = replay_counting(plan, state)
        assert applied == total, f"plan cortado en la acción {applied + 1} de {total}"


def test_el_plan_nunca_repite_una_activacion_ya_gastada(content):
    """Una habilidad primaria se activa una vez; si el plan la repite, es que la búsqueda
    está mutando el estado padre en vez del hijo."""
    for state in mid_game_states(content, count=4):
        plan = solver.solve_turn(state, "damage", config=FAST)
        activations = [solver.action_id(a) for a in plan.actions
                       if a.kind in (ActionKind.ACTIVATE, ActionKind.ACTIVATE_ALLY)]
        assert len(activations) == len(set(activations))


def test_rebind_ata_la_accion_al_estado_que_se_va_a_mutar(content, log):
    state = controlled_turn(content, log, ["Ironpull", "Steelpush"])
    clone = state.clone()
    inst = clone.players[0].hand[0]

    action = Action(ActionKind.CARD_AS_METAL, card=inst, metal=Metal.IRON)
    real = solver.rebind(action, state)

    assert real is not None
    assert real.card is not inst and real.card.uid == inst.uid
    assert real.card in state.players[0].hand


# --- 2. no pierde el óptimo --------------------------------------------------


def test_el_beam_iguala_a_la_busqueda_exhaustiva_en_un_turno_pequeno(content, log):
    """Turno cerrado: el óptimo es comprobable de verdad.

    La comparación es contra `exhaustive_turn`, que recorre el MISMO conjunto de
    acciones candidatas sin haz, sin canonicalización y sin cota. Si alguna de las tres
    podas se comiera el óptimo, aquí se vería.

    Con presupuesto holgado a propósito: esta mano lleva `Enrage`, cuyo Riot mete más
    activaciones en juego y deja la cota sin garantía (ver `bound_is_admissible`), así
    que el corte por cota no ayuda y hay que pagar la anchura. Aun así cuesta un tercio
    de los nodos que la exhaustiva.
    """
    state = controlled_turn(content, log, ["Ironpull", "Steelpush", "Enrage"],
                            burn_limit=2)
    objective = solver.objective_for("damage")

    found = solver.search_turn(state, objective,
                               solver.SolverConfig(beam_width=12, max_depth=7,
                                                   exact_nodes=60_000))
    reference = solver.exhaustive_turn(state, objective, max_depth=7)

    assert found.score >= reference.score
    assert found.explored < reference.explored


def test_el_branch_and_bound_demuestra_el_optimo(content, log):
    """Con presupuesto suficiente y sin cartas entrando, el B&B no deja nada por mirar.

    `proven` no es cosmético: significa que la cota agotó el árbol, o sea que ninguna
    otra secuencia de acciones candidatas puede rendir más. Sólo puede afirmarse cuando
    la cota es admisible — nada que robe, busque en el Mercado o recupere cartas.
    """
    state = controlled_turn(content, log,
                            ["Ironpull", "Steelpush", "Training (Pewter)"], burn_limit=2)
    assert solver.bound_is_admissible(state)

    found = solver.search_turn(state, solver.objective_for("damage"),
                               solver.SolverConfig(max_depth=7, exact_nodes=60_000))
    reference = solver.exhaustive_turn(state, solver.objective_for("damage"), max_depth=7)

    assert found.proven
    assert round(found.score, 6) == round(reference.score, 6)


def test_las_podas_no_cambian_el_valor_encontrado(content, log):
    """Cada poda por separado debe dar el mismo óptimo que sin ella.

    Con presupuesto holgado. Con el presupuesto por defecto NO da lo mismo, y es un
    resultado en sí: sin canonicalización el buscador gasta sus nodos en permutaciones
    del mismo turno y se queda corto. La poda no sólo acelera; es lo que pone el óptimo
    al alcance del presupuesto.
    """
    state = controlled_turn(content, log, ["Ironpull", "Steelpush", "Enrage"],
                            burn_limit=2)
    objective = solver.objective_for("damage")
    scores = {
        (canonical, dedup): solver.search_turn(
            state, objective,
            solver.SolverConfig(beam_width=16, max_depth=7, exact_nodes=60_000,
                                canonical=canonical, dedup=dedup)).score
        for canonical in (True, False)
        for dedup in (True, False)
    }
    assert len(set(round(value, 6) for value in scores.values())) == 1, scores


def test_la_canonicalizacion_recorta_el_arbol(content):
    """Si la poda por permutaciones no recortara, no valdría la pena tenerla.

    Se mide sobre el haz solo (`exact_nodes=0`): con branch-and-bound detrás, los dos
    acaban gastando su presupuesto entero y el recorte no se ve en el contador.
    """
    state = mid_game_states(content, count=1)[0]
    objective = solver.objective_for("damage")
    con = solver.search_turn(state, objective,
                             solver.SolverConfig(exact_nodes=0, canonical=True))
    sin = solver.search_turn(state, objective,
                             solver.SolverConfig(exact_nodes=0, canonical=False))
    assert con.explored < sin.explored
    # Que el valor no se resienta lo comprueba `test_las_podas_no_cambian_el_valor_
    # encontrado` con presupuesto holgado: con un haz estrecho, cambiar qué nodos
    # entran mueve el resultado en ambos sentidos y comparar aquí sería medir ruido.


# --- 3. las conversiones no conmutan -----------------------------------------


def house_war_setup(content, log):
    """Mano capaz de encadenar House War: la primaria da combate y la secundaria lo
    convierte todo en Misión, pero sólo lo acumulado hasta ese momento."""
    return controlled_turn(
        content, log,
        ["House War", "Subdue", "Deceive", "Training (Zinc)"],
        burn_limit=1)


def test_el_motor_trata_la_conversion_como_no_conmutativa(content, log):
    """Documenta el ruling: convertir ANTES de acumular no captura nada.

    Es la premisa de la que depende toda la poda por permutaciones del solver, así que
    se comprueba contra el motor y no se da por supuesta.
    """
    player_res = []
    for convert_first in (True, False):
        state = controlled_turn(content, log, ["House War"], burn_limit=1)
        player = state.players[0]
        inst = player.hand[0]
        chooser = GreedyChooser()
        turn_engine.apply(state, Action(ActionKind.PLAY_CARD, card=inst), log, chooser)
        turn_engine.apply(state, Action(ActionKind.BURN, metal=Metal.ZINC), log, chooser)
        if convert_first:
            player.resources.combat = 0
            inst.primary_activated = True
            player.metal_burn_counts[Metal.ZINC] = 3
            turn_engine.apply(state, Action(ActionKind.ACTIVATE, card=inst,
                                            tier="secondary"), log, chooser)
            player.resources.combat += 5           # combate que llega DESPUÉS
        else:
            player.resources.combat = 5            # combate acumulado ANTES
            inst.primary_activated = True
            player.metal_burn_counts[Metal.ZINC] = 3
            turn_engine.apply(state, Action(ActionKind.ACTIVATE, card=inst,
                                            tier="secondary"), log, chooser)
        player_res.append((player.resources.combat, player.resources.mission))

    convertido_antes, convertido_despues = player_res
    assert convertido_antes == (5, 0), "convertir primero no debe capturar lo posterior"
    assert convertido_despues == (0, 5), "convertir después captura todo lo acumulado"


def test_la_poda_marca_las_conversiones_como_sensibles_al_orden(content, log):
    state = house_war_setup(content, log)
    house_war = state.players[0].hand[0]

    conversion = Action(ActionKind.ACTIVATE, card=house_war, tier="secondary")
    acumulador = Action(ActionKind.ACTIVATE, card=house_war, tier="primary")

    assert solver.order_sensitive(conversion), "la conversión NO conmuta"
    # La primaria de House War es draw + combat: puros acumuladores, sí conmuta.
    assert not solver.order_sensitive(acumulador)
    # Y jugar una carta o quemar una ficha tampoco depende del orden.
    assert not solver.order_sensitive(Action(ActionKind.PLAY_CARD, card=house_war))
    assert not solver.order_sensitive(Action(ActionKind.BURN, metal=Metal.ZINC))


def test_el_solver_acumula_antes_de_convertir(content, log):
    """Con objetivo Misión y House War en la mano, el plan debe convertir combate ya
    acumulado, no activar la conversión en seco."""
    state = house_war_setup(content, log)
    plan = solver.solve_turn(state, "mission", config=solver.SolverConfig(beam_width=20))

    kinds = [(a.kind, a.card.name if a.card else None, a.tier) for a in plan.actions]
    assert (ActionKind.ACTIVATE, "House War", "secondary") in kinds, kinds

    convierte = kinds.index((ActionKind.ACTIVATE, "House War", "secondary"))
    acumula = kinds.index((ActionKind.ACTIVATE, "House War", "primary"))
    assert acumula < convierte, "la conversión debe ir DESPUÉS de generar el combate"

    applied, total, work = replay_counting(plan, state)
    assert applied == total
    assert work.players[0].resources.combat == 0, "todo el combate debió convertirse"


# --- fases de cierre ---------------------------------------------------------


def test_los_puntos_de_mision_se_reparten_con_la_mochila(content, log):
    """Repartir puntos sale del árbol de búsqueda y se resuelve exacto al final."""
    state = controlled_turn(content, log, ["Ironpull"])
    player = state.players[0]
    player.resources.mission = 4
    objective = solver.objective_for("mission")

    actions = solver.plan_mission_spending(state, objective)

    assert actions, "con puntos en la mano tiene que haber reparto"
    assert all(a.kind is ActionKind.ADVANCE_MISSION for a in actions)
    assert sum(a.amount for a in actions) <= 4
    # Y lo que reparte es legal.
    ids = {solver.action_id(a) for a in legal_actions(state)}
    assert all(solver.action_id(a) in ids for a in actions)


def test_el_reparto_prefiere_cruzar_una_recompensa(content, log):
    """Entre dos pistas iguales, gana la que cruza una recompensa con los mismos puntos."""
    state = controlled_turn(content, log, ["Ironpull"])
    player = state.players[0]
    player.resources.mission = 2
    objective = solver.objective_for("mission")

    # Colocamos al jugador a un paso de una recompensa en una sola pista.
    target = None
    for idx, track in enumerate(state.tracks):
        if track.mission.rewards:
            first = min(r.position for r in track.mission.rewards)
            track.positions[player.id] = first - 1
            target = idx
            break
    assert target is not None

    actions = solver.plan_mission_spending(state, objective)
    assert any(a.track == target for a in actions)


def test_refrescar_con_las_cartas_que_van_a_morir_es_gratis(content, log):
    """La mano entera va al descarte al acabar el turno, así que pagar un refresco con
    una carta sobrante no cuesta nada y recupera una ficha flareada."""
    state = controlled_turn(content, log, ["Ironpull", "Steelpush"])
    player = state.players[0]
    player.tokens.flare(Metal.IRON)

    actions = solver.plan_refresh(state)

    assert len(actions) == 1
    assert actions[0].kind is ActionKind.REFRESH
    assert actions[0].metal is Metal.IRON

    turn_engine.apply(state, actions[0], log, GreedyChooser())
    assert player.tokens.state[Metal.IRON] is TokenState.BURNED


def test_una_ficha_flareada_no_se_queda_flareada_si_sobra_una_carta(content):
    """Comprobación de extremo a extremo de lo anterior sobre un turno real."""
    for state in mid_game_states(content, count=5):
        plan = solver.solve_turn(state, "damage", config=FAST)
        applied, total, work = replay_counting(plan, state)
        assert applied == total
        player = work.players[work.active]
        for metal in player.tokens.flared():
            assert not any(metal in inst.card.playable_as_metal() for inst in player.hand), \
                f"quedó {metal} flareado con una carta en mano que podía refrescarlo"


# --- el agente ---------------------------------------------------------------


def test_el_agente_juega_una_partida_entera_sin_caerse_al_respaldo(content):
    """Si el plan no se pudiera ejecutar tal cual, el agente caería en la heurística.

    Que `respaldos` sea 0 es la prueba de que la búsqueda y el estado real no divergen:
    mismo RNG (clonado con su estado interno) y mismo Chooser.
    """
    log = EventLog(keep=frozenset())
    engine = GameEngine(content=content, config=GameConfig(num_players=2, max_turns=30),
                        seed=17, log=log)
    smart = SolverAgent(archetypes.get("aggro-combate"), seed=3,
                        config=solver.SolverConfig(beam_width=8))
    from mistsim.agents.utility import UtilityAgent
    result = engine.run([smart, UtilityAgent(archetypes.get("rush-mision"), seed=4)])

    assert result.turns > 0
    assert smart.stats["turnos"] > 0
    assert smart.stats["respaldos"] == 0
    assert smart.stats["acciones"] > smart.stats["turnos"]


class _AuditingEngine(GameEngine):
    """Motor que revisa la conservación de cartas al final de cada turno."""

    def _play_turn(self, state, player, agent):
        super()._play_turn(state, player, agent)
        uids = [c.uid for p in state.players for c in p.all_cards()]
        uids += [c.uid for c in state.market.row]
        uids += [c.uid for c in state.market.deck]
        uids += [c.uid for c in state.eliminated]
        assert len(uids) == len(set(uids)), "una carta está en dos zonas a la vez"
        if self._expected is None:
            self._expected = len(uids)
        assert len(uids) == self._expected, "el recuento de cartas cambió"

    def run(self, agents, characters=None):
        self._expected = None
        return super().run(agents, characters)


@pytest.mark.parametrize("seed", [23, 24, 25])
def test_el_agente_conserva_las_cartas(content, seed):
    """Mismo invariante que el resto del motor: el solver clona estados a mansalva y
    reata acciones por `uid`, que es justo la manera de duplicar o perder una carta."""
    from mistsim.agents.utility import UtilityAgent

    engine = _AuditingEngine(content=content,
                             config=GameConfig(num_players=2, max_turns=20),
                             seed=seed, log=EventLog(keep=frozenset()))
    engine.run([SolverAgent(archetypes.get("equilibrado"), seed=1,
                            config=solver.SolverConfig(beam_width=6)),
                UtilityAgent(archetypes.get("muro-defender"), seed=2)])


def test_el_objetivo_del_perfil_pesa_como_el_agente_por_utilidad(content):
    """El objetivo del solver sale del MISMO perfil que usa la heurística: la comparación
    entre las dos IAs aísla el orden del turno, no el criterio de valor."""
    profile = archetypes.get("aggro-combate")
    objective = objective_from_profile(profile)
    assert objective.weight("combat") == profile.resource_value("combat")
    assert objective.weight("mission") == profile.resource_value("mission")
    assert objective.weight("combat") > objective.weight("mission")


def test_objetivo_desconocido_falla_ruidosamente():
    with pytest.raises(ValueError):
        solver.objective_for("gloria")
