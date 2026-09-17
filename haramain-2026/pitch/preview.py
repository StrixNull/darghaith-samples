#!/usr/bin/env python3
"""Render the deck for visual QA: preview/Hawnan...pdf, preview/slide-N.jpg and preview/grid.jpg.

Usage:  python3 preview.py [deck.pptx] [--dpi 110] [--only 3,6]
Needs:  LibreOffice (soffice with the Impress module), PyMuPDF (pip install pymupdf), Pillow.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DECK = HERE / "Hawnan_Fakkir_lilHaramain_2026.pptx"
OUT = HERE / "preview"


def to_pdf(deck: Path) -> Path:
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile:
        cmd = [
            "soffice",
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--headless", "--norestore",
            "--convert-to", "pdf", "--outdir", str(OUT), str(deck),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    pdf = OUT / (deck.stem + ".pdf")
    if not pdf.exists():
        sys.exit(f"LibreOffice did not produce {pdf}\n{res.stdout}\n{res.stderr}")
    return pdf


def render(pdf: Path, dpi: int, only: set[int] | None) -> list[Path]:
    import pymupdf  # PyMuPDF

    doc = pymupdf.open(pdf)
    paths = []
    for i, page in enumerate(doc, start=1):
        if only and i not in only:
            continue
        pix = page.get_pixmap(dpi=dpi)
        p = OUT / f"slide-{i}.jpg"
        pix.save(p, jpg_quality=90)
        paths.append(p)
    return paths


def grid(cols: int = 3, width: int = 420) -> Path:
    from PIL import Image, ImageDraw

    files = sorted(OUT.glob("slide-*.jpg"), key=lambda p: int(p.stem.split("-")[1]))
    if not files:
        sys.exit("no slide-*.jpg to grid")
    thumbs = []
    for f in files:
        im = Image.open(f).convert("RGB")
        im = im.resize((width, round(im.height * width / im.width)))
        thumbs.append((int(f.stem.split("-")[1]), im))
    th = thumbs[0][1].height
    pad, label = 16, 22
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (width + pad) + pad, rows * (th + label + pad) + pad), "white")
    d = ImageDraw.Draw(sheet)
    for k, (n, im) in enumerate(thumbs):
        x = pad + (k % cols) * (width + pad)
        y = pad + (k // cols) * (th + label + pad)
        d.text((x, y + 2), f"slide {n}", fill="black")
        sheet.paste(im, (x, y + label))
        d.rectangle([x - 1, y + label - 1, x + width, y + label + th], outline="#888888")
    out = OUT / "grid.jpg"
    sheet.save(out, quality=88)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", nargs="?", default=str(DEFAULT_DECK))
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--only", help="comma-separated slide numbers to re-render (grid is rebuilt from all)")
    a = ap.parse_args()
    only = {int(s) for s in a.only.split(",")} if a.only else None
    pdf = to_pdf(Path(a.deck).resolve())
    pages = render(pdf, a.dpi, only)
    g = grid()
    print("\n".join(str(p) for p in pages))
    print(g)


if __name__ == "__main__":
    main()
