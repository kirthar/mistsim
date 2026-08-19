"""Minería de pares y tríos de cartas sobre un corpus de partidas.

Qué se mide
-----------
Para un par (A, B), **no** cuánto ganan juntos, sino cuánto más aporta B a quien ya
tiene A que a quien no lo tiene. Ese contraste vive en `stats.interaction`; aquí se
construyen las tablas de contingencia que lo alimentan, estrato a estrato.

Estratificación
---------------
El estrato es `(arquetipo, nº de jugadores, modo, tramo de tamaño de mazo)`.

Los tres primeros son obligatorios: la tasa de victoria base es 1/2, 1/3 o 1/4 según los
jugadores, cada arquetipo compra cartas distintas y gana a ritmos distintos, y en Coop
se gana en equipo. Mezclarlos hace que dos cartas "del mismo arquetipo" parezcan
sinérgicas cuando lo único que comparten es que las compra el arquetipo que más gana.

El cuarto es el que ataca el confusor de fondo: **el dinero**. Dos cartas caras coinciden
en el mazo del jugador que tuvo economía, y la economía gana partidas por su cuenta.
Comparando sólo dentro del mismo tramo de tamaño de mazo, esa vía queda cerrada. Se
puede desactivar (`size_control=False`) precisamente para enseñar cuánto cambia.

Cuántos tramos hacen falta no es una constante: depende del tamaño del corpus, porque
con pocas partidas la mitad de los estratos se cae por falta de celdas y el estimador
queda atenuado. `tune_size_buckets` los sube hasta que la mediana del lift de los ~2 000
pares vuelve a 1, que es el diagnóstico nulo de `Calibration`. Con terciles y 30 000
partidas esa mediana se queda en 1,14 y salen 1 500 "descubrimientos"; con veinte
tramos, en 1,01 y salen seis.

Implementación
--------------
Un `int` de Python por carta y estrato hace de bitset sobre las observaciones de ese
estrato. Contar una celda de la 2×2 es un `and` y un `bit_count()`, así que los 2 080
pares por decenas de estratos salen en segundos sin dependencias.
"""
from __future__ import annotations

import bisect
import collections
import itertools
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from mistsim.analysis import stats
from mistsim.analysis.corpus import Observation
from mistsim.analysis.stats import Cell, Estimate

StratumKey = tuple[str, int, str, int]


@dataclass
class Stratum:
    """Las observaciones de un estrato, indexadas como bitsets."""

    key: StratumKey
    size: int = 0
    wins_mask: int = 0
    all_mask: int = 0
    owners: dict[str, int] = field(default_factory=dict)

    def cells(self, mask_a: int, mask_b: int) -> tuple[Cell, Cell, Cell, Cell]:
        """(ambas, sólo A, sólo B, ninguna) para dos conjuntos de poseedores."""
        both = mask_a & mask_b
        only_a = mask_a & ~mask_b & self.all_mask
        only_b = mask_b & ~mask_a & self.all_mask
        neither = self.all_mask & ~(mask_a | mask_b)
        return tuple(  # type: ignore[return-value]
            Cell(m.bit_count(), (m & self.wins_mask).bit_count())
            for m in (both, only_a, only_b, neither)
        )

    def mask(self, card: str) -> int:
        return self.owners.get(card, 0)


@dataclass
class Index:
    """El corpus entero, troceado en estratos y con los conteos globales."""

    strata: list[Stratum]
    observations: int
    wins: int
    pair_support: collections.Counter[tuple[str, str]]
    card_support: collections.Counter[str]
    card_wins: collections.Counter[str]
    size_edges: list[int]


def bucket_edges(sizes: Sequence[int], buckets: int) -> list[int]:
    """Cortes por cuantiles del tamaño de mazo.

    Por cuantiles y no fijos porque el tamaño típico depende del modo y del tope de
    turnos: unos cortes en 4/8/12 dejarían todos los asientos de las partidas cortas en
    el mismo tramo y el control no controlaría nada.

    Pedir N tramos puede dar menos: si dos cuantiles caen en el mismo tamaño entero, el
    corte se descarta en vez de crear un tramo vacío.
    """
    if buckets <= 1 or not sizes:
        return []
    ordered = sorted(sizes)
    edges: list[int] = []
    for i in range(1, buckets):
        edge = ordered[i * len(ordered) // buckets]
        if not edges or edge > edges[-1]:
            edges.append(edge)
    return edges


#: Tramos de tamaño de mazo por defecto cuando no se autoajusta. Ocho y no tres: con
#: terciles el tramo alto va de 8 a 60 cartas y dentro de él el tamaño sigue explicando
#: la victoria, lo que desplazaba la mediana del lift de TODOS los pares (ver
#: `Calibration`). Cuántos hacen falta depende del tamaño del corpus, así que el CLI
#: usa `tune_size_buckets` en lugar de este número fijo.
DEFAULT_SIZE_BUCKETS = 8

#: Escalera de tramos que prueba el autoajuste, de menos a más control.
BUCKET_LADDER = (3, 5, 8, 12, 20, 30, 45)


def build_index(observations: Iterable[Observation], *, size_control: bool = True,
                size_buckets: int = DEFAULT_SIZE_BUCKETS) -> Index:
    """Indexa el corpus. Consume el iterable una sola vez."""
    rows = list(observations)
    edges = bucket_edges([o.size for o in rows], size_buckets) if size_control else []

    grouped: dict[StratumKey, list[Observation]] = collections.defaultdict(list)
    for obs in rows:
        bucket = bisect.bisect_right(edges, obs.size) if edges else 0
        grouped[(obs.strategy, obs.players, obs.mode, bucket)].append(obs)

    strata: list[Stratum] = []
    pair_support: collections.Counter[tuple[str, str]] = collections.Counter()
    card_support: collections.Counter[str] = collections.Counter()
    card_wins: collections.Counter[str] = collections.Counter()
    wins = 0

    for key, members in sorted(grouped.items()):
        stratum = Stratum(key=key, size=len(members), all_mask=(1 << len(members)) - 1)
        for i, obs in enumerate(members):
            bit = 1 << i
            if obs.won:
                stratum.wins_mask |= bit
                wins += 1
            ordered = sorted(obs.cards)
            for card in ordered:
                stratum.owners[card] = stratum.owners.get(card, 0) | bit
                card_support[card] += 1
                if obs.won:
                    card_wins[card] += 1
            pair_support.update(itertools.combinations(ordered, 2))
        strata.append(stratum)

    return Index(strata=strata, observations=len(rows), wins=wins,
                 pair_support=pair_support, card_support=card_support,
                 card_wins=card_wins, size_edges=edges)


# --- pares -------------------------------------------------------------------


@dataclass
class PairResult:
    cards: tuple[str, str]
    #: Co-ocurrencias en todo el corpus (antes de exigir estratos completos).
    support: int
    #: Co-ocurrencias dentro de los estratos que sí entraron en la estimación.
    synergy: Estimate
    #: El estimador confundido, para poder contrastarlo.
    naive: float
    wins_both: int
    n_both: int
    cost: int
    rules: tuple[str, ...] = ()

    @property
    def win_rate(self) -> float:
        return self.wins_both / self.n_both if self.n_both else 0.0

    def wilson(self) -> tuple[float, float]:
        return stats.wilson_interval(self.wins_both, self.n_both)


def _global_cells(index: Index, a: str, b: str) -> tuple[int, int, int, int, int, int]:
    """(w_ambas, n_ambas, w_A, n_A, w_B, n_B) sumando todos los estratos."""
    w_both = n_both = w_a = n_a = w_b = n_b = 0
    for stratum in index.strata:
        mask_a, mask_b = stratum.mask(a), stratum.mask(b)
        both = mask_a & mask_b
        n_both += both.bit_count()
        w_both += (both & stratum.wins_mask).bit_count()
        n_a += mask_a.bit_count()
        w_a += (mask_a & stratum.wins_mask).bit_count()
        n_b += mask_b.bit_count()
        w_b += (mask_b & stratum.wins_mask).bit_count()
    return w_both, n_both, w_a, n_a, w_b, n_b


def mine_pairs(index: Index, *, min_support: int = 30, min_cell: int = 5,
               costs: dict[str, int] | None = None) -> list[PairResult]:
    """Estima la sinergia de todos los pares que llegan al soporte mínimo.

    `min_support` filtra antes de calcular nada: con 65 cartas hay 2 080 pares y muchos
    salen tres veces en todo el corpus. Un lift de 12 con soporte 3 no es un hallazgo,
    es una moneda que cayó de canto, y colarlo en el ranking contamina todo lo demás.
    """
    costs = costs or {}
    results: list[PairResult] = []
    for (a, b), support in index.pair_support.items():
        if support < min_support:
            continue
        strata_cells = [s.cells(s.mask(a), s.mask(b)) for s in index.strata
                        if s.mask(a) and s.mask(b)]
        estimate = stats.estimate_from_strata(strata_cells, min_cell=min_cell)
        w_both, n_both, w_a, n_a, w_b, n_b = _global_cells(index, a, b)
        results.append(PairResult(
            cards=(a, b), support=support, synergy=estimate,
            naive=stats.naive_lift(w_both, n_both, w_a, n_a, w_b, n_b),
            wins_both=w_both, n_both=n_both,
            cost=costs.get(a, 0) + costs.get(b, 0)))
    stats.control_fdr([r.synergy for r in results])
    results.sort(key=_by_lift)
    return results


@dataclass(frozen=True)
class StratumBreakdown:
    """Lo que aporta un estrato concreto a la estimación de un par."""

    key: StratumKey
    both: Cell
    only_a: Cell
    only_b: Cell
    neither: Cell
    log_lift: float
    variance: float
    used: bool

    @property
    def weight(self) -> float:
        return 1.0 / self.variance if self.variance > 0 else 0.0


def explain_pair(index: Index, a: str, b: str, *, min_cell: int = 5
                 ) -> list[StratumBreakdown]:
    """Desglose estrato a estrato de un par.

    Existe para poder discutir una discrepancia con las reglas escritas a mano sin
    creerse el número agregado: casi siempre el desacuerdo es que el par sólo tiene
    soporte en dos estratos, o que un estrato con 6 observaciones tira del resto.
    """
    out = []
    for stratum in index.strata:
        mask_a, mask_b = stratum.mask(a), stratum.mask(b)
        if not mask_a and not mask_b:
            continue
        both, only_a, only_b, neither = stratum.cells(mask_a, mask_b)
        used = min(both.n, only_a.n, only_b.n, neither.n) >= min_cell
        psi, var = stats.interaction(both, only_a, only_b, neither)
        out.append(StratumBreakdown(stratum.key, both, only_a, only_b, neither,
                                    psi, var, used))
    out.sort(key=lambda s: (-s.both.n, s.key))
    return out


# --- tríos -------------------------------------------------------------------


@dataclass
class TripleResult:
    cards: tuple[str, str, str]
    support: int
    #: El más débil de los tres cortes: mide lo que el trío añade **sobre cada uno** de
    #: sus pares, no sobre las cartas sueltas.
    synergy: Estimate
    #: La carta que quedó como "tercera" en ese corte más débil.
    weakest_third: str
    wins_all: int
    n_all: int
    cost: int
    rules: tuple[str, ...] = ()


def mine_triples(index: Index, pairs: Iterable[PairResult], *, min_support: int = 25,
                 min_cell: int = 5, costs: dict[str, int] | None = None,
                 max_candidates: int = 4000) -> list[TripleResult]:
    """Tríos, definidos como "aporta por encima de sus tres pares".

    Un trío se mide con tres cortes: se toma una pareja como un solo ítem compuesto
    (A∧B) y se calcula su interacción con la tercera carta. Se **queda el corte peor**
    de los tres. Es deliberadamente conservador: así un trío sólo puntúa si añade algo
    sobre *cualquiera* de sus pares, y no basta con que dos de sus cartas ya fueran
    buenas juntas y la tercera venga de acompañante.
    """
    costs = costs or {}
    known = {pair.cards for pair in pairs}
    if not known:
        return []
    cards = sorted({card for pair in known for card in pair})
    candidates: list[tuple[str, str, str]] = [
        trio for trio in itertools.combinations(cards, 3)
        if all(p in known for p in itertools.combinations(trio, 2))
    ]

    scored: list[tuple[int, tuple[str, str, str]]] = []
    for trio in candidates:
        total = 0
        for stratum in index.strata:
            masks = [stratum.mask(c) for c in trio]
            if not all(masks):
                continue
            total += (masks[0] & masks[1] & masks[2]).bit_count()
        if total >= min_support:
            scored.append((total, trio))
    scored.sort(key=lambda item: -item[0])
    scored = scored[:max_candidates]

    results: list[TripleResult] = []
    for support, trio in scored:
        worst: Estimate | None = None
        worst_third = trio[0]
        for third in trio:
            pair = tuple(c for c in trio if c != third)
            cells = []
            for stratum in index.strata:
                compound = stratum.mask(pair[0]) & stratum.mask(pair[1])
                mask_c = stratum.mask(third)
                if not compound or not mask_c:
                    continue
                cells.append(stratum.cells(compound, mask_c))
            estimate = stats.estimate_from_strata(cells, min_cell=min_cell)
            if worst is None or _lift_or_inf(estimate) < _lift_or_inf(worst):
                worst, worst_third = estimate, third
        assert worst is not None
        wins_all = n_all = 0
        for stratum in index.strata:
            masks = [stratum.mask(c) for c in trio]
            if not all(masks):
                continue
            all_three = masks[0] & masks[1] & masks[2]
            n_all += all_three.bit_count()
            wins_all += (all_three & stratum.wins_mask).bit_count()
        results.append(TripleResult(
            cards=trio, support=support, synergy=worst, weakest_third=worst_third,
            wins_all=wins_all, n_all=n_all,
            cost=sum(costs.get(c, 0) for c in trio)))
    stats.control_fdr([r.synergy for r in results])
    results.sort(key=_by_lift)
    return results


def _lift_or_inf(estimate: Estimate) -> float:
    """Un corte sin estimación no puede ser el "peor": no sabemos que sea malo."""
    return estimate.lift if estimate.estimated else math.inf


def _by_lift(result) -> tuple[int, float]:
    """Ordena de mayor a menor lift dejando los no estimados al final."""
    if not result.synergy.estimated:
        return (1, 0.0)
    return (0, -result.synergy.lift)


# --- diagnóstico del confusor ------------------------------------------------


@dataclass(frozen=True)
class Calibration:
    """Chequeo de que el ajuste por confusor está completo.

    La inmensa mayoría de los 2 080 pares del juego no tienen ninguna interacción
    mecánica entre sí, así que **la mediana del lift sobre todos los pares tiene que
    salir en 1**. Si sale en 1,15, no es que el 60% de los pares del juego sinergien:
    es que queda confusor sin controlar y todo el ranking está desplazado hacia arriba.

    Es el diagnóstico que destapó que estratificar el tamaño de mazo en terciles no
    basta —el tercil alto va de 8 a 60 cartas y dentro de él el tamaño sigue mandando—.

    No es una prueba de insesgadez: si de verdad hubiera sinergia por todas partes, la
    mediana se movería con razón. Pero un desplazamiento de la mediana es siempre algo
    que hay que explicar antes de publicar el ranking.
    """

    measured: int
    median_lift: float
    #: Proporción con el IC fuera del 1. Bajo el nulo debería rondar el 5%.
    significant_fraction: float
    #: Descubrimientos que sobreviven a Benjamini-Hochberg.
    discoveries: int
    alpha: float = 0.05

    @property
    def well_centred(self) -> bool:
        return abs(self.median_lift - 1.0) <= 0.05


def calibration(results: Sequence, alpha: float = 0.05) -> Calibration:
    measured = [r.synergy for r in results if r.synergy.estimated]
    if not measured:
        return Calibration(0, math.nan, math.nan, 0, alpha)
    lifts = sorted(e.lift for e in measured)
    return Calibration(
        measured=len(measured),
        median_lift=lifts[len(lifts) // 2],
        significant_fraction=sum(1 for e in measured if e.significant) / len(measured),
        discoveries=sum(1 for e in measured
                        if math.isfinite(e.q_value) and e.q_value <= alpha),
        alpha=alpha)


@dataclass(frozen=True)
class ConfounderCheck:
    """Cuánto arrastra el coste a cada ranking, y cuánto se parecen entre sí."""

    #: Spearman del lift ingenuo con el coste del par. Se espera claramente positiva:
    #: es el confusor haciendo de las suyas.
    naive_vs_cost: float
    #: Spearman del lift estratificado con el coste.
    synergy_vs_cost: float
    #: Spearman entre los dos rankings. Si fuera alta, el ajuste no habría cambiado nada.
    naive_vs_synergy: float
    pairs: int


@dataclass(frozen=True)
class PowerHint:
    """Cuánto corpus falta para que el mejor candidato pase el filtro."""

    best_z: float
    z_needed: float
    #: Por cuánto habría que multiplicar el número de partidas.
    factor: float
    best: tuple[str, ...] | None


def power_hint(results: Sequence, alpha: float = 0.05) -> PowerHint:
    """Traduce "no ha salido nada" en "hacen falta N veces más partidas".

    La varianza del log-lift va como 1/N, así que z va como √N: multiplicar el corpus
    por (z_necesaria / z_actual)² pone al mejor candidato justo en el umbral. Es una
    cuenta de servilleta —supone que el efecto es real y del tamaño estimado— pero
    convierte un informe vacío en una instrucción concreta.
    """
    measured = [r for r in results if r.synergy.estimated and r.synergy.variance > 0]
    if not measured:
        return PowerHint(math.nan, math.nan, math.nan, None)
    def z_of(r) -> float:
        return abs(r.synergy.log_lift) / math.sqrt(r.synergy.variance)
    best = max(measured, key=z_of)
    # Umbral de Benjamini-Hochberg en el primer puesto: alpha / m.
    z_needed = stats.z_for_two_sided_p(alpha / len(measured))
    best_z = z_of(best)
    factor = (z_needed / best_z) ** 2 if best_z > 0 else math.inf
    return PowerHint(best_z, z_needed, factor, best.cards)


def cost_correlation(pairs: Sequence[PairResult]) -> ConfounderCheck:
    """Control de sanidad central del módulo.

    Lo que valida el ajuste no es que la correlación con el coste caiga a cero, sino que
    **deje de ser la misma relación**: el ingenuo sube con el coste porque las cartas
    caras las tiene quien tuvo dinero, mientras que el estratificado, medido a igualdad
    de tamaño de mazo, puede perfectamente salir NEGATIVO con el coste —dos cartas caras
    compiten por los mismos huecos y por las mismas quemas, así que a igualdad de espacio
    tienden a estorbarse—. Lo que sería una mala señal es que los dos rankings se
    parecieran entre sí: querría decir que no se ha corregido nada.
    """
    usable = [p for p in pairs
              if math.isfinite(p.naive) and p.synergy.estimated]
    if len(usable) < 3:
        return ConfounderCheck(float("nan"), float("nan"), float("nan"), len(usable))
    costs = [float(p.cost) for p in usable]
    naive = [p.naive for p in usable]
    synergy = [p.synergy.lift for p in usable]
    return ConfounderCheck(
        naive_vs_cost=stats.spearman(naive, costs),
        synergy_vs_cost=stats.spearman(synergy, costs),
        naive_vs_synergy=stats.spearman(naive, synergy),
        pairs=len(usable))


# --- replicación -------------------------------------------------------------


@dataclass(frozen=True)
class Replication:
    """Qué sobrevive al partir el corpus en dos mitades independientes.

    Un intervalo de confianza dice cuánto ruido tiene UNA estimación. No dice nada de
    cuánto ruido añaden las decisiones de análisis: qué estratos, qué tramos, qué
    umbral. La réplica sí: si un par sale con lift 2 en las partidas pares y con 0,8 en
    las impares, el intervalo estaba mintiendo.

    El corte es por partida y no por asiento, porque los asientos de una misma partida
    comparten resultado —gana uno solo— y repartirlos entre las dos mitades las haría
    dependientes justo en la variable que se mide.
    """

    checked: int
    #: Pares que en las dos mitades salen al mismo lado del 1.
    same_direction: int
    #: Spearman entre los lifts de una mitad y los de la otra, sobre todos los medidos.
    rank_agreement: float
    #: Detalle par a par: (cartas, lift A, lift B).
    detail: tuple[tuple[tuple[str, str], float, float], ...]

    @property
    def agreement(self) -> float:
        return self.same_direction / self.checked if self.checked else float("nan")


def replicate(observations: Sequence[Observation], selected: Sequence[PairResult], *,
              size_control: bool = True, size_buckets: int = DEFAULT_SIZE_BUCKETS,
              min_support: int = 10, min_cell: int = 5) -> Replication:
    """Vuelve a estimar `selected` en cada mitad del corpus y compara."""
    halves = ([o for o in observations if o.game % 2 == 0],
              [o for o in observations if o.game % 2 == 1])
    indexes = [build_index(h, size_control=size_control, size_buckets=size_buckets)
               for h in halves]
    lifts: list[dict[tuple[str, str], float]] = []
    for index in indexes:
        lifts.append({p.cards: p.synergy.lift
                      for p in mine_pairs(index, min_support=min_support,
                                          min_cell=min_cell)
                      if p.synergy.estimated})

    detail = []
    for pair in selected:
        a, b = lifts[0].get(pair.cards), lifts[1].get(pair.cards)
        if a is None or b is None:
            continue
        detail.append((pair.cards, a, b))
    same = sum(1 for _, a, b in detail if (a - 1) * (b - 1) > 0)

    comunes = sorted(set(lifts[0]) & set(lifts[1]))
    rho = stats.spearman([lifts[0][k] for k in comunes],
                         [lifts[1][k] for k in comunes]) if len(comunes) > 2 else math.nan
    return Replication(checked=len(detail), same_direction=same, rank_agreement=rho,
                       detail=tuple(detail))


def tune_size_buckets(observations: Sequence[Observation], *,
                      candidates: Sequence[int] = BUCKET_LADDER,
                      min_support: int = 30, min_cell: int = 5,
                      tolerance: float = 0.02
                      ) -> tuple[int, list[tuple[int, Calibration]]]:
    """Elige cuántos tramos de tamaño de mazo hacen falta, mirando la calibración.

    Cuántos tramos bastan **depende del tamaño del corpus**, y esto no es una excusa:
    con 5 000 partidas la mayoría de los estratos se caen por falta de celdas y el
    estimador queda atenuado, así que ocho tramos parecen suficientes; con 30 000 los
    estratos se pueblan, el confusor residual aflora y ocho tramos dejan la mediana del
    lift en 1,06. Fijar el número a ojo garantiza equivocarse en un extremo o en el otro.

    El criterio de parada es el diagnóstico nulo, no el resultado: se sube por la
    escalera hasta que la mediana del lift de los ~2 000 pares vuelve a 1. Es un
    criterio anclado en una hipótesis previa —la inmensa mayoría de los pares del juego
    no interactúan— y no en qué pares acaban saliendo, que es lo que lo separa de
    buscarle al análisis la forma que más gusta.

    Devuelve el número elegido y la escalera recorrida, para poder enseñarla.
    """
    trace: list[tuple[int, Calibration]] = []
    chosen = candidates[-1]
    for buckets in candidates:
        index = build_index(observations, size_control=True, size_buckets=buckets)
        cal = calibration(mine_pairs(index, min_support=min_support, min_cell=min_cell))
        trace.append((buckets, cal))
        if math.isfinite(cal.median_lift) and abs(cal.median_lift - 1.0) <= tolerance:
            chosen = buckets
            break
    else:
        # Ninguno centra la mediana: se queda el más estricto y el informe lo dirá.
        if trace:
            chosen = min(trace, key=lambda item: abs(item[1].median_lift - 1.0))[0]
    return chosen, trace


# --- patrones agregados ------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    """Un grupo de pares mirado en conjunto.

    Un par suelto casi nunca tiene potencia; un grupo de 300 pares que comparten una
    propiedad mecánica, sí. "¿Dos Aliados juntos rinden menos que por separado?" se
    responde con mucha más certeza que "¿Soother y Coinshot se estorban?".
    """

    name: str
    pairs: int
    median_lift: float
    #: Proporción de pares del grupo con lift > 1.
    fraction_above: float
    #: p bilateral del test de signos contra "la mitad por encima y la mitad por debajo".
    sign_p: float


def pattern_summary(pairs: Sequence[PairResult],
                    groups: dict[str, Callable[[PairResult], bool]]) -> list[Pattern]:
    """Resume el ranking por grupos de pares definidos mecánicamente.

    El test es de signos y no de medias: los lifts tienen cola larga y una media se la
    lleva un par con soporte 30. Contar cuántos caen a cada lado del 1 es robusto y es
    justo la pregunta ("¿este tipo de pareja tiende a ayudar o a estorbar?").

    Los pares de un grupo NO son independientes entre sí —comparten cartas—, así que la
    p es orientativa y siempre optimista. Con grupos de cientos de pares y proporciones
    del 60/40 la conclusión aguanta igualmente; con 55/45 no.
    """
    out = []
    for name, belongs in groups.items():
        selected = [p for p in pairs if p.synergy.estimated and belongs(p)]
        if not selected:
            continue
        lifts = sorted(p.synergy.lift for p in selected)
        above = sum(1 for lift in lifts if lift > 1.0)
        n = len(lifts)
        z = abs(above - n / 2) / math.sqrt(n / 4) if n else 0.0
        out.append(Pattern(name=name, pairs=n, median_lift=lifts[n // 2],
                           fraction_above=above / n,
                           sign_p=math.erfc(z / math.sqrt(2))))
    out.sort(key=lambda p: -p.pairs)
    return out


# --- nulo de permutación -----------------------------------------------------


def permute_within_strata(observations: Sequence[Observation], *, size_buckets: int,
                          size_control: bool = True, seed: int = 0) -> list[Observation]:
    """Baraja quién gana DENTRO de cada estrato.

    Conserva todo lo que confunde —el tamaño de mazo, el arquetipo, el número de
    jugadores, qué cartas compra cada quién— y destruye únicamente la asociación entre
    las cartas concretas y la victoria. Sobre el resultado, la respuesta correcta para
    los 2 080 pares es lift 1: cualquier cosa que salga la ha fabricado el método.
    """
    edges = bucket_edges([o.size for o in observations], size_buckets) if size_control else []
    groups: dict[StratumKey, list[int]] = collections.defaultdict(list)
    for i, obs in enumerate(observations):
        bucket = bisect.bisect_right(edges, obs.size) if edges else 0
        groups[(obs.strategy, obs.players, obs.mode, bucket)].append(i)

    rng = random.Random(seed)
    out = list(observations)
    for indices in groups.values():
        wins = [observations[i].won for i in indices]
        rng.shuffle(wins)
        for i, won in zip(indices, wins, strict=True):
            original = observations[i]
            out[i] = Observation(original.strategy, original.players, original.mode,
                                 original.cards, won, original.game)
    return out


def permutation_null(observations: Sequence[Observation], *, size_buckets: int,
                     size_control: bool = True, min_support: int = 30,
                     min_cell: int = 5, seed: int = 0) -> Calibration:
    """Corre la minería entera sobre datos barajados. Es el control decisivo.

    La calibración por la mediana dice si el ranking está desplazado; esto dice si el
    método fabrica significación. Son cosas distintas y las dos hacen falta: un
    estimador puede tener la mediana clavada en 1 y aun así dar el 12% de pares
    "significativos" sobre ruido puro, que es exactamente lo que pasaba antes de
    arreglar los pesos.
    """
    shuffled = permute_within_strata(observations, size_buckets=size_buckets,
                                     size_control=size_control, seed=seed)
    index = build_index(shuffled, size_control=size_control, size_buckets=size_buckets)
    return calibration(mine_pairs(index, min_support=min_support, min_cell=min_cell))


def permutation_null_triples(observations: Sequence[Observation], *, size_buckets: int,
                             size_control: bool = True, min_support: int = 30,
                             min_support_triple: int = 25, min_cell: int = 5,
                             seed: int = 0) -> Calibration:
    """Lo mismo para los tríos, que usan el mismo estimador pero otra búsqueda.

    Va aparte porque cuesta lo suyo: son dos minerías completas de tríos. Que el control
    valga para los pares no lo hace válido para los tríos, donde el candidato se elige
    entre muchos menos y con soporte más fino, así que se comprueba por separado.
    """
    shuffled = permute_within_strata(observations, size_buckets=size_buckets,
                                     size_control=size_control, seed=seed)
    index = build_index(shuffled, size_control=size_control, size_buckets=size_buckets)
    pairs = mine_pairs(index, min_support=min_support, min_cell=min_cell)
    return calibration(mine_triples(index, pairs, min_support=min_support_triple,
                                    min_cell=min_cell))
