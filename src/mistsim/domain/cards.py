"""Cartas del Mercado y del mazo inicial."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from mistsim.domain.metals import Metal

#: Un bloque de efectos tal y como viene en los datos: clave -> valor.
#: El valor es int para acumuladores (`{"combat": 3}`), True para efectos sin
#: cantidad (`{"win_game": True}`), o list[str] para `choice_of`.
Effects = dict[str, int | bool | list[str]]


class CardType(StrEnum):
    ACTION = "Action"
    ALLY = "Ally"
    TRAINING = "Training"   # mazo inicial
    FUNDING = "Funding"     # mazo inicial


@dataclass(frozen=True)
class Ability:
    """Una de las dos habilidades de una carta.

    `extra_burns` es el número impreso en la cabecera de la secundaria ("+2 BRASS" -> 2):
    quemas **adicionales** del mismo metal, además de la que activó la primaria.
    En la primaria siempre es 0.
    """

    #: None = la carta no exige quemar metal (las de Financiación).
    metal: Metal | None
    effects: Effects
    extra_burns: int = 0


@dataclass(frozen=True)
class Card:
    name: str
    type: CardType
    cost: int
    metal_pair: tuple[Metal, ...] = ()
    primary: Ability | None = None
    secondary: Ability | None = None
    #: Bonus que sólo se aplica al jugar la carta **de lado como metal**.
    savant: Effects | None = None
    #: Efecto jugable fuera de tu turno (Cloud / Sense).
    off_turn: Effects | None = None
    #: Efecto permanente mientras el Aliado está en juego.
    ongoing: str | None = None
    defense: int | None = None
    copies: int = 1
    card_number: int | None = None

    @property
    def is_ally(self) -> bool:
        return self.type is CardType.ALLY

    @property
    def is_defender(self) -> bool:
        return self.ongoing == "defender"

    def playable_as_metal(self) -> tuple[Metal, ...]:
        """Metales como los que puede jugarse de lado.

        Los Aliados nunca sirven de metal ni para refrescar (FAQ), así que devuelven ().
        """
        return () if self.is_ally else self.metal_pair


@dataclass
class CardInstance:
    """Una copia física concreta de una carta.

    Las cartas se mueven entre zonas y hay nombres con dos copias, así que la identidad
    la da `uid`, no el nombre.
    """

    uid: int
    card: Card
    #: Aliados: activaciones ya gastadas este turno, por vía ("burn" / "riot").
    activations_used: set[str] = field(default_factory=set)
    #: Habilidad primaria activada este turno (requisito para la secundaria).
    primary_activated: bool = False

    @property
    def name(self) -> str:
        return self.card.name

    def reset_turn(self) -> None:
        self.activations_used.clear()
        self.primary_activated = False
