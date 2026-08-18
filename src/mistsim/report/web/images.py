"""Resuelve el fichero de imagen de cada carta y las copia junto al informe.

Las imágenes se enlazan, no se incrustan como data URI: son ~12 MB en total y meterlas
en el propio HTML infla un único fichero de texto a algo incómodo de abrir. Copiarlas a
una carpeta junto al HTML mantiene todo autocontenido (nada de red, nada de servidor)
sin ese coste — el enunciado deja elegir explícitamente entre las dos formas.
"""
from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from mistsim.content.loader import DATA_DIR

IMAGES_DIR = DATA_DIR / "images"

#: El nombre de fichero no siempre es el nombre de la carta en minúsculas y sin
#: espacios: la transcripción original tiene un par de erratas de tecleo que se
#: quedaron en el nombre del fichero aunque el dato de la carta ya esté corregido.
_FILENAME_OVERRIDES = {
    "Crushing Blow": "cushingblow.png",
    "Maelstrom": "maelstorm.png",
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def image_filename(card_name: str) -> str:
    return _FILENAME_OVERRIDES.get(card_name, card_name.lower().replace(" ", "") + ".png")


def card_image_path(card_name: str) -> Path:
    return IMAGES_DIR / image_filename(card_name)


def png_size(path: Path) -> tuple[int, int] | None:
    """Ancho y alto reales de un PNG, leyendo sólo la cabecera IHDR.

    Sin Pillow a propósito: `mistsim report` se ejecuta con `dependencies = []`
    (ver pyproject.toml) y Pillow es sólo una dependencia de desarrollo, para el
    script de verificación de imágenes contra las cartas físicas. Las cartas de
    Acción son verticales y las de Aliado apaisadas -- sin este dato, el explorador
    de cartas fuerza una proporción vertical a todo y recorta las apaisadas.
    """
    try:
        with open(path, "rb") as fh:
            header = fh.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE:
        return None
    width, height = struct.unpack(">II", header[16:24])
    return width, height


@dataclass(frozen=True)
class ImageRef:
    """Ruta relativa desde el HTML y proporción real de la imagen de una carta."""

    path: str
    width: int | None
    height: int | None


def copy_card_images(card_names: list[str], out_dir: Path) -> dict[str, ImageRef | None]:
    """Copia las imágenes que existan a `out_dir/assets/images/`.

    Devuelve nombre de carta -> `ImageRef` (o `None` si no hay imagen para esa
    carta, para que la página use un marcador de posición en vez de romper un
    `<img>`). `width`/`height` pueden ser `None` si el PNG no se pudo leer aunque
    el fichero exista; la página cae entonces a una proporción por tipo de carta.
    """
    dest_dir = out_dir / "assets" / "images"
    dest_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, ImageRef | None] = {}
    for name in card_names:
        src = card_image_path(name)
        if not src.exists():
            mapping[name] = None
            continue
        dest = dest_dir / src.name
        if not dest.exists() or dest.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dest)
        size = png_size(src)
        mapping[name] = ImageRef(
            path=f"assets/images/{src.name}",
            width=size[0] if size else None,
            height=size[1] if size else None,
        )
    return mapping
