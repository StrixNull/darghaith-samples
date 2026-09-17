# Pitch deck: هَوْنًا إلى الروضة / Hawnan (فكّر للحرمين 2026)

| File | What |
|---|---|
| `build-deck.js` | pptxgenjs generator. Re-run it after any content or layout change. |
| `Hawnan_Fakkir_lilHaramain_2026.pptx` | The 9-slide jury deck it produces (16:9, Arabic, speaker notes on every slide). |
| `talk-track.md` | The 4-minute Arabic talk track, a 60-second elevator version, and 8 likely jury questions with answers. |
| `preview.py` | Renders the deck to `preview/` (PDF, `slide-N.jpg`, `grid.jpg`) for visual QA. |
| `preview/` | Rendered previews. Regenerate, do not edit. |

## Rebuild

```bash
cd haramain-2026/pitch
npm install            # once; installs pptxgenjs into ./node_modules (git-ignored)
node build-deck.js     # writes Hawnan_Fakkir_lilHaramain_2026.pptx
```

The generator sets `LAYOUT_16x9` first, uses hex colours without `#`, builds a fresh options object
for every shape, uses `bullet: true` (never a literal bullet), `isTextBox: true` and `margin: 0` on
every text box, `addNotes()` for the talk track, and Western digits everywhere. After `writeFile()` it
does two small OOXML touches through jszip: a `<c:dPt>` so the "نوافذ متدرجة" bar on slide 7 is gold,
and one right-to-left paragraph per line in the speaker notes.

## Preview and QA

```bash
python3 preview.py               # all slides
python3 preview.py --only 4,7    # re-render only the slides you changed (grid is rebuilt)
```

Needs LibreOffice with the Impress module (`soffice`) and `pip install pymupdf Pillow`. The pptx
skill's `validate.py` should pass with "All validations PASSED!" after every rebuild.

LibreOffice substitutes Arial with a wider Arabic font when it renders, so the preview is slightly
more crowded than PowerPoint will be. Boxes are sized with roughly 10% slack for that. If a line fits
in the preview it fits in PowerPoint.

## Screenshots (slide 6)

Slide 6 draws three device frames with placeholder screens. When the prototype has real screens, drop
PNGs here and rebuild; the generator checks `fs.existsSync` and places the image inside the frame
instead of the drawn placeholder:

| Path (relative to repo) | Frame |
|---|---|
| `haramain-2026/prototype/docs/screenshots/guest-id.png` | Guest phone, Indonesian (right frame) |
| `haramain-2026/prototype/docs/screenshots/guest-ur.png` | Guest phone, Urdu (middle frame) |
| `haramain-2026/prototype/docs/screenshots/staff-tablet.png` | Supervisor tablet, landscape (left frame) |

Portrait phone captures (about 9:19) and a landscape tablet capture (about 4:3) fit best; the image
is placed with `contain`, so other ratios get letterboxed inside the frame.

## Fonts and language

- Everything is Arial: it ships with Office, has Arabic glyphs, and renders true-to-width in QA.
  Do not switch to a decorative Arabic font without re-checking every slide for overflow.
- Arabic boxes carry `rtlMode: true`, `align: 'right'`, `lang: 'ar-SA'`. Numeric cells that contain
  `≥` or `−` are set LTR on purpose: in an RTL paragraph those glyphs get mirrored.
- The only English on the slides is the product lockup "Hawnan". The phone screens on slide 6 show
  Indonesian and Urdu because that is what the demo phones show.
- Team name and university line are constants at the top of `build-deck.js` (`TEAM_NAME`, `TEAM_HOME`).

## Content rules

The slides say nothing beyond `../docs/03-concept.md`: the prototype is a hackathon prototype, the
permit feed is simulated and declared, the chart on slide 7 is labelled as illustrative and is replaced
by calibrated twin output, and slide 8 keeps the "حقيقي / محاكاة معلنة / يحتاج الهيئة" split. Nothing
here is an official Authority product.
