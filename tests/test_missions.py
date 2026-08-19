"""Efectos que sólo aparecen en las cartas de Misión reales.

Las 8 Misiones fotografiadas piden cosas que el motor no sabía hacer. Meterlas sin
implementarlas las habría dejado como no-op silencioso — el fallo que ya ha falseado
este simulador cuatro veces — así que cada una lleva su test.
"""
import random

import pytest

from mistsim.domain.metals import Metal, TokenState
from mistsim.domain.state import GameConfig
from mistsim.engine.choices import GreedyChooser
from mistsim.engine.effects import EffectContext, resolve
from mistsim.engine.events import EventLog
from mistsim.engine.setup import new_game
from mistsim.engine.turn import start_turn


@pytest.fixture
def state(content):
    return new_game(content, GameConfig(num_players=2), ["vin", "kelsier"],
                    random.Random(3), EventLog())


def ctx_for(state, log, player=None):
    return EffectContext(state, player or state.players[0], log, GreedyChooser(),
                         source="test-mission")


# --- Cavernes Skaa: +1 quema permanente --------------------------------------


def test_permanent_burn_raises_the_limit(state, log):
    player = state.players[0]
    start_turn(state, player, log)
    before = player.tokens.burn_limit

    resolve({"permanent_burn_per_turn": 1}, ctx_for(state, log))
    assert player.tokens.burn_limit == before + 1


def test_permanent_burn_survives_training_advancing(state, log):
    """La trampa: la pista de Entrenamiento FIJABA el límite y se comía el bonus.

    Ahora el límite se recompone de sus fuentes (Entrenamiento + Aliados + Misiones),
    así que avanzar en la pista no puede pisar un bonus permanente.
    """
    player = state.players[0]
    start_turn(state, player, log)
    resolve({"permanent_burn_per_turn": 1}, ctx_for(state, log))
    with_bonus = player.tokens.burn_limit

    # Avanzar el Entrenamiento hasta cruzar un escalón de quema.
    for _ in range(8):
        start_turn(state, player, log)

    base_sin_bonus = min(4, 1 + player.training // 3)
    assert player.tokens.burn_limit == base_sin_bonus + 1
    assert player.tokens.burn_limit > with_bonus, "el Entrenamiento debe seguir subiendo"


def test_an_ally_burn_bonus_also_survives_training(state, content, log):
    """Mismo fallo que afectaba a Noble desde siempre, no sólo a las Misiones."""
    from mistsim.domain.cards import CardInstance

    player = state.players[0]
    start_turn(state, player, log)
    noble = content.market_by_name("Noble")
    assert noble.ongoing == "extra_metal_burn"
    player.allies.append(CardInstance(999, noble))
    player.recompute_burn_limit()

    for _ in range(8):
        start_turn(state, player, log)

    assert player.tokens.burn_limit == min(4, 1 + player.training // 3) + 1


def test_losing_the_ally_takes_the_bonus_away(state, content, log):
    from mistsim.domain.cards import CardInstance

    player = state.players[0]
    start_turn(state, player, log)
    player.allies.append(CardInstance(999, content.market_by_name("Noble")))
    player.recompute_burn_limit()
    with_ally = player.tokens.burn_limit

    player.allies.clear()
    player.recompute_burn_limit()
    assert player.tokens.burn_limit == with_ally - 1


# --- Guarnició de Luthadel: +2 combate por turno -----------------------------


def test_permanent_combat_pays_out_every_turn(state, log):
    player = state.players[0]
    resolve({"permanent_combat_per_turn": 2}, ctx_for(state, log))

    for _ in range(3):
        start_turn(state, player, log)
        assert player.resources.combat == 2, "debe cobrarse cada turno, no una vez"


# --- Torrassa Venture / Kredik Shaw ------------------------------------------


def test_permanent_coin_pays_out_every_turn(state, log):
    player = state.players[0]
    resolve({"permanent_coin_per_turn": 2}, ctx_for(state, log))
    for _ in range(3):
        start_turn(state, player, log)
        assert player.resources.coin == 2


def test_permanent_draw_grows_the_hand(state, log):
    from mistsim.engine.turn import end_turn

    player = state.players[0]
    resolve({"permanent_draw_per_turn": 1}, ctx_for(state, log))
    start_turn(state, player, log)
    end_turn(state, player, log)
    assert len(player.hand) == 6, "5 de mano + 1 permanente"


# --- Cavernes Skaa: refrescar ------------------------------------------------


def test_refresh_all_unflares_every_metal(state, log):
    player = state.players[0]
    start_turn(state, player, log)
    for metal in (Metal.IRON, Metal.ZINC, Metal.COPPER):
        player.tokens.flare(metal)
    assert len(player.tokens.flared()) == 3

    resolve({"refresh_all": True}, ctx_for(state, log))
    assert player.tokens.flared() == []


def test_permanent_refresh_recovers_metals_each_turn(state, log):
    player = state.players[0]
    resolve({"permanent_refresh_per_turn": 2}, ctx_for(state, log))
    start_turn(state, player, log)
    player.tokens.flare(Metal.IRON)
    player.tokens.flare(Metal.ZINC)
    player.tokens.flare(Metal.BRASS)

    start_turn(state, player, log)
    assert len(player.tokens.flared()) == 1, "dos de los tres deben recuperarse"


def test_refreshed_metals_are_usable_the_next_turn(state, log):
    """Refrescar deja la ficha BURNED este turno (FAQ), pero lista al siguiente."""
    player = state.players[0]
    start_turn(state, player, log)
    player.tokens.flare(Metal.IRON)
    resolve({"refresh_all": True}, ctx_for(state, log))
    assert player.tokens.state[Metal.IRON] is TokenState.BURNED

    start_turn(state, player, log)
    assert player.tokens.state[Metal.IRON] is TokenState.READY


# --- ninguna Misión debe quedar sin implementar ------------------------------


def test_no_mission_effect_is_silently_unimplemented(content, state, log):
    """Recorre TODAS las recompensas de las 8 Misiones y las resuelve de verdad."""
    for mission in content.missions:
        for effects in [mission.starting_bonus, mission.top_reward,
                        mission.top_reward_first_bonus]:
            if effects:
                resolve(dict(effects), ctx_for(state, log))
        for reward in mission.rewards:
            resolve(dict(reward.effects), ctx_for(state, log))
            if reward.first_player_bonus:
                resolve(dict(reward.first_player_bonus), ctx_for(state, log))

    faltan = {e.data["effect"] for e in log.of_kind("effect-unimplemented")}
    assert not faltan, f"efectos de Misión sin implementar: {sorted(faltan)}"
