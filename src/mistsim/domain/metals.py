"""Metales, sus parejas y el estado de las fichas de un jugador."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Metal(StrEnum):
    PEWTER = "Pewter"
    TIN = "Tin"
    BRONZE = "Bronze"
    COPPER = "Copper"
    ZINC = "Zinc"
    BRASS = "Brass"
    IRON = "Iron"
    STEEL = "Steel"
    ATIUM = "Atium"

    def __str__(self) -> str:
        return self.value


#: Cada metal base se empareja con otro; una carta de un metal puede jugarse de lado
#: como cualquiera de los dos de su pareja. Atium no tiene pareja.
PAIRS: dict[Metal, Metal] = {
    Metal.PEWTER: Metal.TIN,
    Metal.TIN: Metal.PEWTER,
    Metal.BRONZE: Metal.COPPER,
    Metal.COPPER: Metal.BRONZE,
    Metal.ZINC: Metal.BRASS,
    Metal.BRASS: Metal.ZINC,
    Metal.IRON: Metal.STEEL,
    Metal.STEEL: Metal.IRON,
}

#: Los 8 metales base, en el orden del manual. Atium queda fuera: es una ficha aparte
#: de un solo uso, no una de las 8 del jugador.
BASE_METALS: tuple[Metal, ...] = (
    Metal.PEWTER, Metal.TIN, Metal.BRONZE, Metal.COPPER,
    Metal.ZINC, Metal.BRASS, Metal.IRON, Metal.STEEL,
)

KEYWORDS: dict[Metal, str] = {
    Metal.PEWTER: "Defender",
    Metal.TIN: "Sense",
    Metal.BRONZE: "Seek",
    Metal.COPPER: "Cloud",
    Metal.ZINC: "Riot",
    Metal.BRASS: "Soothe",
    Metal.IRON: "Pull",
    Metal.STEEL: "Push",
}


class TokenState(StrEnum):
    READY = "ready"      # sin usar este turno, disponible
    BURNED = "burned"    # quemada este turno
    FLARED = "flared"    # volteada a su cara oscura para saltarse el límite


@dataclass
class MetalTokens:
    """Las 8 fichas de metal de un jugador y el límite de quemas por turno.

    El límite cuenta **fichas**, no cartas: jugar una carta de lado como metal no
    consume ninguna quema (FAQ). Flarear es la vía para pasarse del límite.
    """

    state: dict[Metal, TokenState] = field(
        default_factory=lambda: {m: TokenState.READY for m in BASE_METALS}
    )
    burn_limit: int = 1
    burns_used: int = 0

    def start_turn(self) -> None:
        """Las quemas se reinician; las fichas flareadas siguen flareadas."""
        self.burns_used = 0
        for metal, st in self.state.items():
            if st is TokenState.BURNED:
                self.state[metal] = TokenState.READY

    def can_burn(self, metal: Metal) -> bool:
        return self.state.get(metal) is TokenState.READY and self.burns_used < self.burn_limit

    def burn(self, metal: Metal) -> None:
        if not self.can_burn(metal):
            raise ValueError(f"no se puede quemar {metal}")
        self.state[metal] = TokenState.BURNED
        self.burns_used += 1

    def can_flare(self, metal: Metal) -> bool:
        """Sólo se puede flarear una ficha sin usar todavía este turno (FAQ)."""
        return self.state.get(metal) is TokenState.READY

    def flare(self, metal: Metal) -> None:
        if not self.can_flare(metal):
            raise ValueError(f"no se puede flarear {metal}")
        self.state[metal] = TokenState.FLARED

    def flared(self) -> list[Metal]:
        return [m for m, st in self.state.items() if st is TokenState.FLARED]

    def refresh(self, metal: Metal) -> None:
        """Devuelve una ficha flareada a su cara normal.

        Queda como BURNED, no como READY: el FAQ es explícito en que no se puede volver
        a usar este turno aunque la hayas desflareado. Estará lista el turno siguiente.
        """
        if self.state.get(metal) is not TokenState.FLARED:
            raise ValueError(f"{metal} no está flareado")
        self.state[metal] = TokenState.BURNED
