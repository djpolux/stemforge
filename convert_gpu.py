# -*- coding: utf-8 -*-
"""Batch stem converter on GPU (Demucs htdemucs CUDA) -> .stem.mp4 files.

Usage: python convert_gpu.py <folder> [--out <out_folder>] [--model htdemucs]
For each audio file in the folder:
  1. Demucs separation (GPU if available) -> 4 stems (drums/bass/other/vocals) wav
  2. master = sum of the 4 (ffmpeg amix, no normalize)
  3. stem_writer.write_stem -> <out>/<name>.stem.mp4
Requires: python (torch + demucs), ffmpeg on PATH (or FFMPEG_PATH env var).
"""
import os, sys, subprocess, argparse, shutil, tempfile, traceback, shutil as _sh

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
FFMPEG = os.environ.get('FFMPEG_PATH') or _sh.which('ffmpeg') or 'ffmpeg'
AUDIO_EXT = ('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wma')

STEM_NAMES = ['drums', 'bass', 'other', 'vocals']

def list_audio(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.lower().endswith(AUDIO_EXT) and not f.lower().endswith('.stem.mp4'))

def sep_dir_of(out, stem_file):
    return os.path.join(out, os.path.splitext(stem_file)[0])

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)
    if r.returncode != 0:
        raise RuntimeError(f'cmd échec ({r.returncode}): {" ".join(cmd)}\n{r.stderr[-2000:]}')
    return r

def make_stem(src, out_folder, model='htdemucs', device='cuda', shifts=1, log=print):
    name = os.path.splitext(os.path.basename(src))[0]
    tmp = tempfile.mkdtemp(prefix='stemsep_')
    log(f'  demucs shifts={shifts} ({device}) : {os.path.basename(src)}')
    try:
        # copie vers un nom interne sans espaces en fin de composant (Windows les strip
        # à la création de dossier -> FileNotFoundError dans demucs sur ce type de nom)
        safe = os.path.join(tmp, 'src' + os.path.splitext(src)[1].lower())
        shutil.copy2(src, safe)
        run([PY, '-m', 'demucs.separate', '-n', model, '-d', device,
             '--shifts', str(shifts), '-o', tmp, safe])
        d = os.path.join(tmp, model, 'src')
        stems = [os.path.join(d, n + '.wav') for n in STEM_NAMES]
        for s in stems:
            if not os.path.isfile(s):
                raise RuntimeError('stem manquant : ' + s)
        master = os.path.join(tmp, f'{name}.master.wav')
        # somme des 4 sans normalisation (piste 5 du format NI)
        inputs = []
        cmd = [FFMPEG, '-y', '-loglevel', 'error']
        for s in stems: cmd += ['-i', s]
        filt = ''.join(f'[{i}:a]' for i in range(4)) + 'amix=inputs=4:normalize=0[m]'
        cmd += ['-filter_complex', filt, '-map', '[m]', '-ac', '2', '-ar', '44100', master]
        run(cmd)
        out_mp4 = os.path.join(out_folder, os.path.basename(src))
        out_mp4 = os.path.splitext(out_mp4)[0] + '.stem.mp4'
        import stem_writer
        stem_writer.write_stem(out_mp4, [master] + stems, stems_json=None)
        log(f'  OK -> {out_mp4} ({os.path.getsize(out_mp4)/1e6:.1f} Mo)')
        return out_mp4
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def convert_folder(folder, out_folder=None, model='htdemucs', device='cuda', log=print, workers=3, shifts=1):
    out_folder = out_folder or folder
    os.makedirs(out_folder, exist_ok=True)
    files = list_audio(folder)
    if not files:
        log('aucun audio dans ' + folder); return []
    log(f'{len(files)} fichier(s) à convertir vers {out_folder} ({workers} workers {device})')

    from concurrent.futures import ThreadPoolExecutor
    res = []
    def one(i_f):
        i, f = i_f
        src = os.path.join(folder, f)
        try:
            log(f'[{i}/{len(files)}] {f}')
            r = make_stem(src, out_folder, model, device, shifts=shifts)
            log(f'  OK {f}')
            return r
        except Exception as e:
            log(f'  ERREUR {f}: {e}')
            return None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, enumerate(files, 1)):
            if r: res.append(r)
    log(f'terminé : {len(res)}/{len(files)} fichiers')
    return res

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('folder'); ap.add_argument('--out', default=None)
    ap.add_argument('--model', default='htdemucs'); ap.add_argument('--device', default='cuda')
    ap.add_argument('--workers', type=int, default=3, help='parallel: 4090 -> 3-4')
    ap.add_argument('--shifts', type=int, default=1, help='0 = 1 passage rapide (3x plus vite que defaut)')
    ap.add_argument('--logfile', default=None, help='log persistant en plus du stdout')
    a = ap.parse_args()
    if a.logfile:
        _lf = open(a.logfile, 'a', buffering=1, encoding='utf-8')
        def log(m):
            print(m, flush=True); _lf.write(f'{m}\n')
    else:
        def log(m): print(m, flush=True)
    convert_folder(a.folder, a.out, a.model, a.device, log=log, workers=a.workers, shifts=a.shifts)
