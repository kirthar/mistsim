"""`mistsim validate` — comprueba los datos e informa de su procedencia."""
from __future__ import annotations

import argparse
import sys

from mistsim.agents import archetypes
from mistsim.content.loader import ContentError, load_content


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        content = load_content()
    except ContentError as exc:
        print(f"CONTENIDO INVÁLIDO: {exc}", file=sys.stderr)
        return 1

    print("Contenido válido.\n")
    print(f"  Mercado           {len(content.market)} nombres, "
          f"{sum(c.copies for c in content.market)} cartas físicas")
    print(f"  Personajes        {len(content.characters)} "
          f"({', '.join(c.id for c in content.characters)})")
    print(f"  Misiones          {len(content.missions)}")
    print(f"  Lord Ruler        {len(content.lord_ruler)} cartas")
    print(f"  Arquetipos        {len(archetypes.names())}")

    print("\nProcedencia de los datos:")
    for source, verified in content.provenance.items():
        mark = "verificado" if verified else "HOMEBREW — valores inventados"
        print(f"  {source:18} {mark}")

    unverified = [k for k, v in content.provenance.items() if not v]
    if unverified:
        print("\nLo que falta por fotografiar para que la simulación sea fiel:")
        if "missions" in unverified:
            print("  · las 8 cartas de Misión (valores numéricos de cada pista)")
        if "lord_ruler" in unverified:
            print("  · las 36 cartas del Lord Ruler (Adversarios y Edictos)")
        print("\n  Hasta entonces, los resultados del modo Coop no reflejan el")
        print("  juego real. El PvP sí: sus datos están todos verificados.")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "validate", help="comprueba los datos e informa de su procedencia")
    parser.set_defaults(func=cmd_validate)
