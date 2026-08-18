"""`mistsim play` — juega una partida y muestra el log turno a turno."""
from __future__ import annotations

import argparse
import random

from mistsim.cli.common import add_game_args, agents, config_from, resolve_strategies, warn_homebrew
from mistsim.content.loader import load_content
from mistsim.domain.state import Mode
from mistsim.engine.game import GameEngine
from mistsim.report import log as report_log


def cmd_play(args: argparse.Namespace) -> int:
    content = load_content()
    rng = random.Random(args.seed)
    strategies = resolve_strategies(args.strategy, args.players, rng)
    config = config_from(args)

    engine = GameEngine(content=content, config=config, seed=args.seed)
    result = engine.run(agents(strategies, args.seed or 0), characters=args.characters)

    print("Estrategias: " + ", ".join(f"P{i}={s}" for i, s in enumerate(strategies)))
    if config.mode is Mode.COOP or not content.provenance["missions"]:
        warn_homebrew(content, config)
    print()
    print(report_log.render(result.log, verbose=args.verbose))
    print(report_log.summary(result))
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "play", help="juega una partida y muestra el log turno a turno")
    add_game_args(parser)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--characters", nargs="*", metavar="ID")
    parser.set_defaults(func=cmd_play)
