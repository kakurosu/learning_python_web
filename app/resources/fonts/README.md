# Bundled fonts

Place modern variable / static fonts here to upgrade the look of the app.
Any `.ttf` or `.otf` file in this directory is loaded automatically at
startup by `app/main.py:_load_bundled_fonts`, after which the QSS in
`theme.py` picks them up via the font-family fallback chain.

## Recommended set

For the cleanest Linear / Vercel aesthetic:

| Role | Font | License | Download |
|------|------|---------|----------|
| Sans (UI body / titles) | **Inter Variable** | OFL | https://github.com/rsms/inter/releases — `InterVariable.ttf` |
| Sans display alt | **Geist Sans** | OFL | https://github.com/vercel/geist-font/releases |
| Monospace (code / numerals) | **JetBrains Mono** | OFL | https://github.com/JetBrains/JetBrainsMono/releases |
| Japanese glyphs | **Noto Sans JP** (Variable) | OFL | https://fonts.google.com/noto/specimen/Noto+Sans+JP |

Minimum recommended for a noticeable upgrade:
1. `InterVariable.ttf` (~700 KB)
2. `JetBrainsMono-Regular.ttf` and `JetBrainsMono-Bold.ttf`

## Installation

1. Download the `.ttf` files from the links above.
2. Drop them into this directory:
   ```
   app/resources/fonts/
   ├── InterVariable.ttf
   ├── JetBrainsMono-Regular.ttf
   └── JetBrainsMono-Bold.ttf
   ```
3. Restart the app (`uv run python -m app.main`).

If no fonts are present, the app silently falls back to the OS defaults
(Segoe UI / Yu Gothic UI on Windows, SF Pro on macOS). The look is fine
but won't match the Linear-style design intent.

## Why bundling helps

PyQt6 uses whatever font is installed on the host OS. `Inter` is not
shipped with Windows or macOS, so the QSS `font-family: "Inter", ...`
rule silently falls through to `Segoe UI Variable` (Windows 11) or
`Segoe UI` (Windows 10) which give the typical "business app" look.

By loading Inter via `QFontDatabase.addApplicationFont()` we make the
font available even when it isn't installed system-wide. No registry
edits, no admin rights, no per-machine setup.
