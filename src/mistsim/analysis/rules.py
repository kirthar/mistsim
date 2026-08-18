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
