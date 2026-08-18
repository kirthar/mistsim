"""Punto de entrada del CLI.

Deliberadamente mínimo: no conoce ningún comando concreto, sólo los descubre. Añadir un
subcomando es crear un fichero en `cli/commands/`, nunca editar éste — así varias líneas
de trabajo en paralelo no se pisan en un fichero común.
"""
from __future__ import annotations

import argparse

from mistsim.cli import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mistsim",
        description="Simulador de Mistborn: The Deckbuilding Game")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for module in commands.discover():
        module.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
