"""Estimadores para la minería de combos.

Aquí está la parte que decide si el resultado es un hallazgo o un artefacto. Sólo
`math`: el proyecto no tiene dependencias y no vamos a añadir numpy para cuatro
logaritmos.

El problema que resuelve este módulo
------------------------------------
Comparar `P(ganar|A,B)` contra `P(ganar|A)·P(ganar|B)` mide sobre todo **dinero**: dos
cartas caras aparecen juntas porque el jugador tenía monedas, y tener monedas ya
correlaciona con ganar. El ranking que sale de ahí está ordenado por coste.

Lo que sí aísla la sinergia es el **contraste de interacción**: cuánto ayuda B a quien
YA tiene A, frente a cuánto ayuda B a quien no tiene A.

    ψ = log [ P(W|A,B) / P(W|A,¬B) ]  −  log [ P(W|¬A,B) / P(W|¬A,¬B) ]

Si B sólo era un indicador de riqueza, ayuda lo mismo en los dos grupos y ψ ≈ 0
(lift = e^ψ ≈ 1). El contraste es simétrico en A y B, como debe ser una sinergia.

Se calcula **dentro de cada estrato** (arquetipo × nº de jugadores × modo × tamaño de
mazo) y se agregan los estratos por inverso de la varianza, que es un meta-análisis de
efecto fijo de toda la vida. Un estrato al que le falte alguna de las cuatro celdas no
aporta nada en vez de aportar un número inventado.

La trampa del peso
------------------
El detalle que costó encontrar está en `_cell_variance`. Si la varianza de una celda se
estima con la tasa de victoria de esa misma celda, los estratos donde el par ganó de más
salen con varianza baja y por tanto con MÁS peso: el peso mira el resultado y la
agregación se va hacia arriba sola. Sobre un nulo de permutación —barajar quién gana
dentro de cada estrato— la mediana del lift salía en 1,03 con el 12% de los pares
"significativos". Usando la tasa del estrato entero el peso sólo depende de los tamaños
y el nulo vuelve a su sitio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Corrección de Haldane-Anscombe. Sin ella una celda con 0 victorias manda el
#: logaritmo a −infinito y un solo estrato degenerado decide el ranking entero.
CONTINUITY = 0.5

#: z de la normal para el 95%. Con conteos de dos cifras el intervalo es aproximado;
#: por eso el informe exige además soporte mínimo y no se fía sólo del intervalo.
Z95 = 1.959963984540054


@dataclass(frozen=True)
class Cell:
    """Una celda de la tabla 2×2: cuántas observaciones y cuántas ganaron."""

    n: int
    wins: int

    @property
    def rate(self) -> float:
        return self.wins / self.n if self.n else 0.0


@dataclass
class Estimate:
    """Un lift con su incertidumbre y de cuánta evidencia sale."""

    lift: float
    ci_low: float
    ci_high: float
    #: log-lift y su varianza, que es lo que se agrega entre estratos.
    log_lift: float
    variance: float
    #: Estratos que aportaron (los que tenían las cuatro celdas pobladas).
    strata_used: int
    #: Observaciones dentro de esos estratos con las dos cartas.
    support: int
    #: q de Benjamini-Hochberg, rellenada por `control_fdr` sobre el ranking COMPLETO.
    #: nan = todavía no se ha corregido por multiplicidad.
    q_value: float = math.nan

    @property
    def estimated(self) -> bool:
        """¿Hubo algún estrato utilizable?

        Sin esto, "no se pudo estimar" se disfrazaba de lift 1,00 —o sea, de "medido y
        sin sinergia"—, que es exactamente la clase de silencio que convierte una tabla
        en un artefacto. Un par sin estimación imprime n/d.
        """
        return self.strata_used > 0 and math.isfinite(self.lift)

    @property
    def significant(self) -> bool:
        """¿El intervalo excluye el 1? Necesario, no suficiente: ver `robust`."""
        return self.estimated and (self.ci_low > 1.0 or self.ci_high < 1.0)

    @property
    def p_value(self) -> float:
        """p bilateral de H0: ψ = 0, por normal asintótica."""
        if not self.estimated or self.variance <= 0 or not math.isfinite(self.variance):
            return math.nan
        z = abs(self.log_lift) / math.sqrt(self.variance)
        return math.erfc(z / math.sqrt(2))

    def robust(self, min_support: int = 30, max_width: float = 6.0,
               alpha: float = 0.05) -> bool:
        """Criterio explícito de "esto me lo creo".

        Cuatro condiciones a la vez, porque cada una sola engaña:

        1. soporte real —un lift enorme con n=3 no es un hallazgo—;
        2. el intervalo excluye el 1;
        3. el intervalo no es tan ancho que no diga nada (lift 40 con IC [1,2–900] es
           ruido con signo);
        4. sobrevive a la corrección por multiplicidad. Con 2 080 pares, probar al 5%
           regala ~104 "hallazgos" sin que exista ni uno. Si `control_fdr` no se ha
           llegado a aplicar (q = nan) esta condición no puede comprobarse y se salta,
           pero entonces el número de robustos NO está corregido.
        """
        if not self.estimated or self.support < min_support or not self.significant:
            return False
        if math.isfinite(self.q_value) and self.q_value > alpha:
            return False
        return self.ci_high / max(self.ci_low, 1e-9) <= max_width


def wilson_interval(wins: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción.

    Se usa para las tasas de victoria que se imprimen en el informe. Wilson y no
    Wald porque con n pequeño Wald se sale de [0,1] y da intervalos vacíos en 0 y 1,
    que es justo el régimen en el que está la mayoría de los pares.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _log_rate(cell: Cell) -> float:
    """log de la tasa de victoria de una celda, con corrección de continuidad."""
    return math.log((cell.wins + CONTINUITY) / (cell.n + 2 * CONTINUITY))


def _cell_variance(cell: Cell, base_rate: float) -> float:
    """Var(log p̂) ≈ (1−p)/(n·p) por el método delta, con p = tasa DEL ESTRATO.

    Aquí está el detalle que costó encontrar. La versión obvia usa la p de la propia
    celda, y eso sesga el resultado hacia arriba de forma sistemática: la varianza
    estimada baja justo cuando la celda ha ganado por encima de lo suyo, así que los
    estratos donde el par tuvo suerte reciben MÁS peso al agregar por inverso de la
    varianza. Con un nulo de permutación —barajar quién gana dentro de cada estrato, que
    destruye toda asociación— la mediana del lift salía en 1,03 y el 12% de los pares
    daba "significativo". Es decir: el propio estimador fabricaba 100 hallazgos.

    Usando la tasa del estrato el peso ya no depende de cómo se repartieron las
    victorias entre las cuatro celdas, sólo de sus tamaños, y el nulo vuelve a su sitio.
    """
    n = cell.n + 2 * CONTINUITY
    return (1 - base_rate) / (n * base_rate)


def base_rate(cells: tuple[Cell, ...]) -> float:
    """Tasa de victoria del estrato entero. Las cuatro celdas lo particionan."""
    wins = sum(c.wins for c in cells) + CONTINUITY
    total = sum(c.n for c in cells) + 2 * CONTINUITY
    return wins / total


def interaction(both: Cell, only_a: Cell, only_b: Cell, neither: Cell) -> tuple[float, float]:
    """Contraste de interacción de un estrato: (ψ, varianza).

    ψ = (log p11 − log p10) − (log p01 − log p00): el efecto de B entre los que tienen
    A menos el efecto de B entre los que no. Simétrico al intercambiar A y B.
    """
    cells = (both, only_a, only_b, neither)
    rate = base_rate(cells)
    psi = _log_rate(both) - _log_rate(only_a) - _log_rate(only_b) + _log_rate(neither)
    return psi, sum(_cell_variance(c, rate) for c in cells)


def pool(terms: list[tuple[float, float]]) -> tuple[float, float]:
    """Agrega (ψ, varianza) por estratos, ponderando por el inverso de la varianza.

    Es el estimador de efecto fijo: el estrato con 400 observaciones pesa lo que debe
    frente al que tiene 12, en vez de que ambos cuenten como "un estrato".
    """
    weights = [1.0 / v for _, v in terms if v > 0]
    if not weights:
        return (0.0, float("inf"))
    total = sum(weights)
    value = sum(psi * w for (psi, _), w in zip(terms, weights, strict=True)) / total
    return value, 1.0 / total


def estimate_from_strata(strata: list[tuple[Cell, Cell, Cell, Cell]], *,
                         min_cell: int = 5, z: float = Z95) -> Estimate:
    """Lift de sinergia agregando estratos.

    Un estrato sólo entra si sus **cuatro** celdas llegan a `min_cell`. Es la
    diferencia entre estratificar y fingir que se estratifica: un estrato en el que
    nadie tuvo las dos cartas no contiene información sobre la interacción.
    """
    terms: list[tuple[float, float]] = []
    support = 0
    for both, only_a, only_b, neither in strata:
        if min(both.n, only_a.n, only_b.n, neither.n) < min_cell:
            continue
        terms.append(interaction(both, only_a, only_b, neither))
        support += both.n
    if not terms:
        # nan y no 1.0: "no se pudo medir" no es "medido y da 1".
        return Estimate(math.nan, math.nan, math.nan, math.nan, math.inf, 0, 0)
    psi, var = pool(terms)
    half = z * math.sqrt(var)
    return Estimate(lift=math.exp(psi), ci_low=math.exp(psi - half),
                    ci_high=math.exp(psi + half), log_lift=psi, variance=var,
                    strata_used=len(terms), support=support)


def naive_lift(w_both: int, n_both: int, w_a: int, n_a: int, w_b: int, n_b: int) -> float:
    """El estimador confundido, a propósito.

    `P(W|A,B) / (P(W|A)·P(W|B))`, sin estratificar y sin condicionar. Se calcula para
    poder **enseñar** que su ranking va ordenado por coste; no para publicarlo como
    hallazgo. Ver `mining.cost_correlation`.
    """
    if not n_both or not n_a or not n_b or not w_a or not w_b:
        return float("nan")
    return (w_both / n_both) / ((w_a / n_a) * (w_b / n_b))


def spearman(xs: list[float], ys: list[float]) -> float:
    """Correlación de rangos. Sirve para medir cuánto se parece un ranking al coste."""
    if len(xs) < 3:
        return float("nan")
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else float("nan")


def _ranks(values: list[float]) -> list[float]:
    """Rangos con empates promediados."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def control_fdr(estimates: list[Estimate], alpha: float = 0.05) -> int:
    """Benjamini-Hochberg sobre todo el ranking. Rellena `q_value` in-place.

    Se corrige por FDR y no por Bonferroni a propósito: con 2 080 contrastes Bonferroni
    exige p < 2,4·10⁻⁵ y deja el informe vacío. La FDR responde a la pregunta útil aquí,
    que es "de los pares que enseño, ¿qué proporción espero que sean ruido".

    Devuelve cuántos quedan por debajo de `alpha`.
    """
    scored = [e for e in estimates if math.isfinite(e.p_value)]
    for estimate in estimates:
        estimate.q_value = math.nan
    if not scored:
        return 0
    scored.sort(key=lambda e: e.p_value)
    total = len(scored)
    # Recorrido de atrás hacia delante para imponer la monotonía de las q.
    running = 1.0
    for rank in range(total, 0, -1):
        estimate = scored[rank - 1]
        running = min(running, estimate.p_value * total / rank)
        estimate.q_value = running
    return sum(1 for e in scored if e.q_value <= alpha)


def z_for_two_sided_p(p: float) -> float:
    """z tal que erfc(z/√2) = p. Por bisección, que sobra para un aviso de potencia."""
    if not 0.0 < p < 1.0:
        return math.inf
    low, high = 0.0, 40.0
    for _ in range(200):
        mid = (low + high) / 2
        if math.erfc(mid / math.sqrt(2)) > p:
            low = mid
        else:
            high = mid
    return (low + high) / 2
