"""Montaje de una partida a partir del contenido y la configuración."""
from __future__ import annotations

import itertools
import random

from mistsim.content.loader import Content
from mistsim.domain.cards import CardInstance
from mistsim.domain.missions import MissionTrack
from mistsim.domain.player import Player
from mistsim.domain.state import GameConfig, GameState, LordRuler, Market, Mode
from mistsim.engine.events import EventLog

BASE_HEALTH = 36
#: Bonus de salud por orden de turno; el 4º recibe además 1 Boxing.
TURN_ORDER_HEALTH = {0: 0, 1: 2, 2: 4, 3: 4}
MISSIONS_PER_GAME = 3


def new_game(content: Content, config: GameConfig, characters: list[str],
             rng: random.Random, log: EventLog) -> GameState:
    if len(characters) != config.num_players:
        raise ValueError(
            f"{config.num_players} jugadores pero {len(characters)} personajes")

    uids = itertools.count()
    coop = config.mode is Mode.COOP

    players = []
    for seat, char_id in enumerate(characters):
        character = content.character(char_id)
        # En Solo/Coop no se reparten los bonus de orden de turno.
        health = BASE_HEALTH + (0 if coop else TURN_ORDER_HEALTH.get(seat, 4))
        player = Player(id=seat, character=character, health=health)
        if not coop and seat == 3:
            player.boxings = 1
        deck = [CardInstance(next(uids), card) for card in content.starting_deck(char_id)]
        rng.shuffle(deck)
        player.deck = deck
        player.draw(5, rng)
        players.append(player)

    market_deck = [
        CardInstance(next(uids), card)
        for card in content.market
        for _ in range(card.copies)
    ]
    rng.shuffle(market_deck)
    market = Market(deck=market_deck)
    market.refill()

    chosen = rng.sample(list(content.missions), MISSIONS_PER_GAME)
    tracks = [MissionTrack(mission=m) for m in chosen]

    state = GameState(
        config=config, players=players, market=market, tracks=tracks, rng=rng,
    )

    if coop:
        lr_deck = list(content.lord_ruler)
        rng.shuffle(lr_deck)
        state.lord_ruler = LordRuler(deck=lr_deck)
    elif config.num_players >= 3:
        # El Objetivo empieza en el último jugador en sentido horario desde el primero.
        state.target_holder = config.num_players - 1

    log.emit("game-start", None, mode=str(config.mode), players=config.num_players,
             characters=characters, missions=[m.name for m in chosen])
    _apply_starting_bonuses(state, log)
    return state


def _apply_starting_bonuses(state: GameState, log: EventLog) -> None:
    """Algunas Misiones dan un bonus por empezar la partida."""
    for track in state.tracks:
        bonus = track.mission.starting_bonus
        if not bonus:
            continue
        for player in state.players:
            for key, value in bonus.items():
                if key == "atium":
                    player.atium += value
        log.emit("mission-starting-bonus", None, track=track.mission.name,
                 effects=dict(bonus))
