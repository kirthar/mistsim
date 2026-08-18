"""Bucle de partida: enlaza turnos, agentes, combate y condiciones de victoria."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import mistsim.engine.effects_special  # noqa: F401  (registra los efectos especiales)
from mistsim.content.loader import Content, load_content
from mistsim.domain.state import GameConfig, GameState
from mistsim.engine import combat, lord_ruler, setup, turn
from mistsim.engine.actions import Action, ActionKind, legal_actions
from mistsim.engine.choices import Chooser, GreedyChooser
from mistsim.engine.events import EventLog

#: Tope de acciones por turno. Un turno legal real nunca se acerca; existe para que un
#: agente con un bucle patológico falle ruidosamente en vez de colgar la simulación.
MAX_ACTIONS_PER_TURN = 400


@dataclass
class GameResult:
    winner: int | None
    reason: str
    turns: int
    log: EventLog
    final_health: dict[int, int] = field(default_factory=dict)
    mission_positions: dict[str, dict[int, int]] = field(default_factory=dict)

    @property
    def players_won(self) -> bool:
        """En Coop se gana o se pierde en equipo."""
        return self.reason in ("lord-ruler-defeated", "confrontation")


class Agent(Chooser):
    """Lo que el motor espera de una estrategia.

    Un agente elige acciones del espacio legal y, como `Chooser`, resuelve las
    decisiones internas de los efectos.
    """

    name: str = "agent"

    def choose_action(self, state: GameState, actions: list[Action]) -> Action:
        raise NotImplementedError


class GameEngine:
    def __init__(self, content: Content | None = None, config: GameConfig | None = None,
                 seed: int | None = None) -> None:
        self.content = content or load_content()
        self.config = config or GameConfig()
        self.rng = random.Random(seed)
        self.log = EventLog()

    def run(self, agents: list[Agent], characters: list[str] | None = None) -> GameResult:
        if characters is None:
            characters = self._pick_characters(len(agents))
        state = setup.new_game(self.content, self.config, characters, self.rng, self.log)

        while not state.finished and state.turn < self.config.max_turns:
            state.turn += 1
            self.log.turn = state.turn
            for player in state.players:
                if state.finished:
                    break
                if player.eliminated:
                    continue
                state.active = player.id
                self._play_turn(state, player, agents[player.id])
                if state.finished:
                    break
                if state.lord_ruler is not None:
                    lord_ruler.resolve_challenge(state, player, self.log, agents[player.id])
            self._check_victory(state)

        return self._result(state)

    def _play_turn(self, state: GameState, player, agent: Agent) -> None:
        turn.start_turn(state, player, self.log)

        for _ in range(MAX_ACTIONS_PER_TURN):
            actions = legal_actions(state)
            action = agent.choose_action(state, actions)
            if action.kind is ActionKind.END_TURN:
                break
            turn.apply(state, action, self.log, agent)
            if state.finished:
                return
        else:
            self.log.emit("turn-truncated", player.id, reason="límite de acciones")

        combat.resolve_combat(state, player, self.log, agent)
        turn.end_turn(state, player, self.log)

    def _check_victory(self, state: GameState) -> None:
        if state.finished:
            return

        # Coronar las 3 pistas activas gana la partida al instante.
        for player in state.alive():
            if all(t.finisher == player.id for t in state.tracks):
                state.winner = player.id
                state.victory_reason = "all-missions"
                state.finished = True
                self.log.emit("victory", player.id, reason="all-missions")
                return

        alive = state.alive()
        if state.lord_ruler is not None:
            if not alive:
                state.finished = True
                state.victory_reason = "all-players-eliminated"
                self.log.emit("defeat", None, reason="all-players-eliminated")
            elif not state.lord_ruler.deck:
                state.finished = True
                state.victory_reason = "lord-ruler-deck-empty"
                self.log.emit("defeat", None, reason="lord-ruler-deck-empty")
        elif len(alive) == 1 and len(state.players) > 1:
            state.winner = alive[0].id
            state.victory_reason = "last-standing"
            state.finished = True
            self.log.emit("victory", alive[0].id, reason="last-standing")

    def _result(self, state: GameState) -> GameResult:
        reason = state.victory_reason
        if reason is None:
            # Se agotaron los turnos: gana quien más lejos haya llegado en las Misiones,
            # con la salud como desempate.
            reason = "turn-limit"
            if state.lord_ruler is None and state.alive():
                best = max(state.alive(),
                           key=lambda p: (sum(t.position_of(p.id) for t in state.tracks),
                                          p.health))
                state.winner = best.id

        return GameResult(
            winner=state.winner,
            reason=reason,
            turns=state.turn,
            log=self.log,
            final_health={p.id: p.health for p in state.players},
            mission_positions={
                t.mission.name: dict(t.positions) for t in state.tracks
            },
        )

    def _pick_characters(self, count: int) -> list[str]:
        """Reparte personajes distintos, sin mezclar las dos variantes de Vin."""
        pool = [c.id for c in self.content.characters if not c.promo]
        return self.rng.sample(pool, count)


class RandomAgent(GreedyChooser, Agent):
    """Elige al azar. Sirve de suelo contra el que medir a los demás."""

    name = "random"

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)

    def choose_action(self, state: GameState, actions: list[Action]) -> Action:
        # Terminar pronto y a menudo, para que la partida avance.
        if self.rng.random() < 0.15:
            return Action(ActionKind.END_TURN)
        return self.rng.choice(actions)
