"""Reparto de daño al final del turno.

El daño es un único bote que se reparte libremente (FAQ). Matar un Aliado exige
alcanzar su Defensa en un solo golpe: no hay daño parcial ni acumulación entre turnos.
"""
from __future__ import annotations

from mistsim.domain.player import Player
from mistsim.domain.state import GameState
from mistsim.engine.choices import Chooser
from mistsim.engine.events import EventLog
from mistsim.engine.reactions import Trigger, offer


def resolve_combat(state: GameState, attacker: Player, log: EventLog,
                   chooser: Chooser, agents: list | None = None) -> None:
    """Reparte el daño acumulado.

    `agents` habilita las reacciones fuera de turno (Cloud, y el Cloud de Hide). Si no
    se pasa, el combate se resuelve sin ventana de reacción — es lo que hacen los tests
    que construyen un combate a mano.
    """
    agents = agents or []
    pool = attacker.resources.combat
    if pool <= 0:
        return

    if state.lord_ruler is not None:
        pool = _attack_lord_ruler(state, attacker, pool, log, chooser)
        attacker.resources.combat = pool
        return

    pool = _attack_allies(state, attacker, pool, log, chooser, agents)
    _attack_players(state, attacker, pool, log, chooser, agents)
    attacker.resources.combat = 0


def _attack_allies(state: GameState, attacker: Player, pool: int, log: EventLog,
                   chooser: Chooser, agents: list) -> int:
    """Paso 3: matar Aliados. Los Defender deben caer antes que nada."""
    while pool > 0:
        killable = []
        for opponent in state.opponents(attacker.id):
            defenders = [a for a in opponent.allies if a.card.is_defender]
            # Mientras viva un Defender, el resto de ese rival es intocable.
            reachable = defenders or opponent.allies
            killable += [(opponent, a) for a in reachable if a.card.defense <= pool]
        if not killable:
            break
        chosen = chooser.choose_card([a for _, a in killable], "attack-ally", optional=True)
        if chosen is None:
            break
        owner = next(o for o, a in killable if a is chosen)
        pool -= chosen.card.defense

        # Hide: el dueño puede salvarlo. El daño se gasta igual (texto de la carta).
        if offer(state, Trigger.ALLY_DOOMED, subject=owner.id,
                 amount=chosen.card.defense, agents=agents, log=log, ally=chosen,
                 reactors=[owner.id]):
            log.emit("ally-saved", owner.id, ally=chosen.name, by=attacker.id)
            continue

        owner.allies.remove(chosen)
        owner.discard.append(chosen)
        if chosen.card.ongoing == "extra_metal_burn":
            owner.recompute_burn_limit()
        log.emit("ally-killed", owner.id, ally=chosen.name, by=attacker.id,
                 cost=chosen.card.defense)
    return pool


def _attack_players(state: GameState, attacker: Player, pool: int, log: EventLog,
                    chooser: Chooser, agents: list) -> None:
    """Paso 4: daño a jugadores.

    A 2 jugadores el ataque es opcional y libre. A 3-4, el daño restante DEBE ir a quien
    tenga el Objetivo, que puede pasarlo después de recibir daño ajeno.
    """
    if pool <= 0:
        return
    targets = [p for p in state.opponents(attacker.id) if not p.has_defender()]
    if not targets:
        return

    if state.config.num_players >= 3 and state.target_holder is not None:
        holder = state.player(state.target_holder)
        if holder.id == attacker.id or holder.eliminated or holder.has_defender():
            return
        _damage_player(state, attacker, holder, pool, log, agents)
        if not holder.eliminated:
            # El Objetivo sólo se mueve tras recibir daño de otro, y una vez gastado
            # todo el daño del turno.
            state.target_holder = chooser.choose_player(
                [p.id for p in state.alive() if p.id != holder.id], "pass-target")
            log.emit("target-passed", holder.id, to=state.target_holder)
        else:
            remaining = [p.id for p in state.alive() if p.id != attacker.id]
            state.target_holder = remaining[0] if len(remaining) > 1 else None
        return

    victim_id = chooser.choose_player([p.id for p in targets], "attack-player")
    _damage_player(state, attacker, state.player(victim_id), pool, log, agents)


def _damage_player(state: GameState, attacker: Player, victim: Player, amount: int,
                   log: EventLog, agents: list | None = None) -> None:
    reduction = sum(1 for a in victim.allies if a.card.ongoing == "reduce_damage_taken_by_1")
    # Cloud: cualquiera puede reducir el daño entrante, a sí mismo o a otro.
    if agents:
        reduction += offer(state, Trigger.INCOMING_DAMAGE, subject=victim.id,
                           amount=max(0, amount - reduction), agents=agents, log=log)
    dealt = max(0, amount - reduction)
    victim.take_damage(dealt)
    log.emit("damage", victim.id, amount=dealt, by=attacker.id, health=victim.health)
    if victim.eliminated:
        log.emit("player-eliminated", victim.id, by=attacker.id)


def _attack_lord_ruler(state: GameState, attacker: Player, pool: int, log: EventLog,
                       chooser: Chooser) -> int:
    """En Coop el daño va a escudos de Adversario y al propio Lord Ruler.

    Los escudos caen de izquierda a derecha y cualquier jugador puede pegar a cualquier
    Adversario, esté asignado a quien esté.
    """
    lr = state.lord_ruler
    while pool > 0:
        hit = False
        for adv_id, shields in lr.shields.items():
            if not shields:
                continue
            value = lr.shield_value(shields[0])
            if value <= pool:
                pool -= value
                shields.pop(0)
                hit = True
                log.emit("shield-destroyed", attacker.id, adversary=adv_id, cost=value)
                if not shields:
                    _defeat_adversary(state, adv_id, attacker, log)
                break
        if not hit:
            break

    if pool > 0:
        lr.health = max(0, lr.health - pool)
        log.emit("lord-ruler-damage", attacker.id, amount=pool, health=lr.health)
        pool = 0
        if lr.health == 0:
            state.finished = True
            state.victory_reason = "lord-ruler-defeated"
            log.emit("victory", None, reason="lord-ruler-defeated")
    return pool


def _defeat_adversary(state: GameState, adv_id: str, attacker: Player,
                      log: EventLog) -> None:
    lr = state.lord_ruler
    lr.shields.pop(adv_id, None)
    lr.assigned_to.pop(adv_id, None)
    lr.adversaries = [a for a in lr.adversaries if a["id"] != adv_id]
    log.emit("adversary-defeated", attacker.id, adversary=adv_id)
