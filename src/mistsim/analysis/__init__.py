"""Minería de combos: qué pares y tríos rinden por encima de la suma de sus partes.

El paquete lee el motor y `io/` pero no los escribe. Cuatro piezas:

* `corpus`  — qué partidas jugar y cómo se convierte un asiento en una observación.
* `stats`   — el contraste de interacción y su agregación por estratos.
* `mining`  — tablas de contingencia por estrato, pares y tríos.
* `rules`   — contraste contra las 13 reglas escritas a mano de `agents/synergy.py`.
* `report`  — informe legible, con el soporte y el intervalo pegados a cada lift.
"""
from __future__ import annotations

from mistsim.analysis.corpus import CorpusSpec, Observation, generate, read_observations
from mistsim.analysis.mining import (
    Calibration,
    ConfounderCheck,
    Index,
    PairResult,
    TripleResult,
    build_index,
    calibration,
    cost_correlation,
    mine_pairs,
    mine_triples,
)
from mistsim.analysis.stats import (
    Cell,
    Estimate,
    control_fdr,
    estimate_from_strata,
    wilson_interval,
)

__all__ = [
    "Calibration", "Cell", "ConfounderCheck", "CorpusSpec", "Estimate", "Index",
    "Observation", "PairResult", "TripleResult", "build_index", "calibration",
    "control_fdr", "cost_correlation", "estimate_from_strata", "generate",
    "mine_pairs", "mine_triples", "read_observations", "wilson_interval",
]
