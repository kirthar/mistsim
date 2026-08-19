"""Agente por utilidad: juega un turno guiado por un perfil de estrategia.

La habilidad real del juego está en el ORDEN dentro del turno: qué metales quemar con
un límite muy escaso, y en qué momento activar las conversiones, que sólo capturan lo
acumulado hasta ese instante. Este agente resuelve ese orden con una heurística por
fases; el solver exhaustivo de la 2ª entrega lo hará de forma óptima sobre el mismo
espacio de acciones.
"""
from __future__ import annotations

import random

from mistsim.agents.profile import StrategyProfile
from mistsim.agents.tags import Tag, tags_for
from mistsim.domain.cards import Card, CardInstance
from mistsim.domain.missions import TRACK_LENGTH
from mistsim.domain.state import GameState
from mistsim.engine.actions import Action, ActionKind
from mistsim.engine.game import Agent
from mistsim.engine.reactions import Trigger, contribution

#: Prioridad de fase. Jugar y activar antes de comprar, porque las monedas salen de
#: activar; y gastar la misión al final, cuando ya no puede convertirse en combate.
#:
#: PLAY_CARD y CARD_AS_METAL van a la MISMA altura a propósito. Son la decisión más
#: delicada del turno: con 1-2 quemas por ficha, la mayor parte de la mano sólo puede
#: activarse gastando otras cartas de lado como metal. Si jugar boca arriba tuviera
#: prioridad, el agente vaciaría la mano antes de plantearse la alternativa y se
#: quedaría sin combustible — que es justo el error que cometía.
#: BURN va por encima de PLAY_CARD, pero sólo cuando de verdad desbloquea algo: una
#: quema con rendimiento 0 se puntúa aparte, por debajo de jugar una carta.
PHASE = {
    ActionKind.PLAY_CARD: 60,
    ActionKind.CARD_AS_METAL: 60,
    ActionKind.BURN: 80,
    ActionKind.ACTIVATE_ALLY: 75,
    ActionKind.CHARACTER: 72,
    ActionKind.ACTIVATE: 70,
    ActionKind.FLARE: 40,
    ActionKind.REFRESH: 35,
    ActionKind.BUY: 30,
    ActionKind.BUY_BOXING: 10,
    ActionKind.SELL_BOXING: 5,
    ActionKind.ADVANCE_MISSION: 20,
    ActionKind.END_TURN: 0,
}


#: Lo que cuesta reaccionar, medido en "un hueco de mano". Una reacción tira la carta
#: al descarte sin llegar a jugarla, y ese coste no se lee en su valor de compra: las
#: seis cartas de fuera de turno tienen el texto entero en `off_turn`, así que el
#: valuador las puntúa casi a cero. Sin este suelo la política reacciona siempre.
REACTION_CARD_COST = 3.0


class UtilityAgent(Agent):
    def __init__(self, profile: StrategyProfile, seed: int | None = None) -> None:
        self.profile = profile
        self.name = profile.name
        self.rng = random.Random(seed)

    # --- elección de acción --------------------------------------------------

    def choose_action(self, state: GameState, actions: list[Action]) -> Action:
        scored = [(self._score(state, a), i, a) for i, a in enumerate(actions)]
        best_score, _, best = max(scored)
        # Terminar el turno sólo si nada más aporta.
        if best_score <= 0:
            return Action(ActionKind.END_TURN)
        return best

    def _score(self, state: GameState, action: Action) -> float:
        base = PHASE.get(action.kind, 0)

        if action.kind is ActionKind.END_TURN:
            return 0.0

        if action.kind is ActionKind.PLAY_CARD:
            card = action.card.card
            # Un Aliado se queda en mesa y produce todos los turnos: siempre vale.
            if card.is_ally:
                return base + 12.0
            # Una Acción sólo sirve si vas a poder alimentarla. Ponerla en mesa sin
            # metal que la active es tirarla: acaba en el descarte sin hacer nada.
            return base + self._playability(state, card)

        if action.kind is ActionKind.BURN:
            # Quemar un metal que no desbloquea nada es tirar la quema del turno, y sólo
            # hay 1-4. Por eso una quema sin rendimiento cae por debajo de jugar cartas:
            # primero se pone la mesa, después se enciende.
            payoff = self._metal_payoff(state, action.metal)
            if payoff <= 0:
                return 1.0
            return base + 3.0 * payoff

        if action.kind is ActionKind.CARD_AS_METAL:
            # No consume quema y no tiene tope, así que es la vía principal para
            # activar cosas cuando las fichas se acaban. Se paga descartando la
            # carta, así que se resta lo que habría valido jugarla.
            payoff = self._metal_payoff(state, action.metal)
            savant = self._effects_value(action.card.card.savant or {})
            lost = self._playability(state, action.card.card) * 0.5
            return base + 4.0 * payoff + 1.5 * savant - lost

        if action.kind in (ActionKind.ACTIVATE, ActionKind.ACTIVATE_ALLY):
            return base + self._ability_value(state, action)

        if action.kind is ActionKind.CHARACTER:
            return base + 4.0

        if action.kind is ActionKind.FLARE:
            # Flarear sólo compensa si el metal desbloquea algo de verdad, porque
            # deja la ficha inservible hasta que la refresques.
            payoff = self._metal_payoff(state, action.metal)
            return base + 4.0 * payoff - 3.0 if payoff > 0 else -1.0

        if action.kind is ActionKind.REFRESH:
            return base - 1.0

        if action.kind is ActionKind.BUY:
            return base + self._buy_value(state, action.card)

        if action.kind is ActionKind.BUY_BOXING:
            # Un Boxing es sólo un almacén de media moneda; el último recurso.
            return base - 5.0

        if action.kind is ActionKind.SELL_BOXING:
            missing = self._cheapest_gap(state)
            return base + (6.0 if missing == 1 else -5.0)

        if action.kind is ActionKind.ADVANCE_MISSION:
            return base + self._mission_value(state, action)

        return base

    # --- valoraciones --------------------------------------------------------

    def _playability(self, state: GameState, card: Card) -> float:
        """Cuánto vale poner esta Acción en mesa, según lo cerca que esté de activarse."""
        if card.primary is None:
            return 1.0
        player = state.player(state.active)
        metal = card.primary.metal
        value = self._effects_value(card.primary.effects)
        if metal is None:
            return value
        if metal in player.metals_active_this_turn:
            return value                      # se activa ya
        if player.tokens.can_burn(metal):
            return value * 0.8                # queda una quema para ella
        # Todavía podría alimentarse con otra carta de lado, pero cuesta una carta.
        has_fuel = any(metal in inst.card.playable_as_metal() for inst in player.hand)
        return value * (0.45 if has_fuel else 0.1)

    def _metal_payoff(self, state: GameState, metal) -> float:
        """Cuánto desbloquea quemar este metal ahora mismo."""
        player = state.player(state.active)
        payoff = 0.0
        for inst in player.in_play:
            if inst.card.primary and inst.card.primary.metal == metal \
                    and not inst.primary_activated:
                payoff += self._effects_value(inst.card.primary.effects)
        for ally in player.allies:
            if ally.card.primary and ally.card.primary.metal == metal \
                    and "burn" not in ally.activations_used:
                payoff += self._effects_value(ally.card.primary.effects)
        if (str(metal) == player.character.signature_metal
                and "character" not in player.used_once_per_turn):
            payoff += self._effects_value(player.character.level_1_effects)
        return payoff

    def _ability_value(self, state: GameState, action: Action) -> float:
        ability = (action.card.card.primary if action.tier == "primary"
                   else action.card.card.secondary)
        value = self._effects_value(ability.effects)
        # Las conversiones sólo capturan lo ya acumulado: espera a tenerlo.
        player = state.player(state.active)
        if "convert_all_mission_to_combat" in ability.effects:
            value += 1.5 * player.resources.mission - 4.0
        if "convert_all_combat_to_mission" in ability.effects:
            value += 1.5 * player.resources.combat - 4.0
        return value

    def _effects_value(self, effects) -> float:
        total = 0.0
        for key, amount in effects.items():
            if isinstance(amount, int):
                total += self.profile.resource_value(key) * amount
            elif amount is True:
                total += 2.0
        return total

    def _owned_cards(self, state: GameState) -> list[Card]:
        player = state.player(state.active)
        return [inst.card for inst in player.all_cards()]

    def _buy_value(self, state: GameState, inst: CardInstance) -> float:
        player = state.player(state.active)
        value = self.profile.card_value(inst.card, self._owned_cards(state))

        # Con poca vida, defenderse pasa por delante de cualquier plan.
        if player.health <= self.profile.panic_health:
            card_tags = tags_for(inst.card)
            if Tag.DEFENDER in card_tags or Tag.HEAL in card_tags:
                value += 8.0
        return value

    def _mission_value(self, state: GameState, action: Action) -> float:
        """Cuánto vale meter puntos en esta pista concreta."""
        player = state.player(state.active)
        track = state.tracks[action.track]
        position = track.position_of(player.id)
        value = 3.0 * self.profile.mission_focus * action.amount

        # Rematar una pista es enorme: acerca la victoria instantánea por Misiones.
        if position + action.amount >= 12:
            value += 25.0
        # Cruzar una recompensa vale más que quedarse a un paso.
        for reward in track.mission.rewards:
            if position < reward.position <= position + action.amount:
                value += 4.0
                if reward.position not in track.first_claimed:
                    value += 3.0
        return value

    def _cheapest_gap(self, state: GameState) -> int:
        """A cuántas monedas está la compra más barata que aún no puedo pagar."""
        player = state.player(state.active)
        gaps = [inst.card.cost - player.resources.coin
                for inst in state.market.row
                if inst.card.cost > player.resources.coin]
        return min(gaps) if gaps else 99

    # --- Chooser: decisiones internas de los efectos -------------------------

    def choose_option(self, options: list[str], context: str) -> str:
        def value(option: str) -> float:
            key, _, raw = option.partition(":")
            return self.profile.resource_value(key) * (int(raw) if raw else 1)
        return max(options, key=value)

    def choose_card(self, candidates: list, context: str, optional: bool = False):
        if not candidates:
            return None
        # Al eliminar cartas propias, fuera las peores; en todo lo demás, las mejores.
        if context.startswith(("soothe", "eliminate", "forced-eliminate",
                               "forced-discard", "set-aside")):
            return min(candidates, key=self._instance_value)
        if context.startswith("eliminate-top?"):
            worst = min(candidates, key=self._instance_value)
            return worst if self._instance_value(worst) < 2.0 else None
        return max(candidates, key=self._instance_value)

    def _instance_value(self, inst) -> float:
        card = getattr(inst, "card", inst)
        return self.profile.card_value(card, [])

    def choose_player(self, candidates: list[int], context: str) -> int:
        return candidates[0]

    def choose_amount(self, maximum: int, context: str) -> int:
        return maximum

    # --- reacciones fuera de turno -------------------------------------------

    def choose_reaction(self, state: GameState, options: list, context):
        """Decide si gastar una carta de la mano durante el turno de otro.

        El listón tiene que ser alto: la carta se va al descarte sin llegar a jugarse,
        así que reaccionar cuesta un hueco de mano entero. Sólo compensa cuando lo que
        se evita vale más que jugarla en tu turno — que es casi nunca, salvo si el golpe
        es letal o el rival está a punto de coronar una Misión.
        """
        best, best_net = None, 0.0
        for inst in options:
            net = self._reaction_gain(state, inst, context) - self._reaction_cost(inst)
            if net > best_net:
                best, best_net = inst, net
        return best

    def _reaction_cost(self, inst) -> float:
        """Lo que se pierde por gastar esta carta fuera de turno.

        NO es su valor de compra. `card_value` mide cuánto quieres TENER la carta, y en
        estas seis ese valor viene precisamente del texto de fuera de turno: cobrárselo
        como coste sería cobrar dos veces por lo mismo, y con `muro-defender` hacía que
        Hide nunca salvara a nadie. Lo que de verdad se pierde es el hueco de mano más
        lo que la carta habría hecho en tu propio turno.
        """
        card = getattr(inst, "card", inst)
        on_turn = 0.0
        for ability in (card.primary, card.secondary):
            if ability is not None:
                on_turn += self._effects_value(ability.effects)
        return REACTION_CARD_COST + max(0.0, on_turn)

    def _reaction_gain(self, state: GameState, inst, context) -> float:
        trigger = context.trigger
        gained = contribution(inst, trigger)
        if trigger is Trigger.ALLY_DOOMED:
            return self._save_ally_gain(state, context)
        if trigger is Trigger.INCOMING_DAMAGE:
            return self._prevent_damage_gain(state, context, gained)
        if trigger is Trigger.MISSION_SPENDING:
            return self._deny_mission_gain(state, context, gained)
        return 0.0

    def _save_ally_gain(self, state: GameState, context) -> float:
        """Un Aliado se queda en mesa turno tras turno: vale más que una carta suelta."""
        ally = context.ally
        if ally is None:
            return 0.0
        gain = 1.5 * self._instance_value(ally)
        # El último Defender es lo que impide que el daño llegue a la cara.
        reactor = state.player(context.reactor)
        if ally.card.is_defender and sum(1 for a in reactor.allies
                                         if a.card.is_defender) == 1:
            gain += 6.0
        return gain

    def _prevent_damage_gain(self, state: GameState, context, reduced: int) -> float:
        subject = state.player(context.subject)
        blocked = min(reduced, context.amount)
        if blocked <= 0:
            return 0.0
        if context.reactor != context.subject:
            # Cubrir a otro sólo tiene sentido en equipo, y sólo si le salva la vida.
            if state.lord_ruler is None or context.amount < subject.health:
                return 0.0
            return 25.0 if blocked >= context.amount - subject.health + 1 else 0.0
        if context.amount >= subject.health:
            # Letal: si el bloqueo llega para sobrevivir, no hay nada que valga más.
            return 40.0 if blocked > context.amount - subject.health else 3.0 * blocked
        if subject.health - context.amount <= self.profile.panic_health:
            return 3.0 * blocked
        return 0.8 * blocked

    def _deny_mission_gain(self, state: GameState, context, cut: int) -> float:
        """Recortar al rival vale por lo que le impide cruzar, no por los puntos."""
        subject = state.player(context.subject)
        cut = min(cut, context.amount)
        if cut <= 0:
            return 0.0
        gain = 1.0 * cut
        for track in state.tracks:
            if track.finisher is not None:
                continue
            position = track.position_of(subject.id)
            with_points = position + context.amount
            without = position + context.amount - cut
            if with_points >= TRACK_LENGTH > without:
                gain += 20.0          # le quita la corona de la pista
            elif any(without < r.position <= with_points for r in track.mission.rewards):
                gain += 4.0           # le quita una recompensa intermedia
        return gain


def make(name: str, seed: int | None = None) -> UtilityAgent:
    from mistsim.agents import archetypes
    return UtilityAgent(archetypes.get(name), seed=seed)
