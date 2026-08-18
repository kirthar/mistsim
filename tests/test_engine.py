"""Reglas del motor, con foco en las que son fáciles de implementar mal."""

import pytest

from mistsim.domain.cards import CardInstance
from mistsim.domain.metals import Metal, TokenState
from mistsim.domain.state import GameConfig
from mistsim.engine.actions import Action, ActionKind, legal_actions
from mistsim.engine.choices import GreedyChooser
from mistsim.engine.effects import EffectContext, UnknownEffect, resolve
from mistsim.engine.game import GameEngine, RandomAgent
from mistsim.engine.turn import IllegalAction, apply, start_turn


def put_in_hand(game, content, player_id, card_name):
    """Coloca una carta concreta en la mano, para montar situaciones deterministas."""
    card = content.market_by_name(card_name)
    inst = CardInstance(uid=9000 + len(game.players[player_id].hand), card=card)
    game.players[player_id].hand.append(inst)
    return inst


# --- metales -----------------------------------------------------------------


def test_burning_is_limited_but_playing_cards_as_metal_is_not(game, content, log):
    """El límite cuenta fichas, no cartas (FAQ)."""
    player = game.players[0]
    start_turn(game, player, log)
    assert player.tokens.burn_limit == 1

    apply(game, Action(ActionKind.BURN, metal=Metal.PEWTER), log, GreedyChooser())
    assert not any(a.kind is ActionKind.BURN for a in legal_actions(game))

    # Pero jugar cartas de lado sigue siendo legal, tantas como se quiera.
    as_metal = [a for a in legal_actions(game) if a.kind is ActionKind.CARD_AS_METAL]
    assert as_metal, "jugar carta como metal debe seguir disponible tras agotar la quema"


def test_refreshed_metal_cannot_be_reused_the_same_turn(game, content, log):
    """El FAQ es explícito: refrescar no devuelve la ficha al uso este turno."""
    player = game.players[0]
    start_turn(game, player, log)
    player.tokens.flare(Metal.IRON)
    assert player.tokens.state[Metal.IRON] is TokenState.FLARED

    payment = put_in_hand(game, content, 0, "Ironpull")  # vial Iron/Steel
    apply(game, Action(ActionKind.REFRESH, metal=Metal.IRON, payment=payment),
          log, GreedyChooser())

    assert player.tokens.state[Metal.IRON] is TokenState.BURNED
    assert not player.tokens.can_burn(Metal.IRON)


def test_a_flared_token_cannot_be_flared_again(game, log):
    player = game.players[0]
    start_turn(game, player, log)
    player.tokens.burn(Metal.PEWTER)
    assert not player.tokens.can_flare(Metal.PEWTER)


# --- habilidades -------------------------------------------------------------


def test_secondary_requires_primary_first(game, content, log):
    player = game.players[0]
    start_turn(game, player, log)
    inst = put_in_hand(game, content, 0, "Charm")  # Zinc, +ZINC secundaria

    apply(game, Action(ActionKind.PLAY_CARD, card=inst), log, GreedyChooser())
    apply(game, Action(ActionKind.BURN, metal=Metal.ZINC), log, GreedyChooser())

    with pytest.raises(IllegalAction, match="primaria"):
        apply(game, Action(ActionKind.ACTIVATE, card=inst, tier="secondary"),
              log, GreedyChooser())


def test_secondary_needs_its_extra_burns_before_it_is_legal(game, content, log):
    """Crushing Blow imprime "+2 PEWTER": hacen falta 2 quemas más que la primaria."""
    player = game.players[0]
    start_turn(game, player, log)
    player.tokens.burn_limit = 4
    inst = put_in_hand(game, content, 0, "Crushing Blow")
    assert inst.card.secondary.extra_burns == 2

    apply(game, Action(ActionKind.PLAY_CARD, card=inst), log, GreedyChooser())
    apply(game, Action(ActionKind.BURN, metal=Metal.PEWTER), log, GreedyChooser())
    apply(game, Action(ActionKind.ACTIVATE, card=inst, tier="primary"), log, GreedyChooser())
    assert player.resources.combat == 6

    def secondary_offered():
        return any(a.kind is ActionKind.ACTIVATE and a.tier == "secondary"
                   for a in legal_actions(game))

    assert not secondary_offered(), "con 1 quema no debe ofrecerse"
    player.note_metal(Metal.PEWTER)
    assert not secondary_offered(), "con 2 quemas tampoco: pide 2 ADICIONALES"
    player.note_metal(Metal.PEWTER)
    assert secondary_offered(), "con 3 quemas (1 + 2 extra) ya es legal"


def test_character_ability_fires_only_once_per_turn(game, log):
    player = game.players[0]  # Vin, Peltre
    start_turn(game, player, log)
    apply(game, Action(ActionKind.BURN, metal=Metal.PEWTER), log, GreedyChooser())

    apply(game, Action(ActionKind.CHARACTER, metal=Metal.PEWTER), log, GreedyChooser())
    assert (player.resources.combat, player.resources.coin) == (1, 1)

    assert not any(a.kind is ActionKind.CHARACTER for a in legal_actions(game))
    with pytest.raises(IllegalAction):
        apply(game, Action(ActionKind.CHARACTER, metal=Metal.PEWTER), log, GreedyChooser())


def test_savant_only_triggers_when_played_sideways(game, content, log):
    """Brawl da savant combate 2, pero sólo jugándola COMO metal."""
    player = game.players[0]
    start_turn(game, player, log)
    inst = put_in_hand(game, content, 0, "Brawl")
    assert inst.card.savant == {"combat": 2}

    apply(game, Action(ActionKind.PLAY_CARD, card=inst), log, GreedyChooser())
    assert player.resources.combat == 0, "jugarla normal no da savant"

    other = put_in_hand(game, content, 0, "Brawl")
    apply(game, Action(ActionKind.CARD_AS_METAL, card=other, metal=Metal.PEWTER),
          log, GreedyChooser())
    assert player.resources.combat == 2


# --- efectos -----------------------------------------------------------------


def test_conversion_only_takes_what_is_already_accumulated(game, log):
    """El FAQ: los efectos se resuelven al instante, así que no capturan lo posterior."""
    player = game.players[0]
    player.resources.mission = 5
    ctx = EffectContext(game, player, log, GreedyChooser(), source="test")

    resolve({"convert_all_mission_to_combat": True}, ctx)
    assert (player.resources.mission, player.resources.combat) == (0, 5)

    player.resources.mission = 3  # ganado DESPUÉS: la conversión ya pasó
    assert player.resources.combat == 5


def test_unknown_effects_fail_loudly(game, log):
    ctx = EffectContext(game, game.players[0], log, GreedyChooser(), source="test")
    with pytest.raises(UnknownEffect, match="inventado"):
        resolve({"inventado": 1}, ctx)


def test_mission_points_never_move_a_cube_backwards(game, log):
    player = game.players[0]
    ctx = EffectContext(game, player, log, GreedyChooser(), source="test")
    player.resources.mission = 2
    resolve({"mission": -5}, ctx)
    assert player.resources.mission == 0
    assert game.tracks[0].position_of(player.id) == 0


# --- combate -----------------------------------------------------------------


def test_defender_ally_shields_the_player_and_other_allies(game, content, log):
    from mistsim.engine.combat import resolve_combat

    attacker, victim = game.players[0], game.players[1]
    defender = CardInstance(1, content.market_by_name("Soldier"))     # Defender, def 2
    squishy = CardInstance(2, content.market_by_name("Pickpocket"))   # no Defender, def 2
    victim.allies = [defender, squishy]
    attacker.resources.combat = 2
    health_before = victim.health

    resolve_combat(game, attacker, log, GreedyChooser())

    assert defender not in victim.allies, "el Defender debe caer primero"
    assert squishy in victim.allies
    assert victim.health == health_before, "sin daño sobrante para el jugador"


def test_allies_need_full_defense_in_one_hit(game, content, log):
    from mistsim.engine.combat import resolve_combat

    attacker, victim = game.players[0], game.players[1]
    tough = CardInstance(1, content.market_by_name("Inquisitor"))  # def 4
    victim.allies = [tough]
    attacker.resources.combat = 3  # no llega

    resolve_combat(game, attacker, log, GreedyChooser())
    assert tough in victim.allies, "no hay daño parcial contra Aliados"


# --- partida completa --------------------------------------------------------


def test_a_random_game_terminates_and_conserves_cards(content):
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=2, max_turns=30), seed=11)
    result = engine.run([RandomAgent(1), RandomAgent(2)])
    assert result.turns <= 30
    assert result.reason


@pytest.mark.parametrize("players", [2, 3, 4])
def test_games_finish_for_every_player_count(content, players):
    engine = GameEngine(content=content,
                        config=GameConfig(num_players=players, max_turns=25),
                        seed=100 + players)
    result = engine.run([RandomAgent(i) for i in range(players)])
    assert result.reason
    assert result.turns <= 25
