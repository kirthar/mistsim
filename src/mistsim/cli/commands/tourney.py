"""`mistsim tourney` — liguilla de todos los arquetipos contra todos."""
from __future__ import annotations

import argparse

from mistsim.agents import archetypes
from mistsim.domain.state import GameConfig
from mistsim.sim.batch import BatchSpec, run_batch


def cmd_tourney(args: argparse.Namespace) -> int:
    names = args.strategy or archetypes.names()
    config = GameConfig(num_players=2, max_turns=args.turns)
    record: dict[str, list[int]] = {n: [0, 0] for n in names}  # [ganadas, jugadas]

    for i, first in enumerate(names):
        for second in names[i + 1:]:
            # Alternar quién empieza: el orden de turno reparte bonus de salud.
            for order in ((first, second), (second, first)):
                spec = BatchSpec(strategies=order, config=config,
                                 base_seed=args.seed or 0)
                half = max(1, args.games // 2)
                for result in run_batch(spec, half, workers=args.workers,
                                        collect_log=False):
                    for name in order:
                        record[name][1] += 1
                    if result.winner is not None:
                        record[order[result.winner]][0] += 1

    print(f"Liguilla · {args.games} partidas por emparejamiento · "
          f"{len(names)} arquetipos\n")
    print(f"{'estrategia':22} {'winrate':>8}  {'V':>5}/{'J':<5}")
    for name, (won, played) in sorted(record.items(),
                                      key=lambda kv: -kv[1][0] / max(1, kv[1][1])):
        rate = 100 * won / played if played else 0
        print(f"{name:22} {rate:7.1f}%  {won:5}/{played:<5}")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "tourney", help="liguilla de todos los arquetipos contra todos")
    parser.add_argument("-n", "--games", type=int, default=20)
    parser.add_argument("-t", "--turns", type=int, default=60)
    parser.add_argument("-s", "--seed", type=int, default=None)
    parser.add_argument("-w", "--workers", type=int, default=0)
    parser.add_argument("--strategy", nargs="*", metavar="NOMBRE")
    parser.set_defaults(func=cmd_tourney)
