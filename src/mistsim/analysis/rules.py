"""Contraste entre lo que dice la minería y las 13 reglas escritas a mano.

`agents/synergy.py` tiene 13 reglas, cada una justificada por una interacción mecánica
concreta. Son la hipótesis previa; el corpus es el experimento.

Sirve para dos cosas, y la segunda es la interesante:

* **Validar el método.** Si el ranking medido no recupera las sinergias obvias
  (Rebel↔Aliados, Confrontation↔Atium), el método está roto y da igual lo demás.
* **Encontrar los desacuerdos.** Un par que las reglas predicen y el corpus no
  confirma, o al revés, es lo único que este trabajo aporta de nuevo. Ojo: la sinergia
  escrita a mano **guía la compra** del `UtilityAgent`, así que un par predicho aparece
  más veces en el corpus. Eso mueve el soporte, no el contraste de interacción, que se
  calcula dentro del estrato del arquetipo.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mistsim.agents import synergy
from mistsim.content.loader import Content, load_content
from mistsim.domain.cards import Card


def cards_by_name(content: Content | None = None) -> dict[str, Card]:
    return {card.name: card for card in (content or load_content()).market}


def pair_rules(a: Card, b: Card) -> tuple[tuple[str, float], ...]:
    """Reglas que disparan para el par, en las dos direcciones.

    Se reutiliza `synergy.explain` en vez de re-implementar el barrido de reglas: si
    alguien cambia una regla, este contraste la sigue sin tocarlo.
    """
    hits: dict[str, float] = {}
    for candidate, owned in ((a, b), (b, a)):
        for name, value, _why in synergy.explain(candidate, [owned]):
            hits[name] = max(hits.get(name, 0.0), value)
    return tuple(sorted(hits.items(), key=lambda kv: -kv[1]))


def rule_weight(a: Card, b: Card) -> float:
    """Cuánta sinergia le atribuyen al par las reglas escritas a mano, sumada.

    Es lo que el `UtilityAgent` le suma al valor de compra. Sirve para comprobar si hay
    dosis-respuesta: los pares que las reglas puntúan alto deberían medir más que los
    que puntúan bajo. Si no la hay, las reglas aciertan a lo sumo el signo.
    """
    return sum(value for _, value in pair_rules(a, b))


@dataclass(frozen=True)
class RuleCheck:
    """Cómo le fue a una regla escrita a mano frente al corpus."""

    rule: str
    why: str
    #: Pares del ranking a los que la regla se aplica y que llegaron al soporte mínimo.
    measured: int
    #: De ésos, cuántos salen con lift > 1 y con el intervalo excluyendo el 1.
    confirmed: int
    #: Cuántos salen significativamente **en contra** (lift < 1, IC por debajo de 1).
    contradicted: int
    #: Lift mediano de los pares medidos.
    median_lift: float
    #: El par mejor medido, para poder citarlo en el informe.
    best: tuple[str, str] | None
    best_lift: float


def annotate(pairs, content: Content | None = None) -> None:
    """Rellena `PairResult.rules` / `TripleResult.rules` in-place."""
    by_name = cards_by_name(content)
    for result in pairs:
        names: set[str] = set()
        cards = result.cards
        for i in range(len(cards)):
            for j in range(i + 1, len(cards)):
                a, b = by_name.get(cards[i]), by_name.get(cards[j])
                if a is None or b is None:
                    continue
                names.update(name for name, _ in pair_rules(a, b))
        result.rules = tuple(sorted(names))


def check_rules(pairs, content: Content | None = None,
                min_support: int = 30) -> list[RuleCheck]:
    """Una fila por regla escrita a mano: cuántos de sus pares confirma el corpus."""
    by_name = cards_by_name(content)
    buckets: dict[str, list] = {rule.name: [] for rule in synergy.RULES}
    why = {rule.name: rule.why for rule in synergy.RULES}

    for pair in pairs:
        if pair.support < min_support:
            continue
        a, b = by_name.get(pair.cards[0]), by_name.get(pair.cards[1])
        if a is None or b is None:
            continue
        for name, _value in pair_rules(a, b):
            buckets[name].append(pair)

    checks = []
    for name, matched in buckets.items():
        lifts = sorted(p.synergy.lift for p in matched)
        confirmed = sum(1 for p in matched if p.synergy.lift > 1 and p.synergy.ci_low > 1)
        against = sum(1 for p in matched if p.synergy.lift < 1 and p.synergy.ci_high < 1)
        best = max(matched, key=lambda p: p.synergy.lift) if matched else None
        checks.append(RuleCheck(
            rule=name, why=why[name], measured=len(matched), confirmed=confirmed,
            contradicted=against,
            median_lift=lifts[len(lifts) // 2] if lifts else float("nan"),
            best=best.cards if best else None,
            best_lift=best.synergy.lift if best else float("nan")))
    checks.sort(key=lambda c: (-c.measured, c.rule))
    return checks


def undiscovered(pairs, top: int = 25) -> list:
    """Los mejores pares medidos que **ninguna** regla escrita a mano predice."""
    return [p for p in pairs if not p.rules][:top]


# --- grupos mecánicos de pares -----------------------------------------------


def mechanical_groups(content: Content | None = None
                      ) -> dict[str, Callable[[object], bool]]:
    """Agrupaciones de pares con sentido mecánico, para el resumen agregado.

    No son hipótesis nuevas: son las divisiones que cualquiera haría mirando las cartas
    —dos Aliados, dos cartas del mismo metal, una barata y una cara— y que por tener
    cientos de pares dentro sí tienen potencia estadística, al revés que un par suelto.
    """
    by_name = cards_by_name(content)

    def pair_of(result) -> tuple[Card, Card] | None:
        a, b = by_name.get(result.cards[0]), by_name.get(result.cards[1])
        return (a, b) if a and b else None

    def both(test: Callable[[Card], bool]) -> Callable[[object], bool]:
        def check(result) -> bool:
            cards = pair_of(result)
            return bool(cards) and test(cards[0]) and test(cards[1])
        return check

    def one_each(test: Callable[[Card], bool]) -> Callable[[object], bool]:
        def check(result) -> bool:
            cards = pair_of(result)
            return bool(cards) and (test(cards[0]) != test(cards[1]))
        return check

    def shares_metal(result) -> bool:
        cards = pair_of(result)
        return bool(cards) and bool(set(cards[0].metal_pair) & set(cards[1].metal_pair))

    def disjoint_metal(result) -> bool:
        cards = pair_of(result)
        return bool(cards) and not (set(cards[0].metal_pair) & set(cards[1].metal_pair))

    def predicted(result) -> bool:
        return bool(getattr(result, "rules", ()))

    def not_predicted(result) -> bool:
        return not getattr(result, "rules", ())

    return {
        # Fila de referencia: los grupos hay que leerlos CONTRA ésta, no contra 1,00.
        # Si el ranking entero está una pizca por encima de 1, un grupo en 1,01 no dice
        # nada y uno en 0,95 dice bastante.
        "TODOS los pares (referencia)": lambda result: True,
        "dos Aliados": both(lambda c: c.is_ally),
        "un Aliado y una Acción": one_each(lambda c: c.is_ally),
        "dos Acciones": both(lambda c: not c.is_ally),
        "comparten metal": shares_metal,
        "metales disjuntos": disjoint_metal,
        "dos cartas caras (coste ≥ 5)": both(lambda c: c.cost >= 5),
        "dos cartas baratas (coste ≤ 3)": both(lambda c: c.cost <= 3),
        "alguna regla escrita a mano lo predice": predicted,
        "ninguna regla lo predice": not_predicted,
        # Dosis-respuesta: si las reglas midieran bien la intensidad, este grupo debería
        # separarse del anterior. Si no, aciertan el signo pero no la magnitud.
        "las reglas lo puntúan alto (peso ≥ 2)": _weighted(by_name, 2.0),
        "las reglas lo puntúan bajo (0 < peso < 2)": _weighted(by_name, 0.0, 2.0),
    }


def _weighted(by_name: dict[str, Card], low: float,
              high: float = float("inf")) -> Callable[[object], bool]:
    def check(result) -> bool:
        a, b = by_name.get(result.cards[0]), by_name.get(result.cards[1])
        if a is None or b is None:
            return False
        weight = rule_weight(a, b)
        return low <= weight < high if low else 0 < weight < high
    return check
