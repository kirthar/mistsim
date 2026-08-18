"""`mistsim report` — genera el reproductor de partida y el explorador de cartas."""
from __future__ import annotations

import argparse
import sys

from mistsim.content.loader import load_content
from mistsim.report.web.build import DEFAULT_MAX_GAMES, build_report


def cmd_report(args: argparse.Namespace) -> int:
    content = load_content()

    if args.corpus is None:
        print("AVISO: sin --corpus, el reproductor de partida se genera vacío "
              "(el explorador de cartas no lo necesita).", file=sys.stderr)

    gaps = [k for k, ok in content.provenance.items() if not ok]
    if gaps:
        print(f"AVISO: datos homebrew en juego ({', '.join(gaps)}); la página lo avisa "
              "también para quien la abra.", file=sys.stderr)

    paths = build_report(
        args.corpus, args.out, max_games=args.max_games,
        combos_path=args.combos, content=content,
    )

    print(f"Reproductor de partida: {paths.player_page}  ({paths.games_shown} partidas"
          f"{', hay más en el corpus' if paths.games_truncated else ''})")
    print(f"Explorador de cartas:   {paths.cards_page}")
    print(f"Imágenes copiadas en:   {paths.images_dir}")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "report", help="genera el reproductor de partida y el explorador de cartas (HTML)")
    parser.add_argument("--corpus", metavar="RUTA.jsonl",
                        help="corpus JSONL con log completo (ver 'mistsim batch --save')")
    parser.add_argument("--out", default="informe", metavar="DIR",
                        help="carpeta de salida (por defecto ./informe)")
    parser.add_argument("--max-games", type=int, default=DEFAULT_MAX_GAMES,
                        help=f"tope de partidas embebidas en el reproductor "
                             f"(por defecto {DEFAULT_MAX_GAMES})")
    parser.add_argument("--combos", metavar="RUTA.json",
                        help="ranking de combos de la minería estadística, si existe "
                             "(opcional: la página funciona igual sin él)")
    parser.set_defaults(func=cmd_report)
