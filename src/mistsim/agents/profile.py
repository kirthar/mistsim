"""Perfiles de estrategia: pesos, no guiones.

Una estrategia es un puñado de números, no un árbol de decisiones escrito a mano. Eso
tiene dos consecuencias buenas: los arquetipos se leen de un vistazo y se comparan entre
sí, y el espacio de pesos es exactamente el que recorrerá el optimizador de mazos de la
2ª entrega.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mistsim.agents.synergy import synergy_score
from mistsim.agents.tags import Tag, output_value, tags_for
from mistsim.domain.cards import Card
from mistsim.domain.metals import Metal

#: Valor por punto de cada recurso, en una escala común, antes de aplicar los pesos
#: de la estrategia. Una moneda vale menos que un daño porque es de un solo turno.
BASE_RESOURCE_VALUE = {
    "combat": 1.0,
    "mission": 1.2,
    "coin": 0.8,
    "draw": 1.5,
    "heal": 0.5,
}


@dataclass
class StrategyProfile:
    """Qué le importa a una estrategia."""

    name: str
    description: str

    #: Multiplicador por recurso. 1.0 = neutral.
    weights: dict[str, float] = field(default_factory=dict)
    #: Multiplicador por metal, para inclinar las compras hacia un motor concreto.
    metal_affinity: dict[Metal, float] = field(default_factory=dict)
    #: Multiplicador por etiqueta, para valorar papeles (adelgazar, defender…).
    tag_affinity: dict[Tag, float] = field(default_factory=dict)

    #: Cuánto pesa la sinergia frente al valor bruto de la carta.
    synergy_weight: float = 1.0
    #: Preferencia por gastar en cartas caras (>0) o por curva baja (<0).
    cost_bias: float = 0.0
    #: Reparto del esfuerzo entre ganar por Misiones y ganar por combate.
    mission_focus: float = 0.5
    #: Umbral de salud por debajo del cual la estrategia prioriza curarse y defender.
    panic_health: int = 12

    def resource_value(self, resource: str) -> float:
        return BASE_RESOURCE_VALUE.get(resource, 1.0) * self.weights.get(resource, 1.0)

    def card_value(self, card: Card, owned: list[Card]) -> float:
        """Puntuación de compra: valor bruto + afinidades + sinergia con lo que ya tienes."""
        value = sum(self.resource_value(res) * amount
                    for res, amount in output_value(card).items())

        card_tags = tags_for(card)
        for tag in card_tags:
            value *= self.tag_affinity.get(tag, 1.0)

        if card.metal_pair:
            affinity = max(self.metal_affinity.get(m, 1.0) for m in card.metal_pair)
            value *= affinity

        # Un Aliado se queda en mesa y produce cada turno, así que vale más que su
        # texto suelto; pero también es un blanco que hay que defender.
        if card.is_ally:
            value *= 1.6

        value += self.synergy_weight * synergy_score(card, owned)
        value += self.cost_bias * card.cost

        # Una carta que cuesta mucho y da poco lastra el mazo: penaliza la eficiencia.
        return value - 0.35 * card.cost

    def clone(self, **overrides) -> StrategyProfile:
        data = {
            "name": self.name, "description": self.description,
            "weights": dict(self.weights), "metal_affinity": dict(self.metal_affinity),
            "tag_affinity": dict(self.tag_affinity),
            "synergy_weight": self.synergy_weight, "cost_bias": self.cost_bias,
            "mission_focus": self.mission_focus, "panic_health": self.panic_health,
        }
        data.update(overrides)
        return StrategyProfile(**data)
