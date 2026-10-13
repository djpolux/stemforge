# Stem Forge

Batch-convert whole folders of music tracks into **5-stream stem files** (master + drums + bass + other + vocals) that DJ software can load — verified working with **Traktor Pro 4**.

- **Web app** (FastAPI): pick files through the native Windows file dialog (1, 20 or Ctrl+A), launch the batch, watch the live log, stop and resume later — already-converted tracks are skipped.
- **CLI**: convert a folder in one command.
- **GPU or CPU**: automatic device detection (NVIDIA CUDA when available, CPU fallback).
- Engine: [Demucs](https://github.com/facebookresearch/demucs) — Meta's `htdemucs` / `htdemucs_ft` — plus a custom MP4 writer.

> Not affiliated with, endorsed by, or connected to Native Instruments. Use it with music you own. Respect the terms of your DJ software.

## Install (Windows, Python 3.10+)

```bat
git clone https://github.com/<your-account>/stemforge.git
cd stemforge
py -m venv .venv
.venv\Scripts\activate

:: GPU (NVIDIA) — recommended
pip install torch --index-url https://download.pytorch.org/whl/cu121

:: or CPU only
pip install torch

pip install demucs fastapi uvicorn numpy
```

[ffmpeg](https://ffmpeg.org/download.html) must be on `PATH` (or set the `FFMPEG_PATH` environment variable).

## Usage

Web app (opens at http://127.0.0.1:9005):

```bat
python app_stem.py
```

- **📂 Sélectionner des fichiers…** → native Windows dialog: select one file, Ctrl+click several, or Ctrl+A. Click a row to check/uncheck it.
- Bulk actions: Tout / Aucun / Seulement restants / Inverser / filter by name.
- Model choice: `htdemucs` (fast) or `htdemucs_ft` (higher separation quality, ~2x slower).
- Output: by default a `stems\` subfolder next to the source files. Interruptions are safe — relaunch and done tracks are skipped.

CLI:

```bat
python convert_gpu.py "D:\Music\my playlist" [--out D:\stems] [--model htdemucs] [--shifts 1] [--workers 3]
```

## How it works

`demucs.separate` produces the four stems; the master track is their sum; `stem_writer.py`
multiplexes the five AAC-LC 44.1 kHz streams with the manifest (stem names/colors, optional
mastering DSP chain) into a single MP4 file. Speed on an RTX 4090 laptop: ~20 s for a
4.5-minute track (`htdemucs`, 1 pass).

## Credits

- [Demucs](https://github.com/facebookresearch/demucs) (Meta, MIT) — audio separation.
- [ffmpeg](https://ffmpeg.org) — AAC encoding/muxing.
- [FastAPI](https://fastapi.tiangolo.com), [PyTorch](https://pytorch.org).

## License

MIT — see [LICENSE](LICENSE).