"""`mistsim combos` — mina pares y tríos de cartas sobre un corpus de partidas.

Genera el corpus si no existe (o si se pide `--regenerate`) y lo reutiliza si ya está:
5 000 partidas cuestan minutos y el análisis segundos, así que iterar sobre los
parámetros estadísticos no debería volver a jugarlas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mistsim.analysis import corpus as corpus_mod
from mistsim.analysis import mining, report, rules
from mistsim.analysis.corpus import CorpusSpec
from mistsim.domain.state import Mode

#: Bajo `out/`, que ya está en .gitignore: un corpus de 5 000 partidas ocupa 6 MB y no
#: tiene por qué acabar en el repositorio.
DEFAULT_CORPUS = Path("out/combos-corpus.jsonl")


def cmd_combos(args: argparse.Namespace) -> int:
    path = Path(args.corpus)
    spec = CorpusSpec(
        games=args.games,
        players=tuple(args.players),
        mode=Mode.COOP if args.coop else Mode.PVP,
        max_turns=args.turns,
        seed=args.seed or 0,
    )

    if args.regenerate or not path.exists():
        print(f"Generando corpus: {spec.games} partidas a "
              f"{'/'.join(str(p) for p in spec.players)} jugadores…", file=sys.stderr)
        written = corpus_mod.generate(path, spec, workers=args.workers)
        print(f"Corpus escrito en {path} ({written} partidas)", file=sys.stderr)
    else:
        print(f"Reutilizando corpus existente {path} (--regenerate para rehacerlo)",
              file=sys.stderr)

    content_costs = corpus_mod.card_costs()
    # Se materializan: la réplica en mitades necesita recorrerlas más de una vez, y
    # 15 000 observaciones son 3 MB, no un problema.
    observations = list(corpus_mod.read_observations(path))

    # Cuántos tramos de tamaño de mazo hacen falta depende del tamaño del corpus, así
    # que por defecto se ajustan mirando el diagnóstico nulo en vez de fijarlos a ojo.
    trace: list = []
    buckets = args.size_buckets
    if buckets is None and not args.no_size_control:
        buckets, trace = mining.tune_size_buckets(
            observations, min_support=args.min_support, min_cell=args.min_cell)
        print(f"Tramos de tamaño de mazo autoajustados a {buckets} "
              f"(--size-buckets N para fijarlos)", file=sys.stderr)
    elif buckets is None:
        buckets = mining.DEFAULT_SIZE_BUCKETS

    index = mining.build_index(observations, size_control=not args.no_size_control,
                               size_buckets=buckets)
    if not index.observations:
        print("El corpus está vacío.", file=sys.stderr)
        return 1

    # El desglose de un par no necesita minar los 2 080; se atiende y se sale.
    if args.explain:
        print(report.explain_section(index, args.explain[0], args.explain[1],
                                     args.min_cell))
        return 0

    pairs = mining.mine_pairs(index, min_support=args.min_support,
                              min_cell=args.min_cell, costs=content_costs)
    rules.annotate(pairs)
    triples = []
    if not args.no_triples:
        triples = mining.mine_triples(index, pairs, min_support=args.min_support_triple,
                                      min_cell=args.min_cell, costs=content_costs)
        rules.annotate(triples)
    checks = rules.check_rules(pairs, min_support=args.min_support)
    patterns = mining.pattern_summary(pairs, rules.mechanical_groups())

    replication = None
    if not args.no_replication:
        robustos = [p for p in pairs if p.synergy.robust(min_support=args.min_support)]
        replication = mining.replicate(
            observations, robustos[:args.top],
            size_control=not args.no_size_control, size_buckets=buckets,
            min_support=max(4, args.min_support // 2), min_cell=args.min_cell)

    text = report.render(index, pairs, triples, checks, corpus_path=str(path),
                         size_control=not args.no_size_control, top=args.top,
                         min_support=args.min_support, replication=replication,
                         computed_triples=not args.no_triples, tuning=trace,
                         patterns=patterns)
    print(text)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        volcado = _as_json(index, pairs, triples, checks, replication, patterns)
        Path(args.json).write_text(
            json.dumps(volcado, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nRanking completo en {args.json}", file=sys.stderr)
    return 0


def _as_json(index, pairs, triples, checks, rep=None, patterns=()) -> dict:
    """Volcado completo, para el visor web y para rehacer gráficas sin re-minar."""
    def estimate(e):
        return {"lift": e.lift, "ci_low": e.ci_low, "ci_high": e.ci_high,
                "strata_used": e.strata_used, "support": e.support,
                "significant": e.significant, "robust": e.robust(),
                "p_value": e.p_value, "q_value": e.q_value}
    cal = mining.calibration(pairs)
    return {
        "calibration": {"measured": cal.measured, "median_lift": cal.median_lift,
                        "significant_fraction": cal.significant_fraction,
                        "discoveries": cal.discoveries,
                        "well_centred": cal.well_centred},
        "observations": index.observations,
        "wins": index.wins,
        "size_edges": index.size_edges,
        "strata": len(index.strata),
        "pairs": [{"cards": list(p.cards), "support": p.support, "cost": p.cost,
                   "naive_lift": p.naive, "wins_both": p.wins_both, "n_both": p.n_both,
                   "rules": list(p.rules), **estimate(p.synergy)} for p in pairs],
        "triples": [{"cards": list(t.cards), "support": t.support, "cost": t.cost,
                     "weakest_third": t.weakest_third, "rules": list(t.rules),
                     **estimate(t.synergy)} for t in triples],
        "replication": ({"checked": rep.checked, "same_direction": rep.same_direction,
                         "rank_agreement": rep.rank_agreement} if rep else None),
        "patterns": [{"name": p.name, "pairs": p.pairs, "median_lift": p.median_lift,
                      "fraction_above": p.fraction_above, "sign_p": p.sign_p}
                     for p in patterns],
        "rule_checks": [{"rule": c.rule, "measured": c.measured, "confirmed": c.confirmed,
                         "contradicted": c.contradicted, "median_lift": c.median_lift,
                         "best": list(c.best) if c.best else None} for c in checks],
    }


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "combos", help="mina pares y tríos de cartas sinérgicos sobre miles de partidas")
    parser.add_argument("-n", "--games", type=int, default=5000,
                        help="partidas del corpus (por defecto 5000)")
    parser.add_argument("-p", "--players", type=int, nargs="+", default=[2, 3, 4],
                        help="números de jugadores a mezclar; cada uno es un estrato")
    parser.add_argument("-t", "--turns", type=int, default=60, help="tope de turnos")
    parser.add_argument("-s", "--seed", type=int, default=0)
    parser.add_argument("--coop", action="store_true", help="corpus en modo cooperativo")
    parser.add_argument("-w", "--workers", type=int, default=2,
                        help="procesos en paralelo; 0 = todos los núcleos")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), metavar="RUTA.jsonl")
    parser.add_argument("--regenerate", action="store_true",
                        help="rehace el corpus aunque el fichero ya exista")
    parser.add_argument("--min-support", type=int, default=30,
                        help="co-ocurrencias mínimas de un par para entrar en el ranking")
    parser.add_argument("--min-support-triple", type=int, default=25)
    parser.add_argument("--min-cell", type=int, default=5,
                        help="observaciones mínimas en CADA celda 2×2 para que un "
                             "estrato aporte a la estimación")
    parser.add_argument("--size-buckets", type=int, default=None,
                        help="tramos de tamaño de mazo para controlar el efecto dinero. "
                             "Por defecto se autoajustan hasta que la mediana del lift "
                             "vuelve a 1; con pocos tramos el de arriba mezcla mazos de "
                             "8 y de 60 cartas y el control se queda corto")
    parser.add_argument("--no-size-control", action="store_true",
                        help="no estratificar por tamaño de mazo (para ver cuánto cambia)")
    parser.add_argument("--no-triples", action="store_true")
    parser.add_argument("--no-replication", action="store_true",
                        help="no rehacer el análisis en dos mitades del corpus")
    parser.add_argument("--top", type=int, default=25, help="filas por sección")
    parser.add_argument("--explain", nargs=2, metavar=("CARTA", "CARTA"),
                        help="desglosa un par estrato a estrato en vez de minar todo")
    parser.add_argument("--json", metavar="RUTA.json", help="vuelca el ranking completo")
    parser.set_defaults(func=cmd_combos)
