"""Serializa datos para incrustarlos dentro de un `<script>` sin que rompan el HTML."""
from __future__ import annotations

import json
from typing import Any

#: U+2028 / U+2029 -- validos en JSON, pero no dentro de un literal JS de motores
#: antiguos. Se definen con chr() a proposito: como caracteres literales en el fuente
#: son casi indistinguibles de un espacio normal al leer o editar el fichero.
_LINE_SEPARATOR = chr(0x2028)
_PARAGRAPH_SEPARATOR = chr(0x2029)


def embed_json(obj: Any) -> str:
    """JSON compacto y seguro de meter dentro de un `<script>`.

    Una subcadena `</script` en cualquier sitio del texto -da igual el `type` del
    script- cierra la etiqueta para el parser HTML antes de que el JS la vea. Por eso
    se escapa la barra, y de paso U+2028/U+2029 por si el bloque se copia a mano fuera
    de un `<script type="application/json">`.
    """
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return (text.replace("</", "<\\/")
                .replace(_LINE_SEPARATOR, "\\u2028")
                .replace(_PARAGRAPH_SEPARATOR, "\\u2029"))
