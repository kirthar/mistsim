"""Subcomandos del CLI, descubiertos automáticamente.

Para añadir uno: crea `cli/commands/<nombre>.py` con

    def register(subparsers) -> None:
        parser = subparsers.add_parser("<nombre>", help="...")
        parser.set_defaults(func=cmd_<nombre>)

y ya está. **No hay que tocar `main.py`**, que es justo el punto: cuatro líneas de
trabajo en paralelo pueden añadir su comando sin pisarse en un fichero común.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator
from types import ModuleType


def discover() -> Iterator[ModuleType]:
    """Todos los módulos de comando, en orden alfabético estable."""
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(module, "register"):
            yield module
