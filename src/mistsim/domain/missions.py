"""Pistas de Misión y su estado."""
from __future__ import annotations

from dataclasses import dataclass, field

from mistsim.domain.cards import Effects

TRACK_LENGTH = 12


@dataclass(frozen=True)
class MissionReward:
    """Recompensa en una posición de la pista.

    `first_player_bonus` sólo lo cobra quien llega primero a esa posición.
    """

    position: int
    effects: Effects
    first_player_bonus: Effects | None = None


@dataclass(frozen=True)
class Mission:
    name: str
    starting_bonus: Effects | None = None
    rewards: tuple[MissionReward, ...] = ()
    top_reward: Effects | None = None
    top_reward_first_bonus: Effects | None = None
    verified: bool = False
    source: str = "homebrew"


@dataclass
class MissionTrack:
    """Estado en juego de una Misión: posición de cada jugador y recompensas cobradas."""

    mission: Mission
    positions: dict[int, int] = field(default_factory=dict)
    #: (player_id, position) ya cobrados, para que las recompensas sean de un solo uso.
    claimed: set[tuple[int, int]] = field(default_factory=set)
    #: Posiciones cuyo bonus de primer jugador ya se llevó alguien.
    first_claimed: set[int] = field(default_factory=set)
    #: Primer jugador en coronar la pista; cuenta como "el más alto" para siempre.
    finisher: int | None = None
    #: Jugadores bloqueados este turno por un efecto Sense.
    sensed: set[int] = field(default_factory=set)

    def position_of(self, player_id: int) -> int:
        return self.positions.get(player_id, 0)

    def on_track(self, player_id: int) -> bool:
        """El área de salida no cuenta como estar en la pista."""
        return self.position_of(player_id) > 0

    def completed_by_anyone(self) -> bool:
        return self.finisher is not None

    def is_highest(self, player_id: int, all_players: list[int]) -> bool:
        """Con 3+ cubos en pista, los empates arriba cuentan todos como el más alto."""
        if self.finisher is not None and self.finisher != player_id:
            return False
        if not self.on_track(player_id):
            return False
        best = max((self.position_of(p) for p in all_players if self.on_track(p)), default=0)
        return self.position_of(player_id) >= best

    def is_lowest(self, player_id: int, all_players: list[int]) -> bool:
        if not self.on_track(player_id):
            return False
        on = [p for p in all_players if self.on_track(p)]
        if len(on) < 2:
            # Un solo cubo en pista cuenta como el más alto, pero no como el más bajo.
            return False
        return self.position_of(player_id) <= min(self.position_of(p) for p in on)
