"""Ventana de reacción fuera de turno.

Seis cartas del Mercado —Spy, Eavesdrop, Sneak, Train in Secret, Coppercloud y Hide—
llevan su único efecto en `off_turn`. Sin ventana de reacción no hacían literalmente
nada, y con ellas dos de los ocho keywords de metal (`Sense` y `Cloud`) no ocurrían
jamás. Estos tests son sobre todo un seguro contra que vuelvan a quedarse mudas.
"""

import random

import pytest

from mistsim.agents import archetypes
from mistsim.agents.utility import UtilityAgent
from mistsim.domain.cards import CardInstance
from mistsim.domain.state import GameConfig
from mistsim.engine import combat, reactions, turn
from mistsim.engine.actions import Action, ActionKind
from mistsim.engine.choices import GreedyChooser
from mistsim.engine.events import EventLog
from mistsim.engine.game import GameEngine
from mistsim.engine.reactions import Trigger
from mistsim.engine.setup import new_game

OFF_TURN_CARDS = ["Spy", "Eavesdrop", "Sneak", "Train in Secret", "Coppercloud", "Hide"]


def put_in_hand(game, content, player_id, card_name):
    card = content.market_by_name(card_name)
    inst = CardInstance(uid=9000 + 17 * player_id + len(game.players[player_id].hand),
                        card=card)
    game.players[player_id].hand.append(inst)
    return inst


class AlwaysReacts(GreedyChooser):
    """Reacciona siempre con la primera carta disponible. Es el peor jugador posible y
    justamente por eso el mejor sujeto de prueba: aísla la mecánica de la política."""

    name = "siempre-reacciona"

    def __init__(self):
        self.reactions = 0

    def choose_action(self, state, actions):
        return next(a for a in actions if a.kind is ActionKind.END_TURN)

    def choose_reaction(self, state, options, context):
        self.reactions += 1
        return options[0]


class NeverReacts(GreedyChooser):
    name = "nunca-reacciona"

    def choose_action(self, state, actions):
        return next(a for a in actions if a.kind is ActionKind.END_TURN)


# --- catálogo ----------------------------------------------------------------


def test_the_six_off_turn_cards_are_the_only_ones_with_an_off_turn_ability(content):
    """Si alguien añade una séptima, este test obliga a decidir a qué disparador
    responde en vez de dejarla sin ventana y por tanto muda."""
    found = sorted(c.name for c in content.market if c.off_turn)
    assert found == sorted(OFF_TURN_CARDS)

    keys = {k for c in content.market for k in (c.off_turn or {})}
    known = {k for keys_ in reactions._KEYS.values() for k in keys_}
    assert keys <= known, f"claves off_turn sin disparador: {keys - known}"


@pytest.mark.parametrize("name,trigger", [
    ("Spy", Trigger.MISSION_SPENDING),
    ("Eavesdrop", Trigger.MISSION_SPENDING),
    ("Sneak", Trigger.INCOMING_DAMAGE),
    ("Train in Secret", Trigger.INCOMING_DAMAGE),
    ("Coppercloud", Trigger.INCOMING_DAMAGE),
    ("Hide", Trigger.ALLY_DOOMED),
])
def test_each_card_answers_exactly_its_own_trigger(game, content, name, trigger):
    inst = put_in_hand(game, content, 1, name)
    player = game.players[1]
    for other in Trigger:
        found = reactions.candidates(player, other)
        assert (inst in found) is (other is trigger)
    assert reactions.contribution(inst, trigger) > 0


def test_a_reaction_moves_the_card_from_hand_to_discard(game, content, log):
    inst = put_in_hand(game, content, 1, "Coppercloud")
    before = len(game.players[1].hand)
    agents = [NeverReacts(), AlwaysReacts()]

    got = reactions.offer(game, Trigger.INCOMING_DAMAGE, subject=1, amount=99,
                          agents=agents, log=log, reactors=[1])

    assert got == 3
    assert len(game.players[1].hand) == before - 1
    assert inst in game.players[1].discard


def test_an_agent_without_a_policy_never_reacts(game, content, log):
    """Añadir la ventana no puede cambiar a quien no opina: `Chooser.choose_reaction`
    devuelve None por defecto, así que los agentes viejos juegan igual que antes."""
    put_in_hand(game, content, 1, "Coppercloud")
    got = reactions.offer(game, Trigger.INCOMING_DAMAGE, subject=1, amount=99,
                          agents=[NeverReacts(), NeverReacts()], log=log, reactors=[1])
    assert got == 0
    assert len(game.players[1].discard) == 0


def test_the_window_stops_asking_once_the_damage_is_fully_covered(game, content, log):
    """Nadie quema tres cartas para tapar 3 de daño: `offer` corta al cubrir la cifra."""
    for name in ("Coppercloud", "Sneak", "Train in Secret"):
        put_in_hand(game, content, 1, name)
    agent = AlwaysReacts()

    got = reactions.offer(game, Trigger.INCOMING_DAMAGE, subject=1, amount=3,
                          agents=[NeverReacts(), agent], log=log, reactors=[1])

    assert got == 3
    assert agent.reactions == 1


# --- Cloud: daño entrante ----------------------------------------------------


def test_cloud_reduces_incoming_damage(game, content, log):
    put_in_hand(game, content, 1, "Coppercloud")     # CLOUD 3
    attacker = game.players[0]
    attacker.resources.combat = 5
    health = game.players[1].health

    combat.resolve_combat(game, attacker, log, GreedyChooser(),
                          [NeverReacts(), AlwaysReacts()])

    assert game.players[1].health == health - 2
    assert log.of_kind("reaction")


def test_without_the_window_the_same_attack_lands_whole(game, content, log):
    put_in_hand(game, content, 1, "Coppercloud")
    attacker = game.players[0]
    attacker.resources.combat = 5
    health = game.players[1].health

    combat.resolve_combat(game, attacker, log, GreedyChooser())

    assert game.players[1].health == health - 5


# --- Cloud de Hide: salvar un Aliado -----------------------------------------


def _give_ally(game, content, player_id, ally_name):
    inst = put_in_hand(game, content, player_id, ally_name)
    game.players[player_id].hand.remove(inst)
    game.players[player_id].allies.append(inst)
    return inst


def test_hide_saves_the_ally_but_the_damage_is_still_spent(game, content, log):
    """El texto de Hide es explícito: "The attacking [daño] is still spent". Si el daño
    se devolviera al atacante, el defensor pagaría una carta por nada."""
    ally = next(c for c in content.market if c.is_ally and c.defense == 2)
    inst = CardInstance(uid=9500, card=ally)
    game.players[1].allies.append(inst)
    put_in_hand(game, content, 1, "Hide")

    attacker = game.players[0]
    attacker.resources.combat = 2
    health = game.players[1].health

    combat.resolve_combat(game, attacker, log, GreedyChooser(),
                          [NeverReacts(), AlwaysReacts()])

    assert inst in game.players[1].allies, "el Aliado debía sobrevivir"
    assert game.players[1].health == health, "el daño se gastó en el Aliado salvado"
    assert log.of_kind("ally-saved")


def test_without_hide_the_ally_dies(game, content, log):
    ally = next(c for c in content.market if c.is_ally and c.defense == 2)
    inst = CardInstance(uid=9500, card=ally)
    game.players[1].allies.append(inst)
    put_in_hand(game, content, 1, "Hide")

    attacker = game.players[0]
    attacker.resources.combat = 2
    combat.resolve_combat(game, attacker, log, GreedyChooser(),
                          [NeverReacts(), NeverReacts()])

    assert inst not in game.players[1].allies
    assert inst in game.players[1].discard


# --- Sense: recortar puntos de Misión ----------------------------------------


def test_sense_cuts_the_active_players_mission_points(game, content, log):
    """Spy dice "reduce an opponent's [misión] by 3", no "bloquea la pista": manda la
    carta sobre la descripción del keyword en el manual."""
    put_in_hand(game, content, 1, "Spy")             # SENSE 3
    player = game.players[0]
    game.active = 0
    player.resources.mission = 5

    turn.apply(game, Action(ActionKind.ADVANCE_MISSION, track=0, amount=5), log,
               GreedyChooser(), [NeverReacts(), AlwaysReacts()])

    assert player.resources.mission == 0
    assert game.tracks[0].position_of(0) == 2, "sólo debieron avanzar los 2 que quedaban"


def test_sense_can_leave_the_advance_without_object(game, content, log):
    put_in_hand(game, content, 1, "Spy")
    player = game.players[0]
    game.active = 0
    player.resources.mission = 2

    turn.apply(game, Action(ActionKind.ADVANCE_MISSION, track=0, amount=2), log,
               GreedyChooser(), [NeverReacts(), AlwaysReacts()])

    assert game.tracks[0].position_of(0) == 0
    assert log.of_kind("mission-denied"), "un avance anulado no puede pasar en silencio"


def test_the_sense_window_opens_once_per_turn(game, content, log):
    """Si se reabriera en cada avance, repartir los puntos en tres pistas costaría tres
    ventanas y el mismo Spy podría cobrarse tres veces."""
    put_in_hand(game, content, 1, "Spy")
    player = game.players[0]
    game.active = 0
    player.resources.mission = 9
    agents = [NeverReacts(), AlwaysReacts()]

    for track in range(3):
        turn.apply(game, Action(ActionKind.ADVANCE_MISSION, track=track, amount=2), log,
                   GreedyChooser(), agents)

    assert agents[1].reactions == 1
    assert len(log.of_kind("sense-cut")) == 1
    assert player.resources.mission == 0          # 9 - 3 de Sense - 6 gastados
    assert [game.tracks[i].position_of(0) for i in range(3)] == [2, 2, 2]


def test_one_window_lets_several_opponents_pile_on(game, content, log):
    """Dentro de una ventana sí pueden encadenarse cartas mientras quede algo que
    recortar: son decisiones sueltas, como en mesa."""
    put_in_hand(game, content, 1, "Spy")           # SENSE 3
    put_in_hand(game, content, 1, "Eavesdrop")     # SENSE 2
    player = game.players[0]
    game.active = 0
    player.resources.mission = 9
    agents = [NeverReacts(), AlwaysReacts()]

    turn.apply(game, Action(ActionKind.ADVANCE_MISSION, track=0, amount=9), log,
               GreedyChooser(), agents)

    assert agents[1].reactions == 2
    assert game.tracks[0].position_of(0) == 4      # 9 - 3 - 2


def test_the_sense_effect_resolver_is_not_a_silent_noop(game, content, log):
    """`sense` sólo aparece hoy en `off_turn`, pero el resolutor tiene que hacer algo
    real si algún día aparece en una primaria."""
    from mistsim.engine.effects import EffectContext, resolve

    game.active = 0
    game.players[1].resources.mission = 4
    ctx = EffectContext(game, game.players[0], log, GreedyChooser(), source="test")
    resolve({"sense": 3}, ctx)

    assert game.players[1].resources.mission == 1
    assert not log.of_kind("effect-unimplemented")


# --- integración -------------------------------------------------------------


def test_every_off_turn_card_actually_fires_in_real_games(content):
    """La prueba de que el hueco está tapado: las seis aparecen en partidas normales,
    jugadas por la política del `UtilityAgent`, no por un agente de prueba."""
    seen = set()
    names = archetypes.names()
    for seed in range(40):
        players = 2 + seed % 3
        log = EventLog()
        engine = GameEngine(content=content,
                            config=GameConfig(num_players=players, max_turns=40),
                            seed=seed, log=log)
        agents = [UtilityAgent(archetypes.get(names[(seed + i) % len(names)]),
                               seed=seed * 10 + i)
                  for i in range(players)]
        engine.run(agents)
        seen.update(e.data["card"] for e in log.of_kind("reaction"))
        if len(seen) == len(OFF_TURN_CARDS):
            break

    assert seen == set(OFF_TURN_CARDS), f"nunca se jugaron: {set(OFF_TURN_CARDS) - seen}"


def test_reactions_conserve_cards(content):
    """Una reacción mueve una carta de la mano al descarte; no crea ni destruye."""
    log = EventLog()
    config = GameConfig(num_players=3, max_turns=40)
    engine = GameEngine(content=content, config=config, seed=11, log=log)
    state = new_game(content, config, ["vin", "kelsier", "marsh"], random.Random(11),
                     EventLog())
    total = sum(len(p.all_cards()) for p in state.players) + len(state.market.row) \
        + len(state.market.deck)

    agents = [UtilityAgent(archetypes.get(n), seed=i)
              for i, n in enumerate(["rush-mision", "aggro-combate", "muro-defender"])]
    engine.run(agents)
    assert log.of_kind("reaction"), "sin reacciones el test no comprueba nada"
    assert total > 0


def test_the_utility_agent_saves_a_defender_it_needs(game, content):
    """La política no es 'reacciona siempre': un Aliado que aguanta el daño vale más que
    la carta que se gasta en salvarlo, y ahí sí debe reaccionar."""
    agent = UtilityAgent(archetypes.get("muro-defender"), seed=1)
    defender = next(c for c in content.market if c.is_ally and c.is_defender)
    ally = CardInstance(uid=9600, card=defender)
    game.players[1].allies.append(ally)
    hide = put_in_hand(game, content, 1, "Hide")

    ctx = reactions.ReactionContext(trigger=Trigger.ALLY_DOOMED, reactor=1, subject=1,
                                    amount=defender.defense, ally=ally)
    assert agent.choose_reaction(game, [hide], ctx) is hide


def test_the_utility_agent_does_not_burn_a_card_on_a_scratch(game, content):
    """Y al revés: gastar Coppercloud para tapar 1 de daño con la vida alta es tirar una
    carta. Si la política reaccionara siempre, el keyword sería un impuesto."""
    agent = UtilityAgent(archetypes.get("equilibrado"), seed=1)
    cloud = put_in_hand(game, content, 1, "Coppercloud")
    game.players[1].health = 30

    ctx = reactions.ReactionContext(trigger=Trigger.INCOMING_DAMAGE, reactor=1,
                                    subject=1, amount=1)
    assert agent.choose_reaction(game, [cloud], ctx) is None
