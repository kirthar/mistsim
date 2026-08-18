# Correcciones de `market_cards.json` frente a las imágenes

**30 correcciones sobre 25 de las 65 cartas.** Cada campo se re-derivó
de un recorte ampliado ×4/×5 de la imagen de la carta (`scripts/zoom.py`). La imagen manda.

## Por qué se colaron estos errores

Las imágenes son de 300×402 px. A ese tamaño hay tres confusiones sistemáticas, y los 30
errores caen casi todos en ellas:

1. **El número va *dentro* del glifo de espadas.** A tamaño original se pierde, y el
   transcriptor tomó el número del keyword contiguo (`PUSH 1`, `PULL 1`) como si fuera el
   combate. De ahí que Assassinate, Crash, Lurcher, Precise Shot y Rescue tuvieran todos
   combate 1.
2. **Cuadrado (misión) contra círculo (moneda).** Ambos son dorados y del mismo tamaño.
   Afecta a Lookout, Steelpush, Train in Secret e Infiltrate.
3. **`+2 METAL` leído como `+METAL`.** La cabecera de la habilidad secundaria lleva el
   número de quemas adicionales; siete cartas lo tenían como 1 cuando imprimen 2.

Los *savant* (el bonus del vial lateral, que sólo se aplica al jugar la carta de lado como
metal) faltaban directamente en 8 cartas.

## Tabla de correcciones

| Carta | Campo | Antes | Ahora | Motivo |
|---|---|---|---|---|
| Ascendant | `secondary.extra_burns` | `1` | `2` | la carta imprime "+2 IRON" |
| Assassinate | `primary.effects.combat` | `1` | `3` | las espadas muestran 3, no 1 |
| Coppercloud | `primary.effects.coin` | _(ausente)_ | `1` | moneda 1 omitida en el JSON |
| Crash | `primary.effects.combat` | `1` | `2` | las espadas muestran 2, no 1 |
| Crash | `savant` | _(ausente)_ | `{"combat": 2}` | savant omitido (el vial muestra combate 2) |
| Cushing Blow | `name` | `Cushing Blow` | `Crushing Blow` | el nombre impreso es "Crushing Blow" |
| Cushing Blow | `secondary.extra_burns` | `1` | `2` | la carta imprime "+2 PEWTER" |
| Dominate | `secondary.extra_burns` | `1` | `2` | la carta imprime "+2 BRASS" |
| Eavesdrop | `savant` | _(ausente)_ | `{"coin": 1}` | savant omitido |
| Hide | `savant` | _(ausente)_ | `{"combat": 2}` | savant omitido |
| House War | `primary.effects.combat` | _(ausente)_ | `2` | combate 2 omitido en el JSON |
| House War | `secondary.extra_burns` | `1` | `2` | la carta imprime "+2 ZINC" |
| Hyperaware | `secondary.extra_burns` | `1` | `2` | la carta imprime "+2 TIN" |
| Infiltrate | `primary.effects` | `{"mission": 2, "coin": 2}` | `{"combat": 2, "coin": 2}` | el primer glifo es espadas, no misión |
| Infiltrate | `secondary.effects` | `{"mission": 2}` | `{"combat": 1, "mission": 2}` | combate 1 omitido |
| Lookout | `primary.effects` | `{"coin": 2}` | `{"mission": 2}` | glifo cuadrado (misión), no círculo (moneda) |
| Lurcher | `primary.effects.combat` | `1` | `2` | las espadas muestran 2, no 1 |
| Maelstrom | `secondary.extra_burns` | `1` | `2` | la carta imprime "+2 STEEL" |
| Noble | `defense` | `3` | `2` | el escudo muestra 2, no 3 |
| Pacify | `savant` | _(ausente)_ | `{"train": 1}` | savant omitido |
| Precise Shot | `primary.effects.combat` | `1` | `3` | las espadas muestran 3, no 1 |
| Pursue | `savant` | _(ausente)_ | `{"mission": 1}` | savant omitido |
| Reposition | `savant` | _(ausente)_ | `{"combat": 1}` | savant omitido |
| Rescue | `primary.effects.combat` | `1` | `3` | las espadas muestran 3, no 1 |
| Soar | `savant` | _(ausente)_ | `{"mission": 1}` | savant omitido |
| Steelpush | `primary.effects` | `{"train_or_combat_choice": 1}` | `{"choice_of": ["train:1", "combat:3"]}` | es una elección entrenamiento/combate, con valores 1 y 3 |
| Steelpush | `secondary.effects` | `{"combat": 1, "coin": 2}` | `{"combat": 1, "mission": 2}` | glifo cuadrado (misión), no círculo (moneda) |
| Strategize | `secondary.effects` | `{"choice_of": ["train:1", "combat:3", "coin:5", "heal:5"]}` | `{"choice_of": ["train:1", "combat:4", "mission:3", "heal:5", "coin:5"]}` | faltaba la opción de misión y el combate es 4, no 3 |
| Strike | `savant` | _(ausente)_ | `{"heal": 1}` | savant omitido |
| Train in Secret | `primary.effects` | `{"choice_of": ["train:1", "combat:2", "coin:2", "heal:3"]}` | `{"choice_of": ["train:1", "combat:2", "mission:2", "heal:3"]}` | glifo cuadrado (misión), no círculo (moneda) |

## Comprobación de integridad del set

Cada carta lleva impreso su número `N/82` abajo a la derecha. Leídos los 65:

- 65 números distintos, todos en el rango 1–82.
- Quedan **17 huecos** en la numeración.
- Hay exactamente **17 cartas con `copies: 2`**.

Los dos números cuadran: 65 nombres + 17 segundas copias = 82 cartas físicas. Esto confirma
que el set está completo y que el campo `copies` es correcto.

## Lo que sigue sin verificar

El vial de **Spy** (62/82) muestra un savant cuyo glifo (una flecha hacia arriba sobre una
carta) no aparece en ninguna otra carta del set, así que no se ha podido interpretar con
seguridad y se ha dejado fuera en vez de adivinarlo. Es el único campo del Mercado que
queda pendiente.
