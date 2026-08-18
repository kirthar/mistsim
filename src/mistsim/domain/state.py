"""Estado completo de una partida."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from mistsim.domain.cards import Card, CardInstance
from mistsim.domain.missions import MissionTrack
from mistsim.domain.player import Player


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
        """Repone la fila desde el mazo. El Mercado puede quedar corto si el mazo se agota."""
        added = []
        while len(self.row) < self.size and self.deck:
            added.append(self.deck.pop())
        self.row.extend(added)
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
