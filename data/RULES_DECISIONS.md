# Decisiones de reglas

Orden de precedencia usado en todo el proyecto:

1. **El FAQ oficial de Brotherwise** — manda en cualquier conflicto de reglas.
2. **La imagen de la carta** — manda sobre cualquier transcripción, para datos de carta.
3. El manual.
4. Transcripciones previas y guías comunitarias — sólo cuando no hay nada mejor.

Cada decisión está expuesta como flag en `GameConfig`, para poder simular la lectura
alternativa y medir si cambia algo.

---

## 1. Refrescar un metal flareado el mismo turno

**Conflicto.** `metals.json` decía: *"Un metal puede ser flareado, refrescado y usado otra
vez el mismo turno (pero no flareado→refrescado→flareado otra vez)"*.

El FAQ oficial dice lo contrario:

> **Can I refresh a metal I flared this turn?** Yes, but you cannot use it again, even
> after you unflare it.

**Decisión:** manda el FAQ. Refrescar devuelve la ficha a su cara normal, pero esa ficha
**no vuelve a estar disponible este turno**. Refrescar sirve para dejarla lista para el
turno siguiente, no para reciclarla dentro del mismo.

Flag: `GameConfig.refresh_allows_reuse_same_turn = False`.

## 2. Una ficha de metal no se puede flarear si ya se está quemando

> **Metal tokens can only be used once per round and may not be flared if they are already
> being burned.**

**Decisión:** flarear sólo es legal sobre una ficha **sin usar** este turno. Se aplica.

## 3. Atium no se puede flarear

Del FAQ: si has agotado tus quemas de ficha, no puedes quemar el Atium — no hay forma de
saltarse el límite con él. **Decisión:** usar Atium exige una ranura de quema libre.

## 4. Riot no bloquea la activación normal del Aliado

El FAQ recoge una errata que cambió la regla original:

> **Riot** now allows you to activate allies that have been activated regularly by burning
> metal and does not prevent you from activating them for the rest of the turn.

**Decisión:** cada Aliado tiene dos activaciones independientes por turno — una por quema
normal de su metal y otra vía Riot. Riot puede activar Aliados de Atium.

Flag: `GameConfig.riot_grants_extra_activation = True`.

## 5. Las cartas usadas como metal no cuentan contra el límite de quemas

El límite es de **fichas**, no de cartas. No hay tope de cartas jugadas de lado por turno.
Además se puede jugar una carta como metal **sin alimentar ninguna carta**, sólo para
disparar Aliados, habilidad de personaje o el bonus *savant*.

## 6. Los Aliados no refrescan ni alimentan

> **Ally cards can never be used to refresh metal tokens or to power other cards.**

**Decisión:** un Aliado en mano no es una fuente de metal.

## 7. Los efectos se resuelven de inmediato y en orden

> When you play a card and burn a metal for it, you must immediately activate all effects
> of that ability, in order.

Esto tiene una consecuencia que importa para la IA: **`House War` y `Dominate` no pueden
convertir recursos ganados después** de activar su habilidad secundaria, porque la
conversión se resuelve en el instante de activarse. El orden de juego dentro del turno es
por tanto una decisión real, no cosmética.

## 8. La habilidad secundaria exige haber activado antes la primaria

Del manual. **Decisión:** la secundaria (`+N METAL`) sólo es legal si la primaria ya se
activó este turno, y cuesta N quemas **adicionales** del mismo metal.

## 9. Puntos de misión negativos

> You will never move down a Mission track. Negative Mission points just reduce how many
> mission points you have.

**Decisión:** el acumulador de misión del turno puede bajar (mínimo 0 al gastarse), pero la
posición en la pista nunca retrocede.

## 10. Solo/Coop

- **Sense no afecta al Lord Ruler.** Es un efecto sólo contra jugadores.
- El Lord Ruler ataca únicamente a Aliados *Defender* y a los jugadores, nunca a otros
  Aliados, salvo que la carta lo diga.
- En solitario, los efectos dirigidos a *"a different player"* nunca te aplican.
- `2X`, `3X`… multiplican el valor actual de Dominance.

## 11. Combate: un único bote de daño

> All your damage points go to one pool that you may divide how you like between allies,
> adversaries, and the player with the target.

**Decisión:** el daño es un solo acumulador que se reparte al final del turno. Matar a un
Aliado exige alcanzar o superar su Defensa **en un solo golpe**: no hay daño parcial ni se
acumula entre turnos.

## 12. Qué hace SENSE — manda la carta, no el manual

`metals.json`, transcrito del manual, define el keyword así:

> Stops other players from advancing on a Mission Track for the rest of that turn, even
> if they gain more Mission points afterward.

Las dos únicas cartas que llevan SENSE dicen otra cosa, y lo dicen sin ambigüedad:

| Carta | Keyword | Texto impreso |
|---|---|---|
| Spy (62/82) | SENSE 3 | *Play off turn to reduce an opponent's ⟨misión⟩ by 3.* |
| Eavesdrop | SENSE 2 | *Play off turn to reduce an opponent's ⟨misión⟩ by 2.* |

Por el orden de precedencia del proyecto —**FAQ > imagen de la carta > manual**— manda la
carta. **Decisión:** SENSE **recorta N puntos de Misión** del rival; no bloquea la pista.

Consecuencias en el código: se elimina `MissionTrack.sensed` y los tres sitios que lo
consultaban (`legal_actions`, `turn._advance_mission`, `solver.eligible_tracks`). Un
avance que se queda sin puntos por una reacción emite `mission-denied` en vez de ser
ilegal — la acción era legal cuando se eligió.

Sigue valiendo lo de §10: SENSE no afecta al Lord Ruler.

## 13. Las habilidades `off_turn` necesitan una ventana de reacción

Seis cartas —Spy, Eavesdrop, Sneak, Train in Secret, Coppercloud y Hide— tienen su efecto
SENSE o CLOUD **sólo** en `off_turn`: ninguna lo lleva en la primaria ni en la secundaria.
Sin ventana de reacción no hacían nada en absoluto, y con ellas dos de los ocho keywords
de metal no ocurrían jamás.

**Decisión:** hay tres momentos en que se abre ventana (`engine/reactions.py`):

| Disparador | Cuándo | Quién responde |
|---|---|---|
| `MISSION_SPENDING` | primer gasto de Misión del turno activo | los rivales, con SENSE |
| `INCOMING_DAMAGE` | antes de aplicar daño a un jugador | cualquiera, con CLOUD |
| `ALLY_DOOMED` | antes de retirar un Aliado alcanzado | su dueño, con Hide |

Jugar una reacción **no exige quemar metal**: es la habilidad de fuera de turno de la
carta, que sale de la mano al descarte de su dueño.

Dos detalles del texto impreso que cambian el resultado:

- Hide dice *"The attacking ⟨daño⟩ is still spent"*: salvar al Aliado **no** devuelve el
  daño al atacante.
- La ventana de SENSE se abre **una vez por turno**, en el primer intento de gastar. Es
  el instante en que se ve lo que hay que recortar, y deja la mecánica acotada: repartir
  los puntos entre tres pistas no puede costar tres ventanas.
