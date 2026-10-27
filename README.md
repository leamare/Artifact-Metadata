# Artifact-Metadata

Repository with common metadata for Artifact, Valve's game

## Rendering card faces

```sh
python3 scripts/extract_assets.py              # needs the Classic and Foundry installs
python3 scripts/render_cards.py foundry        # every Foundry card face -> images/foundry/english/
python3 scripts/render_cards.py reborn --changed
python3 scripts/render_cards.py classic 10001 --lang russian
python3 scripts/render_cards.py classic --scale 2   # 1052x1780 -> images/classic/english@2x/
```

### Cards explorer

```sh
python3 scripts/cards_explorer.py [--game foundry] [--lang russian] [--card 10001]
```

A Qt (PySide6 with QtWebEngine) browser for all three games: a sortable, filterable card
list with mini icons; the rendered face or small preview with its alternate artworks, an
overlay of Valve's render (Classic) and PNG export at any scale; the card's text in the chosen language, its data, related
cards, balance history and chat wheel lines. `ui/index.html` is a simpler card browser in
the web page (`python3 -m http.server -d . 8000`, open `/ui/`).

## Scripts

| Script | |
|---|---|
| `tools/generate.py` | regenerate everything (`--only commons/classic/foundry/reborn/images`): commons and Reborn itself, Classic and Foundry through the two below |
| `tools/gen_classic.py` | Classic (client registry + Valve's card API + community database) and `images/classic.json` |
| `tools/gen_foundry.py` | Foundry (community database + Foundry client), on top of Classic |
| `scripts/update_reborn.py` | regenerate `reborn/` (optionally `--pull` the patch repositories) and `changes.json` |
| `scripts/extract_assets.py` | decode the game's textures, copy fonts and bake the frame into `ui/assets/` |
| `scripts/frame.py` | `fit`: refit the frame and text box lighting on Valve's renders (`scripts/data/frame.json`) |
| `scripts/cards_explorer.py` | the Qt cards explorer |
| `scripts/download_images.py` | download Valve's Classic images |
| `scripts/render_cards.py` | render card faces to PNG |
| `scripts/compare_render.py` | compare renders with Valve's |

The source locations come from `.env` at the repository root