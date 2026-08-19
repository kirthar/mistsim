"""Convierte el log de eventos en algo que un humano pueda leer turno a turno."""
from __future__ import annotations

from mistsim.engine.events import Event, EventLog

#: Cómo se cuenta cada evento. {} se rellena con los datos del evento.
TEMPLATES: dict[str, str] = {
    "game-start": "Partida {mode} a {players} jugadores — {characters}\n  Misiones: {missions}",
    "turn-start": "entrenamiento {training}, salud {health}",
    "card-played": "juega {card}",
    "ally-played": "despliega al Aliado {ally}",
    "card-as-metal": "usa {card} de lado como {metal}",
    "burn": "quema {metal}",
    "flare": "FLAREA {metal}",
    "refresh": "refresca {metal} descartando {paid}",
    "activate": "activa {card} ({tier})",
    "character-ability": "habilidad de {character} por {metal}",
    "savant": "savant de {card}: {effects}",
    "buy": "COMPRA {card} por {cost}",
    "seek": "Seek sobre {card} (límite {limit})",
    "riot": "Riot activa a {ally}",
    "soothe": "elimina {card} de su mazo",
    "push": "Push elimina {card} del Mercado",
    "pull": "Pull mueve {count} carta(s) al tope del mazo",
    "draw": "roba {count}",
    "heal": "cura {amount}",
    "train": "avanza {steps} en Entrenamiento (total {total})",
    "convert": "convierte {amount} de {frm} en {to}",
    "mission-advance": "avanza en {track}: {frm} -> {to}",
    "mission-reward": "recompensa de {track} en {position}",
    "mission-first-bonus": "BONUS de primer jugador en {track}@{position}",
    "mission-completed": "COMPLETA la Misión {track}",
    "permanent-gained": "gana permanente: {effect} +{value} (total {total})",
    "ally-killed": "mata a {ally} de P{owner}",
    "damage": "hace {amount} de daño a P{victim} (le queda {health})",
    "player-eliminated": "ELIMINA a P{victim}",
    "target-passed": "pasa el Objetivo a P{to}",
    "burn-limit": "límite de quemas ahora {limit}",
    "adversary-revealed": "aparece el Adversario {adversary} (escudos {shields})",
    "edict": "Edicto: {edict}",
    "dominance": "Dominance sube a {to}",
    "lord-ruler-heal": "el Lord Ruler se cura {amount} (queda {health})",
    "lord-ruler-damage": "golpea al Lord Ruler por {amount} (queda {health})",
    "shield-destroyed": "destruye un escudo de {adversary}",
    "adversary-defeated": "DERROTA al Adversario {adversary}",
    "victory": "VICTORIA ({reason})",
    "defeat": "DERROTA ({reason})",
    "turn-end": "termina con {hand} cartas",
}

#: Eventos que sólo estorban en la lectura normal.
NOISY = {"turn-end", "seek-empty", "sense-noop", "effect-skipped"}

#: Eventos que registra el jugador que los SUFRE, pero que ocurren en el turno del que
#: los causa. Se muestran en el bloque del atacante para que el turno se lea seguido.
ATTRIBUTED_TO_ACTOR = {"damage", "ally-killed", "player-eliminated"}


def describe(event: Event) -> str:
    if event.kind in ATTRIBUTED_TO_ACTOR:
        # El evento lleva a la víctima en `player`; las plantillas la nombran
        # explícitamente, así que se pasa como dato.
        data = {"victim": event.player, "owner": event.player, **event.data}
        template = TEMPLATES.get(event.kind, "")
        try:
            return template.format(**data)
        except (KeyError, IndexError):
            return event.kind

    template = TEMPLATES.get(event.kind)
    if template is None:
        bits = " ".join(f"{k}={v}" for k, v in event.data.items())
        return f"{event.kind} {bits}".strip()
    try:
        return template.format(**event.data)
    except (KeyError, IndexError):
        return event.kind


def render(log: EventLog, *, verbose: bool = False) -> str:
    """Log completo, agrupado por turno y jugador."""
    lines: list[str] = []
    current: tuple[int, int | None] | None = None

    for event in log:
        if event.kind in NOISY and not verbose:
            continue
        if event.kind == "game-start":
            lines.append(describe(event))
            lines.append("")
            continue

        # Un evento causado por el jugador activo se queda en su bloque aunque lo
        # registre la víctima; si no, el turno se parte en trozos ilegibles.
        actor = event.data.get("by") if event.kind in ATTRIBUTED_TO_ACTOR else None
        owner = actor if actor is not None else event.player

        key = (event.turn, owner)
        if key != current:
            current = key
            who = f"P{owner}" if owner is not None else "--"
            lines.append(f"── Turno {event.turn} · {who} ──")
        lines.append(f"   {describe(event)}")

    return "\n".join(lines)


def summary(result) -> str:
    """Resumen final de una partida."""
    lines = [""]
    if result.winner is not None:
        lines.append(f"Gana P{result.winner} por {result.reason} en {result.turns} turnos.")
    else:
        lines.append(f"Fin por {result.reason} tras {result.turns} turnos.")
    lines.append("Salud final: " + ", ".join(
        f"P{pid}={hp}" for pid, hp in sorted(result.final_health.items())))
    for track, positions in result.mission_positions.items():
        marks = ", ".join(f"P{p}={v}/12" for p, v in sorted(positions.items()))
        lines.append(f"  {track}: {marks or 'sin avances'}")
    return "\n".join(lines)
