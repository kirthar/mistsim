"""Log estructurado de eventos.

Todo lo que ocurre pasa por aquí. El CLI, los reportes y el futuro visor web sólo
consumen eventos, nunca hurgan en el estado; y la partida dorada de los tests compara
precisamente esta secuencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    kind: str
    turn: int
    player: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        who = f"P{self.player}" if self.player is not None else "--"
        bits = " ".join(f"{k}={v}" for k, v in self.data.items())
        return f"[T{self.turn:02d} {who}] {self.kind} {bits}".rstrip()


#: Eventos de los que `GameResult` deriva los datos por jugador. Un lote silencioso
#: conserva sólo éstos: bastan para el análisis y dejan fuera el 90% del volumen.
STATS_KINDS = frozenset({"buy", "damage", "mission-advance", "soothe", "eliminate-top"})


class EventLog:
    """Registro de eventos de una partida.

    `keep` filtra qué se almacena. Con `keep=None` se guarda todo, que es lo que quieren
    el log legible y el visor web. Un lote de decenas de miles de partidas pasa
    `keep=STATS_KINDS` y se ahorra la mayor parte del coste sin perder las métricas por
    jugador, que se derivan justo de esos eventos.
    """

    def __init__(self, keep: frozenset[str] | None = None) -> None:
        self.events: list[Event] = []
        self.turn = 0
        self.keep = keep

    def emit(self, kind: str, player: int | None = None, **data: Any) -> None:
        if self.keep is not None and kind not in self.keep:
            return
        self.events.append(Event(kind=kind, turn=self.turn, player=player, data=data))

    def of_kind(self, kind: str) -> list[Event]:
        return [e for e in self.events if e.kind == kind]

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)
