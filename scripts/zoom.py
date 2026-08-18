"""Recorta y amplía la zona de habilidades de las cartas para verificarlas a ojo.

Uso:  python scripts/zoom.py [nombre ...]      (sin args: todas)
Salida en /tmp/zoom/<nombre>.png
"""
import os, sys
from PIL import Image

SRC, OUT = "data/images", "/tmp/zoom"


def zoom(name: str, scale: int = 4) -> None:
    im = Image.open(f"{SRC}/{name}.png")
    w, h = im.size
    if h > w:  # Action: la caja de habilidades ocupa la franja inferior.
        crop = im.crop((0, int(h * 0.56), w, h))
    else:      # Ally: apaisado, con coste/defensa arriba y habilidades a la derecha.
        crop = im.crop((int(w * 0.30), 0, w, h))
    crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
    crop.save(f"{OUT}/{name}.png")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    names = sys.argv[1:] or [f[:-4] for f in sorted(os.listdir(SRC)) if f.endswith(".png")]
    for n in names:
        zoom(n)
    print(f"{len(names)} recortes en {OUT}")
