"""`mistsim batch` — juega N partidas y resume los resultados."""
from __future__ import annotations

import argparse
import collections
import random

from mistsim.cli.common import add_game_args, config_from, resolve_strategies
from mistsim.io import serial
from mistsim.sim.batch import BatchSpec, run_batch


def cmd_batch(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    strategies = resolve_strategies(args.strategy, args.players, rng)
    config = config_from(args)

    spec = BatchSpec(strategies=tuple(strategies), config=config,
                     base_seed=args.seed or 0)
    # Sin --save no hace falta el log completo: las métricas por jugador salen igual.
    results = run_batch(spec, args.games, workers=args.workers,
                        collect_log=bool(args.save))

    wins: collections.Counter[str] = collections.Counter()
    reasons: collections.Counter[str] = collections.Counter()
    turns_total = 0
    saved = []

    for result in results:
        reasons[result.reason] += 1
        turns_total += result.turns
        wins[strategies[result.winner]] += 1 if result.winner is not None else 0
        if result.winner is None:
            wins["<sin ganador>"] += 1
        if args.save:
            saved.append(result)

    print(f"{args.games} partidas · {args.players} jugadores · {config.mode}")
    print(f"Duración media: {turns_total / args.games:.1f} turnos\n")

    print("Victorias por estrategia:")
    seats = collections.Counter(strategies)
    for name, won in wins.most_common():
        count = seats.get(name, 0)
        # Con la misma estrategia en varios asientos, el reparto justo es 1/asientos.
        expected = f" (esperado {100 * count / args.players:.0f}%)" if count else ""
        print(f"  {name:20} {won:5}  {100 * won / args.games:5.1f}%{expected}")

    print("\nCómo terminan:")
    for reason, count in reasons.most_common():
        print(f"  {reason:26} {count:5}  {100 * count / args.games:5.1f}%")

    if args.save:
        written = serial.write_corpus(args.save, saved, include_log=True)
        print(f"\nCorpus escrito en {args.save} ({written} partidas)")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("batch", help="juega N partidas y resume los resultados")
    add_game_args(parser)
    parser.add_argument("-n", "--games", type=int, default=100)
    parser.add_argument("-w", "--workers", type=int, default=0,
                        help="procesos en paralelo; 0 = todos los núcleos, 1 = sin paralelizar")
    parser.add_argument("--save", metavar="RUTA.jsonl",
                        help="guarda las partidas como corpus JSONL")
    parser.set_defaults(func=cmd_batch)
