# Leyenda de símbolos de carta (derivada de las imágenes)

| Símbolo | Significado |
|---|---|
| Círculo grande arriba-derecha (Action) | Coste |
| Ally (horizontal): nº izquierda / nº derecha | Defensa / Coste |
| **Cuadrado redondeado tostado** + nº | Puntos de misión |
| **Círculo dorado** + nº | Monedas |
| **Campana/escudo** + nº | Avance de Entrenamiento (train) |
| **Espadas cruzadas rojas** + nº | Combate (daño) |
| Etiqueta `PUSH n` / `PULL n` / `SOOTHE n` / `SEEK n` | Keyword + valor |
| Cabecera secundaria `+METAL` | extra_burns = 1 |
| Cabecera secundaria `+2 METAL` / `+3 METAL` | extra_burns = 2 / 3 |
| Vial lateral derecho | metal_pair (metales como los que puede jugarse de lado) |
| Nº dentro del vial | bonus **savant** (solo al usar la carta como metal) |
| Plantilla Ally | "IF YOU ARE BURNING… / AND ALSO… +METAL" |
| Nº abajo-derecha | número de carta `N/82` |

**Convención clave confirmada:** `+METAL` sin número = 1 quema adicional. El JSON original
codificó como `1` varias cartas que imprimen `+2`, que es el error sistemático detectado.

## Aviso de lectura

Las imágenes son de 300×402 px. A tamaño original el cuadrado de misión y el círculo de
moneda se confunden, y los números **dentro** del glifo de espadas se pierden. Toda la
verificación se hizo sobre recortes ampliados ×4/×5 (`scripts/zoom.py`). Varios de los
errores del JSON original son exactamente de este tipo: número de combate leído como el
número del keyword, y misión leída como moneda.
