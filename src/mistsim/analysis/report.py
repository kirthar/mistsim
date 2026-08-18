"""Informe legible de la minería de combos.

El formato está pensado para que no se pueda leer un lift sin ver a la vez su soporte y
su intervalo. Un ranking sin esa columna invita a citar el primer número de la lista, y
el primer número de la lista es casi siempre el que menos evidencia tiene.
"""
from __future__ import annotations

import functools
import math
from collections.abc import Sequence

from mistsim.analysis import mining, stats
from mistsim.analysis.mining import (
    Index,
    PairResult,
    TripleResult,
    calibration,
    cost_correlation,
)
from mistsim.analysis.rules import RuleCheck, undiscovered

RULE = "─" * 78


def _rows(lines: list[str], items, render_row, empty: str) -> None:
    """Vuelca una lista de filas, o una línea explícita de "aquí no hay nada".

    Una sección vacía tiene que decirlo: si desaparece, el lector supone que no se buscó.
    """
    if items:
        lines.extend(render_row(item) for item in items)
    else:
        lines.append(empty)


def _fmt_lift(value: float) -> str:
    if not math.isfinite(value):
        return "  n/d"
    return f"{value:5.2f}"


def _fmt_q(value: float) -> str:
    if not math.isfinite(value):
        return " n/d "
    return f"{value:.3f}" if value >= 0.001 else "<.001"


def _fmt_ci(estimate) -> str:
    """n/d cuando ningún estrato tenía las cuatro celdas: no es un intervalo infinito,
    es que no hay medición."""
    if not estimate.estimated or not math.isfinite(estimate.ci_high):
        return "        n/d"
    return f"[{estimate.ci_low:4.2f}–{estimate.ci_high:5.2f}]"


def _pair_row(pair: PairResult, min_support: int = 30) -> str:
    names = f"{pair.cards[0]} + {pair.cards[1]}"
    low, high = pair.wilson()
    flag = ("✔" if pair.synergy.robust(min_support=min_support)
            else ("·" if pair.synergy.significant else " "))
    rules = ",".join(pair.rules) if pair.rules else "—"
    return (f" {flag} {names:<34.34} {_fmt_lift(pair.synergy.lift)} "
            f"{_fmt_ci(pair.synergy):<13} q={_fmt_q(pair.synergy.q_value)} "
            f"n={pair.support:<5d} "
            f"vict={100 * pair.win_rate:4.1f}% [{100 * low:4.1f}–{100 * high:4.1f}] "
            f"coste={pair.cost:<3d} {rules:.28}")


def _triple_row(triple: TripleResult) -> str:
    names = " + ".join(triple.cards)
    flag = "✔" if triple.synergy.robust(min_support=20) else (
        "·" if triple.synergy.significant else " ")
    return (f" {flag} {names:<48.48} {_fmt_lift(triple.synergy.lift)} "
            f"{_fmt_ci(triple.synergy):<13} q={_fmt_q(triple.synergy.q_value)} "
            f"n={triple.support:<4d} "
            f"corte-débil={triple.weakest_third:.18}")


def header(index: Index, corpus_path: str, size_control: bool) -> list[str]:
    strata = [s for s in index.strata if s.size]
    base = index.wins / index.observations if index.observations else 0.0
    edges = ", ".join(str(e) for e in index.size_edges) or "sin control de tamaño"
    return [
        RULE,
        "MINERÍA DE COMBOS — pares y tríos por encima de la suma de sus partes",
        RULE,
        f"Corpus            {corpus_path}",
        f"Observaciones     {index.observations} asientos · {index.wins} victorias "
        f"({100 * base:.1f}% base)",
        f"Estratos          {len(strata)} (arquetipo × jugadores × modo"
        f"{' × tamaño de mazo' if size_control else ''})",
        f"Cortes de tamaño  {edges}",
        f"Pares distintos   {len(index.pair_support)} vistos al menos una vez",
        "",
    ]


def homebrew_warning() -> list[str]:
    return [
        RULE,
        "AVISO SOBRE LOS DATOS — leer antes que cualquier número de abajo",
        RULE,
        "Las 8 cartas de Misión y las 36 del Lord Ruler son HOMEBREW: sus valores están",
        "inventados porque no hay fuente publicada. En lotes a 3 jugadores el ~84% de las",
        "partidas termina por completar las tres Misiones, así que la vía de Misión decide",
        "casi todas las partidas del corpus. Eso infla sistemáticamente a las cartas con",
        "MISSION y a los efectos que miden posición en las pistas, y desinfla al combate y",
        "a los motores lentos. Todo el ranking hereda ese sesgo: es una medida del juego",
        "TAL Y COMO ESTÁ RECONSTRUIDO, no del juego real. Cuando se fotografíen las 8",
        "cartas de Misión hay que volver a correr esto entero antes de citar nada.",
        "",
    ]


def calibration_section(pairs: Sequence[PairResult], tuning=()) -> list[str]:
    """La sección que hay que mirar antes que el ranking."""
    cal = calibration(pairs)
    veredicto = ("centrado: el ajuste por confusor parece completo"
                 if cal.well_centred else
                 "DESPLAZADO: queda confusor sin controlar y TODO el ranking está sesgado")
    return [
        RULE,
        "CALIBRACIÓN — mirar esto antes que el ranking",
        RULE,
        "La mayoría de los 2 080 pares del juego no interactúan entre sí, así que la",
        "mediana del lift sobre todos ellos tiene que salir en 1,00. Si sale en 1,15, no",
        "es que sinergie el 60% del juego: es que falta control y el ranking entero está",
        "desplazado hacia arriba.",
        "",
        f"  pares medidos              {cal.measured}",
        f"  MEDIANA DEL LIFT           {cal.median_lift:.3f}   → {veredicto}",
        f"  con el IC fuera del 1      {100 * cal.significant_fraction:.1f}% "
        f"(bajo el nulo se espera ~5%)",
        f"  descubrimientos tras BH    {cal.discoveries} (FDR {100 * cal.alpha:.0f}%)",
        "",
        "Sin la corrección de Benjamini-Hochberg, probar 2 080 pares al 5% regala ~104",
        "'hallazgos' aunque no exista ninguno. La columna q es la corregida.",
        "",
    ] + _tuning_rows(tuning)


def _tuning_rows(tuning) -> list[str]:
    """La escalera de tramos que recorrió el autoajuste, si lo hubo."""
    if not tuning:
        return []
    lines = ["Autoajuste del control por tamaño de mazo (se para al centrar la mediana):",
             f"  {'tramos':>7}{'mediana':>10}{'IC fuera del 1':>17}{'descubrimientos':>17}"]
    for buckets, cal in tuning:
        lines.append(f"  {buckets:>7}{cal.median_lift:>10.3f}"
                     f"{100 * cal.significant_fraction:>16.1f}%{cal.discoveries:>17}")
    lines += ["", "Cuántos tramos hacen falta depende del tamaño del corpus: con pocas",
              "partidas los estratos se caen por falta de celdas y el estimador queda",
              "atenuado; con muchas, el confusor residual aflora y hacen falta más tramos.",
              ""]
    return lines


def confounder_section(pairs: Sequence[PairResult], top: int = 8) -> list[str]:
    """La sección que justifica todo el aparato estadístico."""
    check = cost_correlation(pairs)
    lines = [
        RULE,
        "DIAGNÓSTICO DEL CONFUSOR — por qué no vale el lift ingenuo",
        RULE,
        "P(ganar|A,B) / (P(ganar|A)·P(ganar|B)) no mide sinergia: mide dinero. Dos cartas",
        "caras coinciden en el mazo del que tuvo economía, y la economía gana sola.",
        "Correlaciones de Spearman:",
        f"  lift INGENUO con el coste del par        ρ = {check.naive_vs_cost:+.3f}",
        f"  lift ESTRATIFICADO con el coste del par  ρ = {check.synergy_vs_cost:+.3f}",
        f"  un ranking con el otro                   ρ = {check.naive_vs_synergy:+.3f}",
        "",
        "La primera positiva es el confusor: el ranking ingenuo va ordenado por coste.",
        "La segunda NO tiene que ser cero. A igualdad de tamaño de mazo dos cartas caras",
        "compiten por los mismos huecos y por las mismas quemas, así que es esperable que",
        "salga negativa; lo que importa es que ya no es la misma relación. La tercera es",
        "la decisiva: si fuera alta, el ajuste no habría cambiado nada.",
        "",
        f"Top {top} del ranking INGENUO (esto es lo que NO hay que entregar):",
    ]
    by_naive = sorted((p for p in pairs if math.isfinite(p.naive)),
                      key=lambda p: -p.naive)[:top]
    for pair in by_naive:
        lines.append(f"   {pair.cards[0]} + {pair.cards[1]:<24.24} "
                     f"ingenuo={pair.naive:5.2f}  coste={pair.cost:<3d} "
                     f"n={pair.support:<4d} sinergia real={_fmt_lift(pair.synergy.lift)}"
                     f" ({pair.synergy.strata_used} estratos)")
    if by_naive:
        mean_cost = sum(p.cost for p in by_naive) / len(by_naive)
        overall = sum(p.cost for p in pairs) / len(pairs)
        lines.append(f"   coste medio del top ingenuo {mean_cost:.1f} "
                     f"frente a {overall:.1f} en el conjunto")
    lines.append("")
    return lines


def pairs_section(pairs: Sequence[PairResult], top: int, min_support: int) -> list[str]:
    robust = [p for p in pairs if p.synergy.robust(min_support=min_support)]
    weak = [p for p in pairs if not p.synergy.robust(min_support=min_support)
            and p.synergy.estimated and p.synergy.lift > 1][:top]
    anti = sorted((p for p in pairs if p.synergy.robust(min_support=min_support)
                   and p.synergy.lift < 1), key=lambda p: p.synergy.lift)

    lines = [
        RULE,
        "PARES — lift de interacción estratificado",
        RULE,
        "Lift = cuánto más aporta B a quien YA tiene A que a quien no. 1,00 = ninguna",
        "sinergia. ✔ = robusto: soporte suficiente, IC fuera del 1, IC utilizable y",
        "q ≤ 0,05 tras Benjamini-Hochberg.",
        "· = significativo pero con intervalo demasiado ancho para apostar.",
        "",
        f"SINERGIAS ROBUSTAS ({len(robust)})",
    ]
    fila = functools.partial(_pair_row, min_support=min_support)
    _rows(lines, robust[:top], fila,
          "  (ninguna: con este corpus ningún par supera los cuatro criterios a la vez)")
    lines += ["", f"CANDIDATOS NO CONCLUYENTES (mejores {len(weak)}) — NO citar como hallazgo"]
    _rows(lines, weak, fila, "  (ninguno)")
    lines += ["", f"ANTI-SINERGIAS ROBUSTAS ({len(anti)}) — juntas rinden menos que por separado"]
    _rows(lines, anti[:top], fila, "  (ninguna)")
    lines.append("")
    return lines


def triples_section(triples: Sequence[TripleResult], top: int) -> list[str]:
    lines = [
        RULE,
        "TRÍOS — lift del corte más débil",
        RULE,
        "Cada trío se parte de las tres formas posibles (pareja compuesta + tercera carta)",
        "y se queda el peor resultado. Así un trío sólo puntúa si aporta sobre CUALQUIERA",
        "de sus tres pares, y no por arrastrar un buen par con un acompañante.",
        "",
    ]
    good = [t for t in triples if t.synergy.robust(min_support=20)]
    measured = [t for t in triples if t.synergy.estimated]
    lines += [f"TRÍOS ROBUSTOS ({len(good)})"]
    _rows(lines, good[:top], _triple_row,
          "  (ninguno: los tríos tienen un orden de magnitud menos de soporte que los pares)")
    rest = [t for t in measured if not t.synergy.robust(min_support=20)][:top]
    lines += ["", f"MEJORES TRÍOS NO CONCLUYENTES ({len(rest)} de {len(measured)} "
              f"estimables sobre {len(triples)} con soporte)"]
    _rows(lines, rest, _triple_row, "  (ninguno)")
    lines.append("")
    return lines


def rules_section(checks: Sequence[RuleCheck], pairs: Sequence[PairResult]) -> list[str]:
    lines = [
        RULE,
        "CONTRASTE CON LAS 13 REGLAS ESCRITAS A MANO (agents/synergy.py)",
        RULE,
        f"{'regla':<34}{'pares':>6}{'conf.':>6}{'contra':>7}{'mediana':>9}  mejor par",
        "",
    ]
    for check in checks:
        best = f"{check.best[0]} + {check.best[1]}" if check.best else "—"
        lines.append(f"{check.rule:<34}{check.measured:>6}{check.confirmed:>6}"
                     f"{check.contradicted:>7}{_fmt_lift(check.median_lift):>9}  "
                     f"{best:.30} ({_fmt_lift(check.best_lift).strip()})")
    silent = [c.rule for c in checks if c.measured == 0]
    if silent:
        lines += ["", "Reglas sin ningún par por encima del soporte mínimo (el corpus no las",
                  "contradice: es que no las prueba): " + ", ".join(silent)]

    lines += ["", "PARES FUERTES QUE NINGUNA REGLA PREDICE — lo que aporta la minería"]
    fresh = [p for p in undiscovered(pairs, top=200) if p.synergy.robust()][:12]
    _rows(lines, fresh, _pair_row, "  (ninguno robusto; ver la lista de no concluyentes)")
    lines.append("")
    return lines


def permutation_section(null, real) -> list[str]:
    """El control que separa "hay señal" de "el método fabrica señal"."""
    exceso = (real.significant_fraction / null.significant_fraction
              if null.significant_fraction else float("inf"))
    veredicto = ("la señal del ranking es real: sobre datos barajados no queda nada"
                 if null.discoveries == 0 and null.significant_fraction < 0.09 else
                 "CUIDADO: el método produce significación sobre datos barajados; "
                 "el ranking no vale")
    return [
        RULE,
        "NULO DE PERMUTACIÓN — el método contra sí mismo",
        RULE,
        "Se baraja quién gana DENTRO de cada estrato. Eso conserva todo lo que confunde",
        "—tamaño de mazo, arquetipo, jugadores, qué compra cada quién— y destruye sólo la",
        "asociación entre cartas y victoria. La respuesta correcta pasa a ser lift 1 para",
        "los 2 080 pares, así que lo que salga lo ha fabricado el método.",
        "",
        f"{'':<12}{'mediana':>10}{'IC fuera del 1':>17}{'descubrimientos':>17}",
        f"{'barajado':<12}{null.median_lift:>10.3f}"
        f"{100 * null.significant_fraction:>16.1f}%{null.discoveries:>17}",
        f"{'real':<12}{real.median_lift:>10.3f}"
        f"{100 * real.significant_fraction:>16.1f}%{real.discoveries:>17}",
        "",
        f"El corpus real da {exceso:.1f}× más pares significativos que el barajado. "
        f"Veredicto:",
        f"{veredicto}.",
        "",
    ]


def patterns_section(patterns) -> list[str]:
    """Los grupos mecánicos de pares, que sí tienen potencia."""
    lines = [
        RULE,
        "PATRONES AGREGADOS — donde sí hay potencia estadística",
        RULE,
        "Un par suelto casi nunca llega a ser concluyente. Un grupo de cientos de pares",
        "que comparten una propiedad mecánica, sí. Se cuenta cuántos caen a cada lado del",
        "1 (test de signos): los lifts tienen cola larga y una media se la lleva un par",
        "con soporte 30. Cada grupo se lee CONTRA la fila de referencia, no contra 1,00.",
        "",
        f"{'grupo':<42}{'pares':>7}{'mediana':>9}{'>1':>8}{'p':>9}",
    ]
    for pattern in patterns:
        marca = "✔" if pattern.sign_p < 0.01 else (" " if pattern.sign_p > 0.05 else "·")
        lines.append(f"{marca}{pattern.name:<41}{pattern.pairs:>7}"
                     f"{pattern.median_lift:>9.3f}{100 * pattern.fraction_above:>7.0f}%"
                     f"{pattern.sign_p:>9.3f}")
    lines += ["", "Los pares de un grupo comparten cartas y NO son independientes, así que "
              "la p",
              "es orientativa y siempre optimista. Con 60/40 sobre cientos de pares la",
              "conclusión aguanta; con 55/45 no.", ""]
    return lines


def replication_section(rep) -> list[str]:
    """Lo que sobrevive a repetir el análisis en la otra mitad del corpus."""
    lines = [
        RULE,
        "REPLICACIÓN EN DOS MITADES INDEPENDIENTES",
        RULE,
        "Un IC dice cuánto ruido tiene una estimación; no dice cuánto ruido añaden las",
        "decisiones de análisis. Se corta el corpus por partidas pares e impares —nunca",
        "por asientos, que comparten resultado— y se rehace todo en cada mitad.",
        "",
        f"  concordancia de rangos entre mitades   ρ = {rep.rank_agreement:+.3f}",
        f"  pares robustos que replican dirección  {rep.same_direction}/{rep.checked}"
        + (f" ({100 * rep.agreement:.0f}%)" if rep.checked else ""),
        "",
    ]
    if rep.detail:
        lines.append(f"{'par':<40}{'mitad par':>12}{'mitad impar':>13}")
        for cards, a, b in rep.detail[:20]:
            marca = " " if (a - 1) * (b - 1) > 0 else "×"
            lines.append(f"{marca}{cards[0] + ' + ' + cards[1]:<39}{a:>12.2f}{b:>13.2f}")
        lines.append("")
        lines.append("× = cambia de lado del 1 entre mitades: no replica, no es un hallazgo.")
    else:
        lines.append("  (no hay pares robustos que contrastar)")
    lines.append("")
    return lines


def verdict(pairs: Sequence[PairResult], triples: Sequence[TripleResult],
            index: Index) -> list[str]:
    """Qué me creo y qué no. Sin esta sección el ranking es peor que no tenerlo."""
    robust = [p for p in pairs if p.synergy.robust()]
    significant = [p for p in pairs if p.synergy.significant]
    measured = [p for p in pairs if p.synergy.estimated]
    cal = calibration(pairs)
    check = cost_correlation(pairs)
    hint = mining.power_hint(pairs)
    inconclusos = len(significant) - len(robust)
    trios_robustos = sum(1 for t in triples if t.synergy.robust(min_support=20))
    return [
        RULE,
        "QUÉ ES ROBUSTO Y QUÉ NO",
        RULE,
        f"· De {len(pairs)} pares con soporte, {len(measured)} llegaron a tener algún",
        "  estrato con las cuatro celdas pobladas. El resto sale n/d, que NO es lift 1.",
        f"· De esos {len(measured)}, sólo {len(robust)} pasan los cuatro criterios: soporte,",
        "  IC fuera del 1, IC utilizable y q de Benjamini-Hochberg. SÓLO ÉSOS son citables.",
        f"· Otros {inconclusos} tienen el IC fuera del 1 pero no sobreviven a la corrección por",
        "  multiplicidad, o traen un intervalo demasiado ancho. Sirven para dirigir el",
        "  siguiente lote, no para concluir nada.",
        f"· Tríos: {trios_robustos} robustos de {len(triples)} con soporte. El soporte "
        "de un trío cae",
        "  con el cubo de la rareza; aquí la respuesta honesta casi siempre es que hace",
        "  falta más corpus.",
        f"· El ajuste cambia el ranking de verdad: ρ con el coste pasa de "
        f"{check.naive_vs_cost:+.3f} a",
        f"  {check.synergy_vs_cost:+.3f}, y los dos rankings sólo correlacionan "
        f"{check.naive_vs_synergy:+.3f} entre sí.",
        f"· Calibración: mediana del lift {cal.median_lift:.3f}. "
        + ("Centrada; el ajuste parece completo."
           if cal.well_centred else
           "DESPLAZADA: queda confusor y nada de arriba es citable."),
        "",
    ] + ([] if len(robust) >= 5 or not hint.best else [
        f"· Cuánto corpus falta: el mejor candidato es {hint.best[0]} + {hint.best[1]}, que va",
        f"  con z = {hint.best_z:.2f} y necesita {hint.z_needed:.2f} para pasar la FDR "
        "en el primer puesto.",
        f"  La z crece con √N, así que harían falta ~{hint.factor:.1f}× las partidas "
        "de este corpus.",
        "  Si ese número sale enorme, el efecto es pequeño y no compensa perseguirlo.",
        "",
    ]) + [
        "Salvedades que NO se arreglan con más partidas:",
        "· Nada que dependa del ritmo de las Misiones es fiable: son datos homebrew y hoy",
        "  deciden casi todas las partidas.",
        "· El corpus lo juega el `UtilityAgent`, que ya compra guiado por `synergy.RULES`.",
        "  Eso sesga QUÉ pares llegan a tener soporte —no el contraste dentro del estrato—,",
        "  pero implica que un par que ninguna regla favorece necesita muchas más partidas",
        "  para alcanzar la misma precisión. Los pares 'sin regla' están medidos peor.",
        "· En PvP los asientos de una misma partida no son independientes: gana uno solo.",
        f"  Con {index.observations} asientos el efecto es pequeño frente al ancho "
        "de los intervalos,",
        "  pero los IC de arriba son algo optimistas.",
        "· El control por tamaño de mazo es en parte un mediador, no sólo un confusor: si",
        "  un combo te mantiene vivo y por eso compras más, controlarlo se come parte del",
        "  efecto. La pregunta que responde el ranking es la del constructor de mazos —'a",
        "  igualdad de huecos, ¿aporta más B a quien ya tiene A?'—, que es la útil, pero no",
        "  es la misma que '¿cuánto sube mi tasa de victoria si añado el combo?'.",
        "",
    ]


def explain_section(index: Index, a: str, b: str, min_cell: int) -> str:
    """Desglose de un par, estrato a estrato."""
    breakdown = mining.explain_pair(index, a, b, min_cell=min_cell)
    used = [s for s in breakdown if s.used]
    estimate = stats.estimate_from_strata(
        [(s.both, s.only_a, s.only_b, s.neither) for s in breakdown], min_cell=min_cell)
    lines = [
        RULE,
        f"DESGLOSE DE {a} + {b}",
        RULE,
        f"Lift agregado {_fmt_lift(estimate.lift)} {_fmt_ci(estimate)} "
        f"sobre {estimate.strata_used} estratos, soporte {estimate.support}.",
        "",
        f"{'estrato':<44}{'ambas':>10}{'sólo A':>10}{'sólo B':>10}"
        f"{'ninguna':>10}{'ψ':>7}{'peso':>7}",
    ]
    for row in breakdown[:40]:
        clave = f"{row.key[0]} · {row.key[1]}p · {row.key[2]} · tramo {row.key[3]}"
        marca = " " if row.used else "×"
        lines.append(
            f"{marca}{clave:<43}"
            f"{row.both.wins:>4}/{row.both.n:<5}"
            f"{row.only_a.wins:>4}/{row.only_a.n:<5}"
            f"{row.only_b.wins:>4}/{row.only_b.n:<5}"
            f"{row.neither.wins:>4}/{row.neither.n:<5}"
            f"{row.log_lift:>7.2f}{row.weight:>7.1f}")
    if len(breakdown) > 40:
        lines.append(f"  … y {len(breakdown) - 40} estratos más")
    lines += ["", "× = estrato descartado por no tener las cuatro celdas pobladas "
              f"(min_cell={min_cell}).",
              f"Entran {len(used)} de {len(breakdown)} estratos con presencia del par.", ""]
    return "\n".join(lines)


def render(index: Index, pairs: Sequence[PairResult], triples: Sequence[TripleResult],
           checks: Sequence[RuleCheck], *, corpus_path: str, size_control: bool,
           top: int = 25, min_support: int = 30, replication=None,
           computed_triples: bool = True, tuning=(), patterns=(),
           permutation=None) -> str:
    lines: list[str] = []
    lines += header(index, corpus_path, size_control)
    lines += homebrew_warning()
    lines += calibration_section(pairs, tuning)
    lines += confounder_section(pairs)
    lines += pairs_section(pairs, top, min_support)
    if computed_triples:
        lines += triples_section(triples, top)
    lines += rules_section(checks, pairs)
    if patterns:
        lines += patterns_section(patterns)
    if permutation is not None:
        lines += permutation_section(permutation, calibration(pairs))
    if replication is not None:
        lines += replication_section(replication)
    lines += verdict(pairs, triples, index)
    return "\n".join(lines)
