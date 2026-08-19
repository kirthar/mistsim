"""Hueco para el ranking de combos de la línea de minería estadística (`analysis/**`).

Ese stream corre en paralelo y no hay contrato congelado con él todavía, así que esto
consume un FICHERO, no su código: si no existe o no tiene la forma esperada, el
explorador de cartas se genera igual y sin esa sección. No hay que esperar a que exista.

Formato esperado (JSON), tolerante:

    {"combos": [{"cards": ["Dominate", "Charm"], "lift": 1.8, "support": 0.12,
                 "count": 34, "note": "texto libre opcional"}, ...]}

o directamente una lista al nivel superior. Cada entrada necesita `cards` (>= 2
nombres de carta) y, si la trae, un valor numérico en alguno de `lift`, `score`,
`value` o `support` — es lo que se usa para ordenar y para el badge de la tarjeta.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Campos en los que se busca, en orden de preferencia, el número a mostrar/ordenar.
_SCORE_FIELDS = ("lift", "score", "value", "support")


def load_combos(path: str | Path | None) -> list[dict[str, Any]] | None:
    """Carga el ranking de combos si existe y tiene forma reconocible.

    Devuelve `None` (nunca lanza) si `path` es `None`, el fichero no existe, o el JSON
    no trae nada usable — el explorador de cartas lo trata como "no disponible aún".
    """
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("no se pudo leer el ranking de combos en %s: %s", p, exc)
        return None

    items = raw.get("combos") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        logger.warning("el ranking de combos en %s no tiene la forma esperada", p)
        return None

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cards = item.get("cards")
        if not isinstance(cards, list) or len(cards) < 2:
            continue
        cards = [str(c) for c in cards]
        field = next((f for f in _SCORE_FIELDS if isinstance(item.get(f), int | float)), None)
        score = item[field] if field is not None else None
        out.append({
            "cards": cards, "score": score, "score_field": field,
            "note": item.get("note") if isinstance(item.get("note"), str) else None,
            "extra": {k: v for k, v in item.items()
                     if k not in ("cards", "note", *_SCORE_FIELDS)},
        })

    if not out:
        return None
    out.sort(key=lambda c: c["score"] if c["score"] is not None else float("-inf"), reverse=True)
    return out
