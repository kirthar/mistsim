"""Estado de un jugador: mazo, zonas, salud, metales y pista de Entrenamiento."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from mistsim.domain.cards import CardInstance
from mistsim.domain.metals import Metal, MetalTokens

MAX_HEALTH = 40
HAND_SIZE = 5
TRAINING_STEPS = 8


@dataclass
class Character:
    id: str
    name: str
    title: str
    signature_metal: str
    level_1_effects: dict
    promo: bool = False


@dataclass
class TurnResources:
    """Acumuladores que se reinician cada turno. Nada de esto se arrastra al siguiente."""

    coin: int = 0
    combat: int = 0
    mission: int = 0

    def reset(self) -> None:
        self.coin = self.combat = self.mission = 0


@dataclass
class Player:
    id: int
    character: Character
    health: int = 36
    boxings: int = 0
    atium: int = 0

    deck: list[CardInstance] = field(default_factory=list)
    hand: list[CardInstance] = field(default_factory=list)
    discard: list[CardInstance] = field(default_factory=list)
    in_play: list[CardInstance] = field(default_factory=list)
    allies: list[CardInstance] = field(default_factory=list)
    #: Apartadas por Keeper; se roban al inicio del turno siguiente.
    set_aside: list[CardInstance] = field(default_factory=list)

    tokens: MetalTokens = field(default_factory=MetalTokens)
    resources: TurnResources = field(default_factory=TurnResources)
    training: int = 0
    eliminated: bool = False

    #: Efectos de un solo uso por turno ya gastados (habilidad de personaje, nivel II…).
    used_once_per_turn: set[str] = field(default_factory=set)

    #: Veces que se ha activado cada metal este turno, contando fichas quemadas,
    #: fichas flareadas y cartas jugadas de lado. Es lo que decide si una habilidad
    #: secundaria "+N METAL" ya tiene sus quemas, y qué Aliados pueden activarse.
    metal_burn_counts: dict[Metal, int] = field(default_factory=dict)

    #: Efectos permanentes ganados de recompensas de Misión, p.ej. {"coin": 2}.
    permanents: dict[str, int] = field(default_factory=dict)

    # ---- movimiento de cartas -------------------------------------------------

    def draw(self, n: int, rng: random.Random) -> list[CardInstance]:
        """Roba n cartas, barajando el descarte cuando el mazo se agota."""
        drawn: list[CardInstance] = []
        for _ in range(n):
            if not self.deck:
                if not self.discard:
                    break
                self.deck = self.discard
                self.discard = []
                rng.shuffle(self.deck)
            drawn.append(self.deck.pop())
        self.hand.extend(drawn)
        return drawn

    def cleanup(self, rng: random.Random) -> list[CardInstance]:
        """Fin de turno: todo lo jugado y la mano sobrante al descarte. Los Aliados quedan."""
        self.discard.extend(self.in_play)
        self.discard.extend(self.hand)
        self.in_play = []
        self.hand = []
        for inst in self.allies:
            inst.reset_turn()
        return self.discard

    def all_cards(self) -> list[CardInstance]:
        """Todas las cartas del jugador. Usado por los invariantes de conservación."""
        return [*self.deck, *self.hand, *self.discard, *self.in_play, *self.allies,
                *self.set_aside]

    # ---- estado ---------------------------------------------------------------

    def heal(self, amount: int) -> int:
        before = self.health
        self.health = min(MAX_HEALTH, self.health + amount)
        return self.health - before

    def take_damage(self, amount: int) -> None:
        self.health -= amount
        if self.health <= 0:
            self.health = 0
            self.eliminated = True

    def has_defender(self) -> bool:
        return any(a.card.is_defender for a in self.allies)

    def advance_training(self, steps: int = 1) -> int:
        before = self.training
        self.training = min(TRAINING_STEPS, self.training + steps)
        return self.training - before

    @property
    def metals_active_this_turn(self) -> set[Metal]:
        return {m for m, n in self.metal_burn_counts.items() if n > 0}

    def note_metal(self, metal: Metal) -> int:
        """Registra una activación de ese metal y devuelve el total del turno."""
        self.metal_burn_counts[metal] = self.metal_burn_counts.get(metal, 0) + 1
        return self.metal_burn_counts[metal]

    def start_turn(self) -> None:
        self.tokens.start_turn()
        self.resources.reset()
        self.used_once_per_turn.clear()
        self.metal_burn_counts.clear()
        for inst in self.allies:
            inst.reset_turn()
