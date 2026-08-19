"""Bucle de partida: enlaza turnos, agentes, combate y condiciones de victoria."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from mistsim.content.loader import Content, load_content
from mistsim.domain.state import GameConfig, GameState
from mistsim.engine import combat, lord_ruler, setup, turn
from mistsim.engine.actions import Action, ActionKind, legal_actions
from mistsim.engine.choices import Chooser, GreedyChooser
from mistsim.engine.events import EventLog

#: Motivos de fin de partida que cuentan como victoria del equipo en Solo/Coop.
TEAM_WIN_REASONS = frozenset({"lord-ruler-defeated", "confrontation"})

#: Tope de acciones por turno. Un turno legal real nunca se acerca; existe para que un
#: agente con un bucle patológico falle ruidosamente en vez de colgar la simulación.
MAX_ACTIONS_PER_TURN = 400


@dataclass
class PlayerResult:
    """Qué hizo cada jugador, derivado del log UNA sola vez al cerrar la partida.

    Existe para que el análisis posterior (optimizador, minería de combos, informes) no
    tenga que re-escanear el log cada uno a su manera y llegar a números distintos.
    """

    player_id: int
    strategy: str
    character: str
    won: bool
    rank: int
    final_health: int
    purchases: list[str] = field(default_factory=list)
    damage_dealt: int = 0
    damage_taken: int = 0
    mission_points_spent: int = 0
    tracks_topped: int = 0
    cards_eliminated: int = 0
    training: int = 0


@dataclass
class GameResult:
    winner: int | None
    reason: str
    turns: int
    log: EventLog
    #: Modo de la partida ("pvp" / "coop"). Se persiste para que el análisis pueda
    #: estratificar por él sin tener que deducirlo del motivo de fin.
    mode: str = "pvp"
    num_players: int = 0
    final_health: dict[int, int] = field(default_factory=dict)
    mission_positions: dict[str, dict[int, int]] = field(default_factory=dict)
    players: list[PlayerResult] = field(default_factory=list)

    @property
    def players_won(self) -> bool:
        """En Coop se gana o se pierde en equipo."""
        return self.reason in ("lord-ruler-defeated", "confrontation")

    def player(self, pid: int) -> PlayerResult:
        return self.players[pid]


class Agent(Chooser):
    """Lo que el motor espera de una estrategia.

    Un agente elige acciones del espacio legal y, como `Chooser`, resuelve las
    decisiones internas de los efectos.
    """

    name: str = "agent"

    def choose_action(self, state: GameState, actions: list[Action]) -> Action:
        raise NotImplementedError

    # `choose_reaction` lo hereda de Chooser: por defecto no se reacciona nunca, que es
    # lo correcto para un agente que no tiene una política propia. Ver engine.reactions.


class GameEngine:
    def __init__(self, content: Content | None = None, config: GameConfig | None = None,
                 seed: int | None = None, log: EventLog | None = None) -> None:
        self.content = content or load_content()
        self.config = config or GameConfig()
        self.rng = random.Random(seed)
        #: Pasar un EventLog con `keep` filtrado permite correr lotes grandes sin
        #: construir el log completo. Ver EventLog.STATS_KINDS.
        self.log = log if log is not None else EventLog()
        #: Se rellena en `run()`; sin él no hay ventana de reacción.
        self._agents: list[Agent] = []

    def run(self, agents: list[Agent], characters: list[str] | None = None) -> GameResult:
        # Las reacciones fuera de turno las juegan los RIVALES del jugador activo, así
        # que el turno necesita la lista entera, no sólo el agente de turno. Va en el
        # motor y no en la firma de `_play_turn` para no romper a quien la sobrescribe.
        self._agents = agents
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

        return self._result(state, agents)

    def _play_turn(self, state: GameState, player, agent: Agent) -> None:
        turn.start_turn(state, player, self.log)

        for _ in range(MAX_ACTIONS_PER_TURN):
            actions = legal_actions(state)
            action = agent.choose_action(state, actions)
            if action.kind is ActionKind.END_TURN:
                break
            turn.apply(state, action, self.log, agent, self._agents)
            if state.finished:
                return
        else:
            self.log.emit("turn-truncated", player.id, reason="límite de acciones")

        combat.resolve_combat(state, player, self.log, agent, self._agents)
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

    def _result(self, state: GameState, agents: list[Agent]) -> GameResult:
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
            mode=str(state.config.mode),
            num_players=state.config.num_players,
            final_health={p.id: p.health for p in state.players},
            mission_positions={
                t.mission.name: dict(t.positions) for t in state.tracks
            },
            players=self._player_results(state, agents),
        )

    def _player_results(self, state: GameState, agents: list[Agent]) -> list[PlayerResult]:
        """Un recorrido único del log para repartir las métricas entre jugadores."""
        # En Coop se gana o se pierde en equipo, así que `won` no depende del asiento.
        team_won = state.lord_ruler is not None and state.victory_reason in TEAM_WIN_REASONS

        stats = {
            p.id: PlayerResult(
                player_id=p.id,
                strategy=getattr(agents[p.id], "name", "?"),
                character=p.character.id,
                won=team_won or state.winner == p.id,
                rank=0,
                final_health=p.health,
                tracks_topped=sum(1 for t in state.tracks if t.finisher == p.id),
                training=p.training,
            )
            for p in state.players
        }

        for event in self.log:
            data = event.data
            if event.kind == "buy" and event.player is not None:
                stats[event.player].purchases.append(data["card"])
            elif event.kind == "damage":
                if event.player in stats:
                    stats[event.player].damage_taken += data.get("amount", 0)
                dealer = data.get("by")
                if dealer in stats:
                    stats[dealer].damage_dealt += data.get("amount", 0)
            elif event.kind == "mission-advance" and event.player is not None:
                # Eavesdrop avanza sin gastar puntos, así que no siempre hay "spent".
                stats[event.player].mission_points_spent += data.get("spent", 0)
            elif event.kind in ("soothe", "eliminate-top") and event.player is not None:
                stats[event.player].cards_eliminated += 1

        # Puesto: el ganador primero; el resto por progreso de Misión y salud.
        def sort_key(pr: PlayerResult):
            progress = sum(t.position_of(pr.player_id) for t in state.tracks)
            return (pr.player_id == state.winner, progress, pr.final_health)

        for rank, pr in enumerate(sorted(stats.values(), key=sort_key, reverse=True), 1):
            pr.rank = rank
        return [stats[p.id] for p in state.players]

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
