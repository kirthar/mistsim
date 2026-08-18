"""Piezas que comparten los subcomandos.

Vive aquí y no en `main.py` para que un subcomando nuevo no tenga que tocar el punto de
entrada. Ver `cli/commands/__init__.py` para el contrato de un comando.
"""
from __future__ import annotations

import argparse
import random
import sys

from mistsim.agents import archetypes
from mistsim.agents.utility import UtilityAgent
from mistsim.content.loader import Content
from mistsim.domain.state import GameConfig, Mode


def add_game_args(parser: argparse.ArgumentParser) -> None:
    """Opciones comunes a todo lo que juega partidas."""
    parser.add_argument("-p", "--players", type=int, default=2, choices=range(1, 5))
    parser.add_argument("-t", "--turns", type=int, default=60, help="tope de turnos")
    parser.add_argument("-s", "--seed", type=int, default=None)
    parser.add_argument("--coop", action="store_true", help="modo cooperativo")
    parser.add_argument(
        "--strategy", nargs="*", metavar="NOMBRE",
        help=f"una por jugador. Disponibles: {', '.join(archetypes.names())}")


def config_from(args: argparse.Namespace) -> GameConfig:
    return GameConfig(
        mode=Mode.COOP if getattr(args, "coop", False) else Mode.PVP,
        num_players=args.players,
        max_turns=args.turns,
    )


def agents(names: list[str], seed: int) -> list[UtilityAgent]:
    return [UtilityAgent(archetypes.get(n), seed=seed + i) for i, n in enumerate(names)]


def resolve_strategies(raw: list[str] | None, players: int,
                       rng: random.Random) -> list[str]:
    if not raw:
        return [rng.choice(archetypes.names()) for _ in range(players)]
    if len(raw) == 1:
        return raw * players
    if len(raw) != players:
        raise SystemExit(f"se dieron {len(raw)} estrategias para {players} jugadores")
    return raw


def warn_homebrew(content: Content, config: GameConfig) -> None:
    """Avisa por stderr si la partida descansa en datos inventados."""
    gaps = [k for k, ok in content.provenance.items() if not ok]
    if config.mode is not Mode.COOP:
        gaps = [g for g in gaps if g != "lord_ruler"]
    if gaps:
        print(f"AVISO: esta partida usa datos homebrew ({', '.join(gaps)}); "
              f"no son valores del juego real.", file=sys.stderr)
