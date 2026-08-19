"""Solver de turno óptimo: haz + branch-and-bound sobre `legal_actions`.

El turno de Mistborn es "en cualquier orden y cualquier número de veces", y ahí está la
habilidad real del juego: con 1-4 quemas por turno, el ORDEN decide cuánto rinde la mano.
El motor expone ese espacio (`legal_actions` / `turn.apply`) y este módulo lo recorre.

## Por qué no se busca a lo bruto

Medido sobre este motor (partidas `equilibrado` vs `aggro-combate`, 3 041 pasos):

    profundidad por turno    media 12 pasos
    ramificación por paso    media 15 acciones, máx 33
    espacio bruto del turno  ~15^12 ≈ 10^14
    GameState.clone()        0,08 ms

Así que el buscador se apoya en cuatro reducciones, en este orden:

1. **Fases fuera del árbol.** Repartir puntos de Misión, comprar y refrescar fichas son
   decisiones de *final de turno*: no cambian lo que el resto del turno puede hacer.
   Salen de la búsqueda y se resuelven después, cada una por su cuenta. Sólo
   `advance_mission` llegaba a 24 de las 89 acciones de un paso; `buy` + `buy_boxing` +
   `sell_boxing` + `refresh` suman otra media de 1,9. En conjunto la lista de acciones
   de un paso baja de 22-27 a 11.
2. **Acciones sin rendimiento posible.** Quemar o flarear un metal que no desbloquea
   nada, o jugar una carta de lado como un metal que no alimenta nada, es tirar el
   recurso. `flare` era la acción más numerosa de la lista legal (3,8 por paso) y casi
   siempre es ruido.
3. **Canonicalización de órdenes conmutativos.** Jugar A y luego B da el mismo estado
   que B y luego A, así que se explora sólo una de las dos permutaciones.
   **Excepción real: las conversiones no conmutan.** `House War` (+2 Zinc) convierte
   *todo el combate acumulado hasta ese instante* en Misión, y `Dominate` (+2 Brass)
   hace lo contrario; es un ruling del FAQ ya implementado en `effects.py`. Tratarlas
   como conmutativas produciría secuencias que parecen óptimas y son ilegales o
   simplemente peores. Por eso la poda mira los EFECTOS de cada acción y sólo colapsa
   las que son puros acumuladores.
4. **Transposiciones.** Dos caminos distintos que llegan al mismo estado se funden en
   uno. Esto captura lo que la canonicalización no ve y, sobre todo, mantiene el haz
   lleno de estados *distintos* en vez de doce copias del mismo.

Sobre eso corren DOS pasadas, y hacen falta las dos:

- **Haz** ordenado por `valor + cota optimista`, ancho y barato. Su papel no es acertar
  sino levantar pronto el listón, porque la poda de la segunda pasada corta por
  "cota ≤ mejor conocido" y sin incumbente no corta nada.
- **Branch-and-bound best-first** sobre la misma cota, que mejora el incumbente y —si el
  presupuesto le llega— agota el árbol y DEMUESTRA que no hay mejor turno.

La cota está en `Valuer.potential` y es superior de verdad mientras no entren cartas
nuevas en la mano; `bound_is_admissible` dice cuándo se cumple eso. El haz solo, con la
cota plana de la primera versión, perdía el óptimo en un turno de siete acciones que la
exhaustiva sí encontraba: está en `tests/test_solver.py`.

Y una advertencia medida, para quien venga a subirle la potencia: **buscar más hondo no
da más victorias**. Con `exact_nodes=2500` el agente gasta 5,5× más tiempo por turno y
gana lo mismo en liguilla. El techo no está en la búsqueda sino en la función de valor,
que puntúa el turno aislado y no sabe nada del turno siguiente.
"""
from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace

import mistsim.engine.effects_special  # noqa: F401  (registra los efectos especiales)
from mistsim.domain.cards import Card, CardInstance, Effects
from mistsim.domain.metals import Metal
from mistsim.domain.missions import TRACK_LENGTH, MissionTrack
from mistsim.domain.player import Player
from mistsim.domain.state import GameState
from mistsim.engine import turn as turn_engine
from mistsim.engine.actions import Action, ActionKind, legal_actions
from mistsim.engine.choices import Chooser, GreedyChooser
from mistsim.engine.events import EventLog

#: Acciones que sí se ramifican. El resto son fases de cierre (ver módulo).
SEARCH_KINDS = frozenset({
    ActionKind.PLAY_CARD,
    ActionKind.CARD_AS_METAL,
    ActionKind.BURN,
    ActionKind.FLARE,
    ActionKind.ACTIVATE,
    ActionKind.ACTIVATE_ALLY,
    ActionKind.CHARACTER,
})

#: Orden canónico entre acciones conmutativas. Dos permutaciones de las mismas acciones
#: conmutativas sólo se exploran en el orden creciente de esta clave.
_KIND_ORDER = {
    ActionKind.PLAY_CARD: 0,
    ActionKind.CARD_AS_METAL: 1,
    ActionKind.BURN: 2,
    ActionKind.FLARE: 3,
    ActionKind.ACTIVATE: 4,
    ActionKind.ACTIVATE_ALLY: 5,
    ActionKind.CHARACTER: 6,
}

#: Efectos que son puros acumuladores: no leen el estado ni preguntan al Chooser, así
#: que dos activaciones que sólo contengan estas claves conmutan entre sí.
#:
#: Todo lo demás es sensible al orden por definición: las conversiones porque capturan
#: lo acumulado hasta ese instante; `soothe`/`push`/`pull`/`seek`/`riot` porque eligen
#: sobre zonas que las acciones anteriores han cambiado; y los efectos que leen la
#: posición en las pistas porque dependen de lo que se haya avanzado antes.
COMMUTATIVE_EFFECTS = frozenset({
    "coin", "combat", "mission", "heal", "train", "atium", "draw",
    "cloud", "cloud_protect_ally", "sense",
})

#: Tope duro de nodos expandidos por turno. Un turno normal no se acerca; existe para
#: que una mano patológica no cuelgue la simulación.
MAX_NODES = 20_000


# --- objetivo ----------------------------------------------------------------


@dataclass(frozen=True)
class Objective:
    """Qué se está maximizando.

    `weights` puntúa cada recurso; `card_value` valora una carta del Mercado para la
    fase de compra (el `SolverAgent` le pasa el `StrategyProfile`, pero el motor no
    depende de la capa de agentes: aquí es sólo una función).
    """

    name: str
    weights: Mapping[str, float] = field(default_factory=dict)
    #: Cuánto vale coronar una pista de Misión. Es enorme: coronar las tres gana.
    finish_bonus: float = 25.0
    card_value: Callable[[Card], float] | None = None

    def weight(self, resource: str, default: float = 0.0) -> float:
        return self.weights.get(resource, default)


#: Peso residual de los recursos que no son el objetivo. No es cero para que, a igualdad
#: de objetivo, el solver prefiera el turno que además deja moneda o vida.
EPSILON = 0.05

_PURE = {
    "damage": "combat",
    "mission": "mission",
    "coin": "coin",
}


def objective_for(name: str, card_value: Callable[[Card], float] | None = None) -> Objective:
    """Objetivo puro: maximiza un recurso, con los demás como desempate."""
    if name not in _PURE:
        raise ValueError(f"objetivo desconocido: {name!r}. Disponibles: {sorted(_PURE)}")
    target = _PURE[name]
    weights = {res: EPSILON for res in ("combat", "mission", "coin", "draw", "heal", "atium")}
    weights[target] = 1.0
    return Objective(name=name, weights=weights, card_value=card_value)


def blended_objective(name: str, weights: Mapping[str, float],
                      card_value: Callable[[Card], float] | None = None,
                      finish_bonus: float = 25.0) -> Objective:
    """Objetivo mezclado, para una IA: cada recurso vale lo que diga la estrategia."""
    return Objective(name=name, weights=dict(weights), card_value=card_value,
                     finish_bonus=finish_bonus)


class ObjectiveChooser(GreedyChooser):
    """El `Chooser` por defecto del solver.

    `GreedyChooser` responde a todo con la primera opción, y eso arruina una búsqueda:
    `Steelpush` ofrece "train:1 o combat:3" y la primera opción es la mala, así que el
    solver evaluaba —y jugaba— turnos peores que la heurística en las cartas con
    `choice_of`. Aquí la elección se resuelve con el mismo objetivo que se está
    maximizando, que es lo mínimo coherente.

    Las demás decisiones (qué carta eliminar, a quién atacar) siguen siendo las de
    `GreedyChooser`: un agente que sepa más pasa el suyo, y `SolverAgent` pasa el de
    `UtilityAgent`.
    """

    def __init__(self, objective: Objective) -> None:
        self.objective = objective

    def choose_option(self, options: list[str], context: str) -> str:
        return max(options, key=lambda option: _option_value(self.objective, option))


# --- plan --------------------------------------------------------------------


@dataclass(frozen=True)
class TurnPlan:
    """Una secuencia de acciones legales y lo que rinde.

    Las acciones apuntan a las `CardInstance` del CLON sobre el que se buscó, no a las
    del estado real: `replay` las vuelve a atar por `uid` antes de aplicarlas.
    """

    actions: tuple[Action, ...]
    score: float
    resources: Mapping[str, int] = field(default_factory=dict)
    #: Cuántas acciones vienen de la búsqueda; el resto son las fases de cierre.
    searched: int = 0
    #: Nodos expandidos, para poder medir el efecto de cada poda.
    explored: int = 0
    #: El branch-and-bound agotó el árbol: no existe mejor secuencia. Ver
    #: `bound_is_admissible` para cuándo puede afirmarse eso.
    proven: bool = False

    def __str__(self) -> str:
        head = (f"{self.name_or_empty()} · valor {self.score:.2f} · "
                f"{self.explored} nodos{' · óptimo demostrado' if self.proven else ''}")
        body = "\n".join(f"  {i + 1:2d}. {a}" for i, a in enumerate(self.actions))
        return f"{head}\n{body}" if body else head

    def name_or_empty(self) -> str:
        return f"{len(self.actions)} acciones" if self.actions else "turno vacío"

    def replay(self, state: GameState, log: EventLog, chooser: Chooser) -> int:
        """Aplica el plan sobre un estado real. Devuelve cuántas acciones entraron.

        Se detiene en cuanto una acción deja de ser legal, en vez de forzarla: eso sólo
        puede pasar si el estado ha divergido del que se buscó, y en ese caso lo honesto
        es parar y dejar que el agente vuelva a decidir.
        """
        applied = 0
        for action in self.actions:
            real = rebind(action, state)
            if real is None or not _is_legal(state, real):
                break
            turn_engine.apply(state, real, log, chooser)
            applied += 1
            if state.finished:
                break
        return applied


def rebind(action: Action, state: GameState) -> Action | None:
    """Vuelve a atar una acción del clon a las instancias reales, por `uid`.

    Sin esto, `apply` marcaría `primary_activated` sobre la copia del clon y el estado
    real se quedaría sin enterarse. Es el único punto delicado de aplicar un plan
    buscado sobre otro objeto.
    """
    card = _find_instance(state, action.card) if action.card is not None else None
    payment = _find_instance(state, action.payment) if action.payment is not None else None
    if (action.card is not None and card is None) or \
            (action.payment is not None and payment is None):
        return None
    return replace(action, card=card, payment=payment)


def _find_instance(state: GameState, inst: CardInstance) -> CardInstance | None:
    player = state.player(state.active)
    zones = (player.hand, player.in_play, player.allies, player.discard, player.deck,
             player.set_aside, state.market.row, state.eliminated)
    for zone in zones:
        for candidate in zone:
            if candidate.uid == inst.uid:
                return candidate
    return None


def _is_legal(state: GameState, action: Action) -> bool:
    ident = action_id(action)
    return any(action_id(a) == ident for a in legal_actions(state))


def action_id(action: Action) -> tuple:
    """Identidad de una acción, estable entre un clon y el estado real."""
    return (
        action.kind,
        action.card.uid if action.card is not None else -1,
        action.metal,
        action.tier,
        action.track,
        action.amount,
        action.payment.uid if action.payment is not None else -1,
    )


# --- filtro de acciones ------------------------------------------------------


def candidate_actions(state: GameState) -> list[Action]:
    """Las acciones del árbol de búsqueda: legales, útiles y sin las fases de cierre."""
    player = state.player(state.active)
    out: list[Action] = []
    for action in legal_actions(state):
        if action.kind not in SEARCH_KINDS:
            continue
        if action.kind is ActionKind.BURN:
            if not metal_relevant(state, player, action.metal):
                continue
        elif action.kind is ActionKind.FLARE:
            # Flarear deja la ficha inservible hasta que se refresque, incluso en turnos
            # posteriores. Sólo compensa cuando ya no quedan quemas.
            if player.tokens.burns_used < player.tokens.burn_limit:
                continue
            if not metal_relevant(state, player, action.metal):
                continue
        elif (action.kind is ActionKind.CARD_AS_METAL
                and not action.card.card.savant
                and not metal_relevant(state, player, action.metal)):
            continue
        out.append(action)
    return out


def metal_relevant(state: GameState, player: Player, metal: Metal | None) -> bool:
    """¿Activar este metal desbloquea algo, ahora o tras jugar algo de la mano?"""
    if metal is None:
        return False
    if (str(metal) == player.character.signature_metal
            and "character" not in player.used_once_per_turn):
        return True
    for inst in player.in_play:
        card = inst.card
        if card.primary and card.primary.metal == metal and not inst.primary_activated:
            return True
        if (card.secondary and card.secondary.metal == metal
                and "secondary" not in inst.activations_used):
            return True
    for ally in player.allies:
        card = ally.card
        if card.primary and card.primary.metal == metal and "burn" not in ally.activations_used:
            return True
        if (card.secondary and card.secondary.metal == metal
                and "secondary" not in ally.activations_used):
            return True
    for inst in player.hand:
        card = inst.card
        if card.primary and card.primary.metal == metal:
            return True
    return False


# --- conmutatividad ----------------------------------------------------------


def order_sensitive(action: Action) -> bool:
    """¿Puede esta acción dar un resultado distinto según cuándo se juegue?

    Las conversiones son el caso que obliga a hacer esto bien: sólo capturan lo
    acumulado hasta el instante de activarse.
    """
    if action.kind is ActionKind.CHARACTER:
        return True                      # una sola por turno; no merece afinar más
    for effects in _action_effects(action):
        if any(key not in COMMUTATIVE_EFFECTS for key in effects):
            return True
    return False


def _action_effects(action: Action) -> Iterator[Effects]:
    if action.kind in (ActionKind.ACTIVATE, ActionKind.ACTIVATE_ALLY):
        card = action.card.card
        ability = card.primary if action.tier == "primary" else card.secondary
        if ability is not None:
            yield ability.effects
    elif action.kind is ActionKind.CARD_AS_METAL and action.card.card.savant:
        yield action.card.card.savant


def _sort_key(action: Action) -> tuple:
    return (
        _KIND_ORDER[action.kind],
        action.card.uid if action.card is not None else -1,
        str(action.metal or ""),
        action.tier or "",
    )


# --- firma de estado ---------------------------------------------------------


def signature(state: GameState) -> tuple:
    """Todo lo que distingue dos posiciones del turno del jugador activo.

    Dos caminos con la misma firma son intercambiables de aquí en adelante, así que se
    quedan en uno solo. Incluye el mazo entero porque las cartas que se van a robar
    forman parte de lo que el resto del turno puede hacer.
    """
    player = state.player(state.active)
    res = player.resources
    return (
        res.coin, res.combat, res.mission,
        player.health, player.atium, player.boxings, player.training,
        player.tokens.burns_used, player.tokens.burn_limit,
        tuple(sorted((str(m), str(s)) for m, s in player.tokens.state.items())),
        tuple(sorted(i.uid for i in player.hand)),
        tuple(sorted((i.uid, i.primary_activated, tuple(sorted(i.activations_used)))
                     for i in player.in_play)),
        tuple(sorted((i.uid, i.primary_activated, tuple(sorted(i.activations_used)))
                     for i in player.allies)),
        tuple(i.uid for i in player.deck),
        len(player.discard), len(player.set_aside),
        tuple(i.uid for i in state.market.row),
        tuple(sorted(player.used_once_per_turn)),
        tuple(sorted((str(m), n) for m, n in player.metal_burn_counts.items())),
        tuple(t.position_of(player.id) for t in state.tracks),
        len(state.eliminated),
        state.finished,
    )


# --- valoración --------------------------------------------------------------


def _effects_value(objective: Objective, effects: Effects | None,
                   mission_rate: float | None = None) -> float:
    """Valor de un bloque de efectos.

    `mission_rate` sustituye al peso del recurso "mission" por lo que de verdad rinde un
    punto de Misión en la partida concreta (ver `Valuer.mission_rate`). Sin eso, la cota
    valoraba un punto de Misión a su peso pelado mientras que `Valuer.value` lo valoraba
    por lo que consigue en las pistas, y la cota dejaba de ser superior — con lo que el
    branch-and-bound se cerraba antes de tiempo dando por óptimo un turno que no lo era.
    """
    if not effects:
        return 0.0
    total = 0.0
    for key, amount in effects.items():
        if isinstance(amount, bool):
            total += objective.weight(key, 0.5) if amount else 0.0
        elif isinstance(amount, int):
            if key == "mission" and mission_rate is not None:
                total += mission_rate * amount
            else:
                total += objective.weight(key, 0.3) * amount
        elif isinstance(amount, list):
            total += max((_option_value(objective, opt, mission_rate) for opt in amount),
                         default=0.0)
    return total


def _option_value(objective: Objective, option: str,
                  mission_rate: float | None = None) -> float:
    key, _, raw = option.partition(":")
    amount = int(raw) if raw else 1
    if key == "mission" and mission_rate is not None:
        return mission_rate * amount
    return objective.weight(key, 0.3) * amount


class Valuer:
    """Valora estados para un objetivo, con las tablas caras cacheadas.

    Las dos tablas —cuánto rinde la moneda en el Mercado y cuánto rinden N puntos de
    Misión repartidos entre las pistas— dependen de cosas que casi nunca cambian dentro
    de un turno, así que se calculan una vez y se reutilizan en los miles de nodos.
    """

    def __init__(self, objective: Objective, player_id: int) -> None:
        self.objective = objective
        self.player_id = player_id
        self._buy_cache: dict[tuple, list[float]] = {}
        self._mission_cache: dict[tuple, list[float]] = {}

    # -- moneda -> mejor compra posible ------------------------------------

    def coin_value(self, state: GameState, coin: int) -> float:
        if coin <= 0:
            return 0.0
        key = tuple(i.uid for i in state.market.row)
        table = self._buy_cache.get(key)
        if table is None:
            table = self._buy_table(state)
            self._buy_cache[key] = table
        return table[min(coin, len(table) - 1)]

    def _buy_table(self, state: GameState) -> list[float]:
        """Valor de lo que se compraría con 0..N monedas, con la MISMA regla voraz que
        usa `plan_purchases`. Si la tabla valorara la moneda de una forma y la fase de
        compra gastara de otra, el buscador estaría persiguiendo un dinero que no
        existe."""
        row = list(state.market.row)
        top = sum(i.card.cost for i in row) + 1
        table = [0.0] * (top + 1)
        for coin in range(top + 1):
            budget = coin
            available = list(row)
            total = 0.0
            while True:
                affordable = [i for i in available if i.card.cost <= budget]
                best = max(affordable, key=lambda i: self.card_value(i.card), default=None)
                if best is None or self.card_value(best.card) <= 0:
                    break
                total += self.card_value(best.card)
                budget -= best.card.cost
                available.remove(best)
            table[coin] = total
        return table

    def card_value(self, card: Card) -> float:
        if self.objective.card_value is not None:
            return self.objective.card_value(card)
        value = _effects_value(self.objective, card.primary.effects if card.primary else None)
        value += 0.5 * _effects_value(self.objective,
                                      card.secondary.effects if card.secondary else None)
        if card.is_ally:
            value *= 1.6
        return max(0.0, value - 0.35 * card.cost)

    # -- puntos de misión -> mejor reparto ---------------------------------

    #: Puntos de Misión que se tabulan de una vez. Un turno excepcional pasa de 12; por
    #: encima del tope la tabla se extrapola con el último valor, que ya incluye haber
    #: coronado lo que se pudiera coronar.
    MISSION_TABLE_SIZE = 26

    def _mission_table(self, state: GameState) -> list[float]:
        """Valor del mejor reparto para 0..N puntos, tabulado de una vez.

        Se tabula porque la cota consulta esto en CADA nodo y para varias cantidades:
        resolver la mochila una vez por consulta multiplicaba por diez el coste de la
        búsqueda. La tabla sólo cambia cuando cambia la posición en las pistas, que
        dentro de un turno es casi nunca.
        """
        tracks = eligible_tracks(state)
        key = tuple((idx, track.position_of(self.player_id)) for idx, track in tracks)
        table = self._mission_cache.get(key)
        if table is None:
            table = [best_allocation(self.objective, state, tracks, points)[1]
                     for points in range(self.MISSION_TABLE_SIZE)]
            self._mission_cache[key] = table
        return table

    def mission_value(self, state: GameState, points: int) -> float:
        if points <= 0:
            return 0.0
        table = self._mission_table(state)
        return table[min(points, len(table) - 1)]

    def mission_rate(self, state: GameState, points: int) -> float:
        """Cuánto puede llegar a valer un punto de Misión más, desde aquí.

        Es el máximo de la ganancia MEDIA por punto sobre todos los tamaños de aporte,
        así que `n * rate` es cota superior de lo que rinden n puntos. Sin esto la cota
        valoraba un punto de Misión a su peso pelado mientras `value` lo valoraba por lo
        que consigue en la pista, y una cota que no es superior hace que el
        branch-and-bound cierre antes de tiempo dando por óptimo lo que no lo es.
        """
        table = self._mission_table(state)
        base = table[min(points, len(table) - 1)] if points > 0 else 0.0
        rate = max(
            (table[min(points + k, len(table) - 1)] - base) / k
            for k in range(1, TRACK_LENGTH + 1)
        )
        return max(rate, self.objective.weight("mission", 1.0))

    # -- estado completo ----------------------------------------------------

    def value(self, state: GameState) -> float:
        """Lo que vale el turno si se cerrara aquí.

        Dos decisiones que no son obvias:

        La moneda se valora por lo que COMPRA (`coin_value` consulta la tabla del
        Mercado), no por su cuenta: cinco monedas no valen nada si la carta más barata
        de la fila cuesta seis. Lo mismo los puntos de Misión, que valen lo que consigan
        en las pistas.

        Y no hay ningún término por robar. Lo hubo —`0.2 * len(deck)`— y estaba al
        revés: robar VACÍA el mazo, así que ese término premiaba no robar, y con
        `motor-robo` (peso de robo 3,3) llegaba a penalizar cada carta robada. El valor
        de robar es lo que las cartas nuevas permiten hacer, y eso ya lo cuenta el resto
        de la función cuando se juegan.
        """
        player = state.player(self.player_id)
        if state.finished and state.winner == self.player_id:
            return 1e6
        obj = self.objective
        total = obj.weight("combat") * player.resources.combat
        total += self.mission_value(state, player.resources.mission)
        total += obj.weight("coin", EPSILON) * self.coin_value(state, player.resources.coin)
        total += obj.weight("atium", EPSILON) * player.atium
        total += obj.weight("heal", EPSILON) * player.health * 0.1
        # Los Aliados se quedan en mesa y producen todos los turnos siguientes.
        total += 1.5 * len(player.allies)
        return total

    def potential(self, state: GameState) -> float:
        """Cota optimista de lo que aún puede sacarse del turno.

        No basta con sumar todas las habilidades pendientes: esa cota es la misma para
        todos los nodos —los mismos naipes están ahí en cualquier orden— y un haz
        ordenado por una cota plana degenera en búsqueda voraz, que es justo lo que se
        quería evitar. La primera versión hacía eso y perdía el óptimo en un turno de
        siete acciones que la búsqueda exhaustiva sí encontraba.

        Ésta cuenta el cuello de botella real del turno: **cuántos metales distintos
        quedan por encender**. Una habilidad cuyo metal ya está activo es gratis; las
        demás compiten por las quemas que quedan y por las cartas de la mano que pueden
        jugarse de lado. Con eso la cota BAJA en cuanto un camino desperdicia una quema,
        y se mantiene alta en los que preparan la mesa antes de encenderla.

        Sigue siendo admisible mientras no entren cartas nuevas (robo, Seek, recuperar
        del montón de eliminadas): ninguna secuencia puede activar más metales que
        quemas más cartas tiene, ni sacar de una habilidad más de lo que dice su texto.
        """
        player = state.player(self.player_id)
        obj = self.objective
        rate = self.mission_rate(state, player.resources.mission)
        active = player.metals_active_this_turn
        free = 0.0
        pending: dict[Metal, float] = {}

        def offer(metal: Metal | None, value: float) -> None:
            nonlocal free
            if value <= 0:
                return
            if metal is None or metal in active:
                free += value
            else:
                pending[metal] = pending.get(metal, 0.0) + value

        for inst in player.in_play:
            for metal, value in _pending_abilities(obj, inst, rate=rate):
                offer(metal, value)
        for ally in player.allies:
            for metal, value in _pending_abilities(obj, ally, ally=True, rate=rate):
                offer(metal, value)
        for inst in player.hand:
            # Jugar una carta de la mano no cuesta nada, así que sus DOS habilidades
            # cuentan como alcanzables en cuanto lo sea su metal. Contar sólo la
            # primaria dejaba la cota por debajo del óptimo real —Steelpush guarda
            # "combate 1 + misión 2" en la secundaria— y una cota que no es superior
            # hace que el branch-and-bound se cierre dando por demostrado lo que no es.
            for metal, value in _pending_abilities(obj, inst, rate=rate):
                offer(metal, value)
        if "character" not in player.used_once_per_turn:
            offer(Metal(player.character.signature_metal),
                  _effects_value(obj, player.character.level_1_effects, rate))

        # Cada metal nuevo cuesta una quema o una carta jugada de lado; ni una más.
        budget = max(0, player.tokens.burn_limit - player.tokens.burns_used) + len(player.hand)
        best = sorted(pending.values(), reverse=True)[:budget]
        return free + sum(best)


def _pending_abilities(objective: Objective, inst: CardInstance, ally: bool = False,
                       rate: float | None = None) -> Iterator[tuple[Metal | None, float]]:
    """Habilidades de una carta en mesa que todavía pueden activarse, con su metal."""
    card = inst.card
    used = inst.activations_used
    done_primary = ("burn" in used) if ally else inst.primary_activated
    if card.primary and not done_primary:
        yield card.primary.metal, _effects_value(objective, card.primary.effects, rate)
    if card.secondary and "secondary" not in used:
        yield card.secondary.metal, _effects_value(objective, card.secondary.effects, rate)


#: Efectos que meten cartas nuevas al alcance del turno. Mientras ninguno esté sobre la
#: mesa, `Valuer.potential` es una cota superior de verdad y el branch-and-bound puede
#: DEMOSTRAR que su respuesta es óptima. Con ellos sigue siendo una buena guía, pero
#: deja de ser una cota: una carta robada puede rendir más de lo que la cota preveía.
INFLUX_EFFECTS = frozenset({
    "draw", "draw_per_highest_mission_track", "draw_if_lowest_on_any_mission_track",
    "seek", "seek_two_different_cards", "gain_market_card_to_discard_max_cost",
    "gain_eliminated_card_to_hand", "gain_eliminated_card_to_discard",
    "may_buy_eliminated_card", "play_top_ability_of_eliminated_card",
    "repeat_own_top_ability", "riot",
})


def bound_is_admissible(state: GameState) -> bool:
    """¿Puede la cota garantizarse superior en este turno?

    Sólo si nada de lo que hay al alcance roba, busca en el Mercado o recupera cartas.
    Es la diferencia entre "el solver no encontró nada mejor" y "no hay nada mejor".
    """
    player = state.player(state.active)
    for inst in [*player.hand, *player.in_play, *player.allies]:
        for ability in (inst.card.primary, inst.card.secondary):
            if ability and any(key in INFLUX_EFFECTS for key in ability.effects):
                return False
        if inst.card.savant and any(key in INFLUX_EFFECTS for key in inst.card.savant):
            return False
    return not any(key in INFLUX_EFFECTS for key in player.character.level_1_effects)


# --- fases de cierre ---------------------------------------------------------


def eligible_tracks(state: GameState) -> list[tuple[int, MissionTrack]]:
    """Pistas en las que el jugador activo puede gastar puntos ahora mismo."""
    player = state.player(state.active)
    return [
        (idx, track) for idx, track in enumerate(state.tracks)
        if player.id not in track.sensed and track.finisher != player.id
    ]


#: Lo que vale cruzar una recompensa de Misión POR ENCIMA de lo que dice su texto.
#: Una pista es una carrera: la casilla que se cruza ya no la cruza otro con su bonus
#: de primero, y acerca la victoria instantánea por Misiones. Valorar la recompensa
#: sólo por sus efectos (a menudo `soothe: 2`, que puntúa bajísimo) hacía que el solver
#: repartiera los puntos peor que la heurística, que sí las premia.
MILESTONE_VALUE = 3.0
FIRST_BONUS_VALUE = 2.0


def track_gain(objective: Objective, track: MissionTrack, player_id: int,
               amount: int) -> float:
    """Cuánto vale meter `amount` puntos en esta pista."""
    if amount <= 0:
        return 0.0
    before = track.position_of(player_id)
    after = min(TRACK_LENGTH, before + amount)
    if after == before:
        return 0.0
    gain = objective.weight("mission", 1.0) * (after - before)
    for reward in track.mission.rewards:
        if not (before < reward.position <= after):
            continue
        if (player_id, reward.position) in track.claimed:
            continue
        gain += MILESTONE_VALUE + _effects_value(objective, reward.effects)
        if reward.first_player_bonus and reward.position not in track.first_claimed:
            gain += FIRST_BONUS_VALUE + _effects_value(objective, reward.first_player_bonus)
    if after >= TRACK_LENGTH and track.finisher is None:
        gain += objective.finish_bonus
        gain += _effects_value(objective, track.mission.top_reward)
        gain += _effects_value(objective, track.mission.top_reward_first_bonus)
    return gain


def _allocations(points: int, slots: int) -> Iterator[tuple[int, ...]]:
    """Todos los repartos de hasta `points` puntos entre `slots` pistas."""
    if slots == 1:
        for amount in range(points + 1):
            yield (amount,)
        return
    for amount in range(points + 1):
        for rest in _allocations(points - amount, slots - 1):
            yield (amount, *rest)


def best_allocation(objective: Objective, state: GameState,
                    tracks: Sequence[tuple[int, MissionTrack]],
                    points: int) -> tuple[tuple[int, ...], float]:
    """Mochila exacta del reparto de puntos de Misión.

    Es pequeña de verdad (3 pistas, ≤12 puntos ⇒ 455 repartos), así que se resuelve
    entera en vez de aproximarla: sacarla del árbol de búsqueda no cuesta precisión.
    """
    if not tracks or points <= 0:
        return ((0,) * len(tracks), 0.0)
    player_id = state.active
    best: tuple[int, ...] = (0,) * len(tracks)
    best_key = (0.0, 0)
    for alloc in _allocations(points, len(tracks)):
        value = sum(track_gain(objective, track, player_id, amount)
                    for (_, track), amount in zip(tracks, alloc, strict=True))
        # A igualdad de valor, el reparto que gasta menos: los puntos que sobran de
        # rematar una pista rinden más en la siguiente que tirados en la misma.
        key = (value, -sum(alloc))
        if key > best_key:
            best, best_key = alloc, key
    return best, best_key[0]


def plan_mission_spending(state: GameState, objective: Objective) -> list[Action]:
    """Reparte los puntos de Misión acumulados. Se hace al final del turno a propósito:
    una vez gastados ya no pueden convertirse en combate, así que cualquier conversión
    debe haber ocurrido antes."""
    player = state.player(state.active)
    points = player.resources.mission
    tracks = eligible_tracks(state)
    if points <= 0 or not tracks:
        return []
    alloc, _ = best_allocation(objective, state, tracks, points)
    return [
        Action(ActionKind.ADVANCE_MISSION, track=idx, amount=amount)
        for (idx, _), amount in zip(tracks, alloc, strict=True) if amount > 0
    ]


def plan_purchases(state: GameState, valuer: Valuer) -> list[Action]:
    """Compra con la moneda que sobra, la mejor carta primero.

    Aquí hubo que tragarse una lección medida. La primera versión resolvía la compra
    como una MOCHILA: con 6 cartas en la fila caben las 64 combinaciones, así que
    elegía el conjunto de mayor valor total que cupiera en la moneda. Es óptimo… para
    la métrica equivocada. En un juego de construcción de mazo, dos cartas mediocres
    valen menos que una buena aunque sumen más: además de rendir menos, diluyen el mazo
    y empeoran todas las manos siguientes.

    En liguilla contra `UtilityAgent` (150 partidas, 6 arquetipos) el agente con la
    mochila ganaba el 51,3%; el mismo agente dejándole SÓLO la compra a la heurística
    subía al 60,0%. Todo lo demás del turno era idéntico, así que la diferencia era la
    mochila. Se sustituyó por la compra voraz —la mejor carta que se pueda pagar, y
    otra vez—, que es lo que hacía la heurística.

    Vender un Boxing sólo si con eso se alcanza una compra; comprarlos sólo con la
    calderilla que de otro modo se perdería al acabar el turno.
    """
    player = state.player(state.active)
    coin = player.resources.coin
    boxings = player.boxings
    actions: list[Action] = []
    row = list(state.market.row)

    while True:
        affordable = [i for i in row if i.card.cost <= coin]
        best = max(affordable, key=lambda i: valuer.card_value(i.card), default=None)
        if best is None or valuer.card_value(best.card) <= 0:
            break
        actions.append(Action(ActionKind.BUY, card=best))
        coin -= best.card.cost
        row.remove(best)

    # Vender Boxings sólo cierra el hueco de una compra que ya casi se paga.
    if boxings > 0:
        reachable = [i for i in row if coin < i.card.cost <= coin + boxings]
        best = max(reachable, key=lambda i: valuer.card_value(i.card), default=None)
        if best is not None and valuer.card_value(best.card) > 0:
            sold = best.card.cost - coin
            actions += [Action(ActionKind.SELL_BOXING) for _ in range(sold)]
            actions.append(Action(ActionKind.BUY, card=best))
            coin = 0

    # La moneda que sobra se pierde al acabar el turno; un Boxing la guarda a mitad de
    # precio, que es más que nada.
    actions += [Action(ActionKind.BUY_BOXING) for _ in range(coin // 2)]
    return actions


def plan_refresh(state: GameState) -> list[Action]:
    """Desflarea con las cartas que iban a morir en la mano de todos modos.

    Al final del turno la mano entera va al descarte (`Player.cleanup`), así que pagar
    un refresco con una carta sobrante es GRATIS: recupera una ficha que si no seguiría
    flareada turnos enteros. Es el hueco más claro que dejaba la heurística anterior,
    que puntuaba refrescar por debajo de no hacer nada.
    """
    player = state.player(state.active)
    spare = list(player.hand)
    actions: list[Action] = []
    for metal in player.tokens.flared():
        for inst in spare:
            if metal in inst.card.playable_as_metal():
                actions.append(Action(ActionKind.REFRESH, metal=metal, payment=inst))
                spare.remove(inst)
                break
    return actions


def _step(state: GameState, action: Action, log: EventLog, chooser: Chooser) -> GameState:
    """Clona el estado y aplica ahí la acción, atándola antes al clon.

    Volver a atarla no es cosmético: `apply` marca `primary_activated` y
    `activations_used` SOBRE el objeto de la acción. Si esa acción sigue apuntando a la
    instancia del estado padre, el hijo no se entera de que la habilidad ya se usó —y
    el padre sí—, con lo que el solver "descubre" que puede activar la misma carta
    veinte veces. Pasó de verdad la primera vez que se corrió esto.
    """
    child = state.clone()
    real = rebind(action, child)
    turn_engine.apply(child, real if real is not None else action, log, chooser)
    return child


# --- búsqueda ----------------------------------------------------------------


@dataclass
class _Node:
    state: GameState
    actions: tuple[Action, ...]
    value: float
    bound: float
    last_key: tuple | None = None
    last_sensitive: bool = True
    sibling_ids: frozenset = frozenset()


@dataclass(frozen=True)
class SolverConfig:
    """Cuánto se le deja gastar al buscador y qué podas usa.

    Los campos de poda existen para poder APAGARLAS y medir: un recorte que nadie ha
    medido es una creencia. `mistsim solve --podas` imprime las cuatro combinaciones.
    """

    beam_width: int = 12
    max_depth: int = 24
    #: Tope de nodos del haz.
    max_nodes: int = MAX_NODES
    #: Nodos que puede gastar el branch-and-bound después del haz. 0 lo desactiva.
    exact_nodes: int = 2_500
    #: Desactiva la canonicalización, para poder medir cuánto poda.
    canonical: bool = True
    #: Desactiva la fusión de transposiciones, para lo mismo.
    dedup: bool = True


def _allowed(node: _Node, action: Action, config: SolverConfig) -> bool:
    """Poda por conmutatividad.

    Se descarta la acción si ya estaba disponible antes de la última jugada, su clave
    canónica es menor, y ninguna de las dos es sensible al orden: en ese caso la
    permutación contraria lleva al mismo estado y ya se está explorando.
    """
    if not config.canonical or node.last_key is None:
        return True
    if node.last_sensitive or order_sensitive(action):
        return True
    if _sort_key(action) > node.last_key:
        return True
    return action_id(action) not in node.sibling_ids


def _expand(node: _Node, valuer: Valuer, config: SolverConfig, log: EventLog,
            chooser: Chooser) -> Iterator[_Node]:
    """Los hijos legales de un nodo, ya podados por conmutatividad."""
    options = candidate_actions(node.state)
    ids = frozenset(action_id(a) for a in options)
    for action in options:
        if not _allowed(node, action, config):
            continue
        child_state = _step(node.state, action, log, chooser)
        value = valuer.value(child_state)
        yield _Node(
            state=child_state,
            actions=(*node.actions, action),
            value=value,
            bound=value + valuer.potential(child_state),
            last_key=_sort_key(action),
            last_sensitive=order_sensitive(action),
            sibling_ids=ids,
        )


def _root(state: GameState, valuer: Valuer) -> _Node:
    clone = state.clone()
    value = valuer.value(clone)
    return _Node(state=clone, actions=(), value=value,
                 bound=value + valuer.potential(clone))


def _beam(root: _Node, valuer: Valuer, config: SolverConfig, log: EventLog,
          chooser: Chooser) -> tuple[_Node, int]:
    """Primera pasada: barata y ancha, para tener pronto un buen incumbente.

    No pretende ser óptima —el branch-and-bound viene después—: su papel es levantar
    el listón cuanto antes, porque la poda del B&B corta por `cota <= mejor conocido` y
    sin un incumbente decente no corta nada.
    """
    best = root
    frontier = [root]
    explored = 0
    for _ in range(config.max_depth):
        children: list[_Node] = []
        seen: dict[tuple, _Node] = {}
        for node in frontier:
            for child in _expand(node, valuer, config, log, chooser):
                explored += 1
                if child.value > best.value:
                    best = child
                if config.dedup:
                    key = signature(child.state)
                    previous = seen.get(key)
                    if previous is None or child.bound > previous.bound:
                        seen[key] = child
                else:
                    children.append(child)
                if explored >= config.max_nodes:
                    break
        if config.dedup:
            children = list(seen.values())
        if not children or explored >= config.max_nodes:
            break
        # El haz se ordena por cota optimista: lo que promete, no lo que ya tiene.
        children.sort(key=lambda n: (n.bound, n.value), reverse=True)
        frontier = children[:config.beam_width]
    return best, explored


def _branch_and_bound(root: _Node, incumbent: _Node, valuer: Valuer,
                      config: SolverConfig, log: EventLog,
                      chooser: Chooser) -> tuple[_Node, int, bool]:
    """Segunda pasada: best-first sobre la cota, con el incumbente del haz.

    Se abre siempre el nodo de mayor cota. En cuanto la mejor cota abierta no supera al
    mejor turno ya encontrado, no queda nada mejor por explorar y la búsqueda termina
    **habiendo demostrado** que su respuesta es óptima (dentro del conjunto de acciones
    candidatas). Eso sólo vale mientras la cota sea admisible: ver `bound_is_admissible`.

    Sobre el turno de laboratorio de los tests, el haz solo necesitaba una anchura de
    300 para dar con el óptimo; el B&B lo demuestra en menos nodos que la exhaustiva.
    """
    best = incumbent
    counter = itertools.count()
    heap: list[tuple[float, int, _Node]] = [(-root.bound, next(counter), root)]
    seen = {signature(root.state)}
    explored = 0
    exhausted = True

    while heap:
        if explored >= config.exact_nodes:
            exhausted = False
            break
        negative_bound, _, node = heapq.heappop(heap)
        if -negative_bound <= best.value:
            break                      # ni el nodo más prometedor puede mejorar ya
        if len(node.actions) >= config.max_depth:
            continue
        for child in _expand(node, valuer, config, log, chooser):
            explored += 1
            key = signature(child.state)
            if key in seen:
                continue
            seen.add(key)
            if child.value > best.value:
                best = child
            if child.bound > best.value:
                heapq.heappush(heap, (-child.bound, next(counter), child))

    return best, explored, exhausted


def search_turn(state: GameState, objective: Objective, config: SolverConfig | None = None,
                chooser: Chooser | None = None) -> TurnPlan:
    """Busca la mejor secuencia del turno, sin las fases de cierre.

    Dos pasadas sobre el mismo árbol: haz para tener incumbente, branch-and-bound para
    mejorarlo y, cuando el turno es pequeño, demostrar que ya no hay nada mejor.
    """
    config = config or SolverConfig()
    chooser = chooser or ObjectiveChooser(objective)
    log = EventLog(keep=frozenset())      # el log de la búsqueda no le interesa a nadie
    valuer = Valuer(objective, state.active)

    root = _root(state, valuer)
    best, explored = _beam(root, valuer, config, log, chooser)

    proven = False
    if config.exact_nodes > 0:
        best, exact, exhausted = _branch_and_bound(root, best, valuer, config, log, chooser)
        explored += exact
        proven = exhausted and bound_is_admissible(state)

    return TurnPlan(actions=best.actions, score=best.value,
                    resources=_resources(best.state), explored=explored, proven=proven)


def exhaustive_turn(state: GameState, objective: Objective, max_depth: int = 8,
                    chooser: Chooser | None = None) -> TurnPlan:
    """Búsqueda exhaustiva sobre el MISMO conjunto de acciones candidatas.

    Sin haz, sin canonicalización y sin cota: sólo memoización por estado repetido.
    Es la implementación de referencia contra la que se comprueba el beam search en un
    turno pequeño; en un turno real no termina.
    """
    chooser = chooser or ObjectiveChooser(objective)
    log = EventLog(keep=frozenset())
    valuer = Valuer(objective, state.active)
    best_actions: tuple[Action, ...] = ()
    best_value = valuer.value(state)
    best_state = state
    seen: set[tuple] = set()
    explored = 0

    def walk(node: GameState, actions: tuple[Action, ...], depth: int) -> None:
        nonlocal best_actions, best_value, best_state, explored
        if depth >= max_depth or node.finished:
            return
        for action in candidate_actions(node):
            child = _step(node, action, log, chooser)
            explored += 1
            key = signature(child)
            if key in seen:
                continue
            seen.add(key)
            value = valuer.value(child)
            trail = (*actions, action)
            if value > best_value:
                best_actions, best_value, best_state = trail, value, child
            walk(child, trail, depth + 1)

    walk(state.clone(), (), 0)
    return TurnPlan(actions=best_actions, score=best_value,
                    resources=_resources(best_state), explored=explored)


def _resources(state: GameState) -> dict[str, int]:
    res = state.player(state.active).resources
    return {"coin": res.coin, "combat": res.combat, "mission": res.mission}


# --- entrada pública ---------------------------------------------------------


def solve_turn(state: GameState, objective: str | Objective = "damage",
               config: SolverConfig | None = None, chooser: Chooser | None = None,
               card_value: Callable[[Card], float] | None = None) -> TurnPlan:
    """Encuentra la mejor secuencia de juego para el turno del jugador activo.

    `objective` es "damage", "mission" o "coin", o un `Objective` a medida (que es lo
    que usa `SolverAgent` para maximizar los pesos de su estrategia).

    Devuelve el plan COMPLETO: la secuencia buscada más las fases de cierre —repartir
    los puntos de Misión, comprar y desflarear— resueltas sobre el estado que deja la
    búsqueda, aplicando cada una antes de decidir la siguiente porque las recompensas de
    Misión dan moneda y esa moneda tiene que poder gastarse.

    Sacarlas del árbol no cuesta optimalidad: ninguna de las tres cambia lo que el resto
    del turno podía hacer. Lo que sí es aproximado es cómo se resuelven por dentro —el
    reparto de Misión sí se optimiza entero, la compra es voraz a sabiendas (ver
    `plan_purchases`)—.

    `TurnPlan.searched` dice cuántas acciones vienen de la búsqueda; el resto es cierre.
    """
    if isinstance(objective, str):
        objective = objective_for(objective, card_value=card_value)
    config = config or SolverConfig()
    chooser = chooser or ObjectiveChooser(objective)

    plan = search_turn(state, objective, config, chooser)
    valuer = Valuer(objective, state.active)

    # Las fases de cierre se planifican sobre el estado que deja la búsqueda, aplicando
    # cada una antes de decidir la siguiente: las recompensas de Misión dan moneda, y
    # esa moneda tiene que poder gastarse en la fase de compra.
    log = EventLog(keep=frozenset())
    working = state.clone()
    actions = list(plan.actions)
    for action in actions:
        real = rebind(action, working)
        if real is None:
            break
        turn_engine.apply(working, real, log, chooser)

    resources = _resources(working)
    tail: list[Action] = []
    if not working.finished:
        tail += _apply_phase(working, plan_mission_spending(working, objective), log, chooser)
        # Comprar repone el Mercado, así que puede abrirse una compra mejor: dos rondas.
        for _ in range(2):
            bought = _apply_phase(working, plan_purchases(working, valuer), log, chooser)
            tail += bought
            if not bought:
                break
        tail += _apply_phase(working, plan_refresh(working), log, chooser)

    # El valor del plan es el del estado que deja la BÚSQUEDA, no el del estado final.
    # Las fases de cierre convierten recursos en cosas que `Valuer.value` no puntúa
    # —moneda en cartas compradas, puntos de Misión en posición en la pista—, así que
    # medir después haría parecer que comprar empeora el turno.
    return TurnPlan(actions=(*actions, *tail), score=plan.score,
                    resources=resources, searched=len(actions),
                    explored=plan.explored, proven=plan.proven)


def _apply_phase(state: GameState, actions: Sequence[Action], log: EventLog,
                 chooser: Chooser) -> list[Action]:
    """Aplica una fase de cierre y devuelve las acciones que de verdad entraron."""
    done: list[Action] = []
    for action in actions:
        real = rebind(action, state)
        if real is None or not _is_legal(state, real):
            continue
        turn_engine.apply(state, real, log, chooser)
        done.append(action)
        if state.finished:
            break
    return done
