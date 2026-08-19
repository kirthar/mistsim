"""Conversión entre `StrategyProfile` y el vector de genoma del algoritmo genético.

El genoma tiene 34 componentes, en un orden fijo:

    5  weights          (combat, mission, coin, draw, heal)
    9  metal_affinity   (los 9 valores de `Metal`, en su orden de declaración)
    16 tag_affinity     (los 16 valores de `Tag`, en su orden de declaración)
    4  escalares        (synergy_weight, cost_bias, mission_focus, panic_health)

El orden de `Metal` y `Tag` es estable entre ejecuciones porque son `StrEnum`: Python
conserva el orden de declaración al iterar la clase, así que no hace falta ordenar a
mano ni guardar el orden aparte — el propio código de los enums es la fuente de verdad.
"""
from __future__ import annotations

from collections.abc import Sequence

from mistsim.agents.profile import StrategyProfile
from mistsim.agents.tags import Tag
from mistsim.domain.metals import Metal

WEIGHT_KEYS: tuple[str, ...] = ("combat", "mission", "coin", "draw", "heal")
METAL_KEYS: tuple[Metal, ...] = tuple(Metal)
TAG_KEYS: tuple[Tag, ...] = tuple(Tag)
#: Los cuatro escalares sueltos de StrategyProfile, en el orden en que van al genoma.
SCALAR_KEYS: tuple[str, ...] = ("synergy_weight", "cost_bias", "mission_focus", "panic_health")

DIMS = len(WEIGHT_KEYS) + len(METAL_KEYS) + len(TAG_KEYS) + len(SCALAR_KEYS)

#: Rango de los multiplicadores (weights / metal_affinity / tag_affinity). Centrado en
#: el 1.0 neutral y calcado del rango que ya usan los 11 arquetipos escritos a mano
#: (ninguno pasa de 2.2); se deja margen para que el GA explore algo más allá sin que
#: un gen se dispare a valores absurdos.
_MULT_BOUNDS = (0.1, 3.0)

#: (mínimo, máximo) por posición del vector, mismo orden que el genoma.
BOUNDS: tuple[tuple[float, float], ...] = (
    (_MULT_BOUNDS,) * len(WEIGHT_KEYS)
    + (_MULT_BOUNDS,) * len(METAL_KEYS)
    + (_MULT_BOUNDS,) * len(TAG_KEYS)
    + ((0.0, 3.0), (-1.0, 1.0), (0.0, 1.0), (1.0, 40.0))  # panic_health: 0-40 de vida
)
assert len(BOUNDS) == DIMS


def profile_to_vector(profile: StrategyProfile) -> list[float]:
    """Aplana un perfil a su genoma. Las claves ausentes en los dicts valen 1.0 (neutral),
    igual que hace `StrategyProfile.card_value` al leerlas con `.get(key, 1.0)`.
    """
    out: list[float] = []
    out.extend(profile.weights.get(k, 1.0) for k in WEIGHT_KEYS)
    out.extend(profile.metal_affinity.get(m, 1.0) for m in METAL_KEYS)
    out.extend(profile.tag_affinity.get(t, 1.0) for t in TAG_KEYS)
    out.extend([
        profile.synergy_weight, profile.cost_bias, profile.mission_focus,
        float(profile.panic_health),
    ])
    return out


def vector_to_profile(
    vector: Sequence[float], *, name: str, description: str = "",
) -> StrategyProfile:
    """Reconstruye un perfil completo a partir de un genoma de `DIMS` componentes.

    A diferencia de los 11 arquetipos escritos a mano (que sólo listan las claves que
    les importan), el perfil resultante trae los tres dicts completos: cada clave que
    valga 1.0 es indistinguible en comportamiento de una clave ausente, así que no hay
    pérdida de expresividad, sólo de brevedad.
    """
    if len(vector) != DIMS:
        raise ValueError(f"el genoma tiene {DIMS} componentes, se dieron {len(vector)}")

    i = 0
    weights = {k: float(vector[i + idx]) for idx, k in enumerate(WEIGHT_KEYS)}
    i += len(WEIGHT_KEYS)
    metal_affinity = {m: float(vector[i + idx]) for idx, m in enumerate(METAL_KEYS)}
    i += len(METAL_KEYS)
    tag_affinity = {t: float(vector[i + idx]) for idx, t in enumerate(TAG_KEYS)}
    i += len(TAG_KEYS)
    synergy_weight, cost_bias, mission_focus, panic_health = vector[i:i + len(SCALAR_KEYS)]

    return StrategyProfile(
        name=name, description=description,
        weights=weights, metal_affinity=metal_affinity, tag_affinity=tag_affinity,
        synergy_weight=float(synergy_weight), cost_bias=float(cost_bias),
        mission_focus=float(mission_focus), panic_health=round(panic_health),
    )


def clamp_vector(vector: Sequence[float]) -> list[float]:
    """Recorta cada gen a su rango en `BOUNDS`, tras mutación o cruce."""
    return [min(hi, max(lo, v)) for v, (lo, hi) in zip(vector, BOUNDS, strict=True)]
