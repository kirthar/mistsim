"""Estado completo de una partida."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from mistsim.domain.cards import Card, CardInstance
from mistsim.domain.metals import MetalTokens
from mistsim.domain.missions import MissionTrack
from mistsim.domain.player import Player, TurnResources


class Mode(StrEnum):
    PVP = "pvp"
    COOP = "coop"


@dataclass
class Market:
    """La fila de 6 cartas visibles y el mazo del que se reponen."""

    row: list[CardInstance] = field(default_factory=list)
    deck: list[CardInstance] = field(default_factory=list)
    size: int = 6

    def refill(self) -> list[CardInstance]:
        """Repone la fila hasta `size` desde el mazo.

        La fila se extiende dentro del bucle a propósito: comprobar la longitud sobre
        una lista que sólo se actualiza al final vacía el mazo entero de una vez.
        El Mercado puede quedar corto si el mazo se agota, que es lo que dice el manual.
        """
        added = []
        while len(self.row) < self.size and self.deck:
            card = self.deck.pop()
            self.row.append(card)
            added.append(card)
        return added

    def take(self, inst: CardInstance) -> CardInstance:
        self.row.remove(inst)
        self.refill()
        return inst

    def affordable(self, coin: int) -> list[CardInstance]:
        return [c for c in self.row if c.card.cost <= coin]


@dataclass
class LordRuler:
    """El adversario del modo Solo/Coop."""

    health: int = 48
    dominance: int = 1
    dominance_max: int = 6
    deck: list[dict] = field(default_factory=list)
    adversaries: list[dict] = field(default_factory=list)
    #: id de Adversario -> escudos que le quedan (el valor "X" se resuelve al golpear).
    shields: dict[str, list[int | str]] = field(default_factory=dict)
    #: id de Adversario -> jugador al que está asignado.
    assigned_to: dict[str, int] = field(default_factory=dict)

    def shield_value(self, raw: int | str) -> int:
        return self.dominance if raw == "X" else int(raw)

    def raise_dominance(self, steps: int) -> int:
        before = self.dominance
        self.dominance = min(self.dominance_max, self.dominance + steps)
        return self.dominance - before


@dataclass
class GameConfig:
    """Reglas discutibles, expuestas para poder medir el efecto de la lectura contraria.

    Ver data/RULES_DECISIONS.md: los valores por defecto siguen el FAQ oficial.
    """

    mode: Mode = Mode.PVP
    num_players: int = 2
    max_turns: int = 60
    #: FAQ: refrescar un metal flareado NO permite volver a usarlo ese turno.
    refresh_allows_reuse_same_turn: bool = False
    #: FAQ (errata): Riot da una activación extra, además de la normal por quema.
    riot_grants_extra_activation: bool = True
    #: FAQ: Sense no tiene ningún efecto sobre el Lord Ruler.
    sense_affects_lord_ruler: bool = False


@dataclass
class GameState:
    config: GameConfig
    players: list[Player]
    market: Market
    tracks: list[MissionTrack]
    rng: random.Random
    turn: int = 0
    active: int = 0
    #: Montón compartido de cartas eliminadas, visible para todos.
    eliminated: list[CardInstance] = field(default_factory=list)
    #: Quién tiene el Objetivo (sólo 3-4 jugadores en PvP).
    target_holder: int | None = None
    lord_ruler: LordRuler | None = None
    winner: int | None = None
    #: Puesto cuando alguien gana por Confrontation, para distinguirlo de las demás vías.
    victory_reason: str | None = None
    finished: bool = False

    def clone(self) -> GameState:
        """Copia independiente del estado, para explorar una rama sin destruir la actual.

        La usa el solver de turno: aplica una secuencia de acciones sobre el clon, mide
        el resultado y lo descarta. El RNG se copia con su estado interno, así que dos
        ramas exploradas desde el mismo punto son comparables — si el azar divergiera
        entre ramas, el solver compararía peras con manzanas.

        Está escrito a mano en vez de con `deepcopy` porque el solver clona cientos de
        veces por turno y `deepcopy` cuesta unas 10 veces más: recorre objeto a objeto
        las ~120 instancias de carta del estado. Aquí se comparten las definiciones
        inmutables (Card, Mission, Character) y sólo se copia lo que muta.

        Al añadir un campo mutable a GameState, Player, Market o MissionTrack hay que
        reflejarlo aquí. `test_clone_matches_deepcopy_field_by_field` falla si se olvida.
        """
        rng = random.Random()
        rng.setstate(self.rng.getstate())

        clone = GameState(
            config=self.config,          # inmutable en la práctica: se comparte
            players=[_clone_player(p) for p in self.players],
            market=Market(
                row=[_clone_instance(c) for c in self.market.row],
                deck=[_clone_instance(c) for c in self.market.deck],
                size=self.market.size,
            ),
            tracks=[_clone_track(t) for t in self.tracks],
            rng=rng,
            turn=self.turn,
            active=self.active,
            eliminated=[_clone_instance(c) for c in self.eliminated],
            target_holder=self.target_holder,
            lord_ruler=_clone_lord_ruler(self.lord_ruler),
            winner=self.winner,
            victory_reason=self.victory_reason,
            finished=self.finished,
        )
        return clone

    def player(self, pid: int) -> Player:
        return self.players[pid]

    def alive(self) -> list[Player]:
        return [p for p in self.players if not p.eliminated]

    def alive_ids(self) -> list[int]:
        return [p.id for p in self.alive()]

    def opponents(self, pid: int) -> list[Player]:
        return [p for p in self.alive() if p.id != pid]

    def all_market_cards(self) -> list[Card]:
        return [inst.card for inst in [*self.market.row, *self.market.deck]]


# --- ayudantes de clonado ----------------------------------------------------
#
# Sueltos y no métodos para que `clone` se lea de un tirón. Comparten todo lo que es
# definición de contenido (Card, Mission, Character, dicts del mazo del Lord Ruler) y
# copian todo lo que el motor muta durante la partida.


def _clone_instance(inst: CardInstance) -> CardInstance:
    copy_ = CardInstance(uid=inst.uid, card=inst.card)
    copy_.activations_used = set(inst.activations_used)
    copy_.primary_activated = inst.primary_activated
    return copy_


def _clone_player(player: Player) -> Player:
    clone = Player(id=player.id, character=player.character, health=player.health)
    clone.boxings = player.boxings
    clone.atium = player.atium
    clone.deck = [_clone_instance(c) for c in player.deck]
    clone.hand = [_clone_instance(c) for c in player.hand]
    clone.discard = [_clone_instance(c) for c in player.discard]
    clone.in_play = [_clone_instance(c) for c in player.in_play]
    clone.allies = [_clone_instance(c) for c in player.allies]
    clone.set_aside = [_clone_instance(c) for c in player.set_aside]
    clone.tokens = MetalTokens(
        state=dict(player.tokens.state),
        burn_limit=player.tokens.burn_limit,
        burns_used=player.tokens.burns_used,
    )
    clone.resources = TurnResources(
        coin=player.resources.coin,
        combat=player.resources.combat,
        mission=player.resources.mission,
    )
    clone.training = player.training
    clone.eliminated = player.eliminated
    clone.used_once_per_turn = set(player.used_once_per_turn)
    clone.metal_burn_counts = dict(player.metal_burn_counts)
    clone.permanents = dict(player.permanents)
    return clone


def _clone_track(track: MissionTrack) -> MissionTrack:
    return MissionTrack(
        mission=track.mission,               # contenido inmutable: se comparte
        positions=dict(track.positions),
        claimed=set(track.claimed),
        first_claimed=set(track.first_claimed),
        finisher=track.finisher,
        sensed=set(track.sensed),
    )


def _clone_lord_ruler(lr: LordRuler | None) -> LordRuler | None:
    if lr is None:
        return None
    return LordRuler(
        health=lr.health,
        dominance=lr.dominance,
        dominance_max=lr.dominance_max,
        # Las cartas del mazo son dicts de contenido que nadie muta: se comparten.
        deck=list(lr.deck),
        adversaries=list(lr.adversaries),
        shields={k: list(v) for k, v in lr.shields.items()},
        assigned_to=dict(lr.assigned_to),
    )
