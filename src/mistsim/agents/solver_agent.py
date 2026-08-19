"""IA que juega el turno buscado, no el turno heurístico.

`UtilityAgent` decide acción a acción con una prioridad de fases. Eso resuelve bien el
"qué", pero el turno de Mistborn se gana en el "cuándo": con 1-4 quemas, alimentar una
carta antes que otra cambia lo que rinde la mano entera, y las conversiones sólo capturan
lo acumulado hasta el instante en que se activan. Una heurística por fases no puede ver
eso; una búsqueda sí.

`SolverAgent` planifica el turno COMPLETO en su primera decisión y luego se limita a
ejecutar el plan. Hereda de `UtilityAgent` a propósito: reutiliza sus `Chooser` (qué
carta eliminar, qué opción tomar) y su perfil de estrategia, así que la comparación
entre los dos aísla exactamente una variable —cómo se ordena el turno— en vez de
mezclarla con criterios de compra distintos.
"""
from __future__ import annotations

from collections.abc import Callable

from mistsim.agents.profile import StrategyProfile
from mistsim.agents.tags import Tag, tags_for
from mistsim.agents.utility import UtilityAgent
from mistsim.domain.cards import Card
from mistsim.domain.state import GameState
from mistsim.engine.actions import Action, ActionKind
from mistsim.engine.solver import (
    Objective,
    SolverConfig,
    TurnPlan,
    action_id,
    blended_objective,
    rebind,
    solve_turn,
)

#: Recursos que el objetivo del solver lee del perfil de estrategia.
TRACKED_RESOURCES = ("combat", "mission", "coin", "draw", "heal", "atium")

#: Configuración por defecto del agente: sólo el haz, sin branch-and-bound.
#:
#: MEDIDO, y en contra de lo que uno esperaría: con `exact_nodes=2500` el agente gasta
#: 1 774 nodos por turno en vez de 335 —5,5× más tiempo— y el resultado en liguilla no
#: mejora (67,5% frente a 70,0% en 40 partidas, o sea empate dentro del ruido). Buscar
#: más hondo no da más victorias porque el techo no está en la búsqueda: está en la
#: función de valor, que puntúa el turno aislado y no sabe nada del turno siguiente.
#: Por eso el agente juega con el haz y el B&B queda para `solve_turn`, donde lo que se
#: pide es el mejor turno posible y no la partida más barata.
AGENT_CONFIG = SolverConfig(beam_width=12, exact_nodes=0)


def objective_from_profile(profile: StrategyProfile,
                           card_value: Callable[[Card], float] | None = None) -> Objective:
    """Traduce un `StrategyProfile` al objetivo mezclado que maximiza el solver.

    Es la misma escala de valores que usa `UtilityAgent` para puntuar acciones sueltas
    (`profile.resource_value`), así que las dos IAs quieren lo mismo: sólo cambia cómo
    de lejos miran para conseguirlo.
    """
    weights = {res: profile.resource_value(res) for res in TRACKED_RESOURCES}
    # Coronar una pista es una condición de victoria, no un recurso más: vale mucho
    # incluso para una estrategia que no mira las Misiones, pero se escala con su foco.
    finish_bonus = 25.0 * (0.5 + profile.mission_focus)
    return blended_objective(f"perfil:{profile.name}", weights,
                             card_value=card_value, finish_bonus=finish_bonus)


class SolverAgent(UtilityAgent):
    """Agente que ejecuta el plan de turno del solver, con la heurística de respaldo."""

    def __init__(self, profile: StrategyProfile, seed: int | None = None,
                 config: SolverConfig | None = None) -> None:
        super().__init__(profile, seed=seed)
        self.name = f"solver-{profile.name}"
        self.config = config or AGENT_CONFIG
        self._turn_key: tuple[int, int] | None = None
        self._queue: list[Action] = []
        self._fallback = False
        self._replanned = False
        #: Contadores para poder decir en el informe cuánto se usó de verdad el plan.
        self.stats = {"turnos": 0, "acciones": 0, "respaldos": 0, "replanes": 0,
                      "nodos": 0}

    # --- elección de acción --------------------------------------------------

    def choose_action(self, state: GameState, actions: list[Action]) -> Action:
        key = (state.turn, state.active)
        if key != self._turn_key:
            self._turn_key = key
            self._replanned = False
            self._plan_turn(state)

        legal = {action_id(a) for a in actions}
        while self._queue:
            planned = self._queue.pop(0)
            real = rebind(planned, state)
            if real is not None and action_id(real) in legal:
                self.stats["acciones"] += 1
                return real
            # El estado se ha desviado del que se buscó, y hay una causa legítima: una
            # reacción fuera de turno. Un Sense rival puede vaciar los puntos de Misión
            # a mitad de turno y tumbar la cola entera del plan. Volver a buscar desde
            # el estado real juega mejor que caer a la heurística, así que se
            # replanifica una vez por turno; a la segunda desviación, ya sí, respaldo.
            self._queue.clear()
            if not self._replanned:
                self._replanned = True
                self.stats["replanes"] += 1
                self._search(state)
                continue
            self.stats["respaldos"] += 1
            self._fallback = True

        if self._fallback:
            return super().choose_action(state, actions)
        return Action(ActionKind.END_TURN)

    def _plan_turn(self, state: GameState) -> None:
        self.stats["turnos"] += 1
        self._fallback = False
        self._search(state)

    def _search(self, state: GameState) -> None:
        plan = self.plan(state)
        self._queue = list(plan.actions)
        self.stats["nodos"] += plan.explored

    def plan(self, state: GameState) -> TurnPlan:
        """El plan para el turno actual. Expuesto para poder inspeccionarlo desde el CLI."""
        return solve_turn(state, self.objective(state), config=self.config, chooser=self)

    def objective(self, state: GameState) -> Objective:
        """El objetivo se reconstruye cada turno porque el valor de compra depende de
        lo que ya tienes: la sinergia de una carta cambia con el mazo.

        El valor de compra es EXACTAMENTE el de `UtilityAgent._buy_value`, bonus de
        pánico incluido. Es deliberado: si las dos IAs compraran con criterios
        distintos, la liguilla mediría eso y no lo que se quiere medir, que es el orden
        del turno.
        """
        player = state.player(state.active)
        owned = [inst.card for inst in player.all_cards()]
        panic = player.health <= self.profile.panic_health

        def card_value(card: Card) -> float:
            value = self.profile.card_value(card, owned)
            if panic:
                card_tags = tags_for(card)
                if Tag.DEFENDER in card_tags or Tag.HEAL in card_tags:
                    value += 8.0
            return value

        return objective_from_profile(self.profile, card_value=card_value)


def make(name: str, seed: int | None = None, config: SolverConfig | None = None) -> SolverAgent:
    from mistsim.agents import archetypes
    return SolverAgent(archetypes.get(name), seed=seed, config=config)
