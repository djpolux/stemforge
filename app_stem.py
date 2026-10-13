# -*- coding: utf-8 -*-
"""Traktor Stem Forge — UI web directe (FastAPI).

Clic sur une ligne = tout de ligne cochée/décochée. Boutons de masse. Filtre.
Multi-batch GPU/CPU, reprise après interruption.
"""
import os, time, json, threading, traceback
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles  # noqa
import uvicorn
import convert_gpu

HERE = os.path.dirname(os.path.abspath(__file__))
RECENTS = os.path.join(HERE, 'app_recents.json')
app = FastAPI(title='Traktor Stem Forge')
S = {'stop': False, 'running': False, 'log': [], 'files': [], 'rows': [], 'folder': None}

def load_recents():
    try: return json.load(open(RECENTS, encoding='utf-8'))
    except Exception: return []

def push_recent(folder):
    if not folder or not os.path.isdir(folder): return
    r = load_recents()
    r = [folder] + [x for x in r if x != folder][:7]
    try: json.dump(r, open(RECENTS, 'w', encoding='utf-8'))
    except Exception: pass

def detect_device():
    try:
        import torch
        if torch.cuda.is_available(): return 'cuda', torch.cuda.get_device_name(0)
    except Exception: pass
    return 'cpu', 'CPU'

def stem_out(folder, out=None):
    return out if out else os.path.join(folder, 'stems')

@app.get('/api/scan')
def api_scan(folder: str = '', out: str = ''):
    if not folder or not os.path.isdir(folder):
        return {'files': [], 'recents': load_recents()}
    o = stem_out(folder, out or None)
    rows = []
    for f in convert_gpu.list_audio(folder):
        st = 'done' if os.path.exists(os.path.join(o, os.path.splitext(f)[0] + '.stem.mp4')) else 'todo'
        sz = os.path.getsize(os.path.join(folder, f)) / 1e6
        rows.append({'name': f, 'size': f'{sz:.1f} Mo', 'status': st})
    S['files'] = rows; S['folder'] = folder
    return {'files': rows, 'recents': load_recents()}

@app.get('/api/scanpaths')
def api_scanpaths(p: str = ''):
    import urllib.parse
    paths = [x.strip() for x in p.split('|') if x.strip()]
    rows = []
    for fp in paths:
        d = os.path.dirname(fp); n = os.path.basename(fp)
        try: sz = f'{os.path.getsize(fp)/1e6:.1f} Mo'
        except Exception: sz = '?'
        st = 'done' if os.path.exists(os.path.join(d, 'stems', os.path.splitext(n)[0] + '.stem.mp4')) else 'todo'
        rows.append({'file': fp, 'dir': d, 'name': n, 'size': sz, 'status': st})
    S['files'] = rows; S['folder'] = None
    print(f'[TRACE] scanpaths -> {len(rows)} fichier(s)', flush=True)
    return {'files': rows}

@app.get('/api/recents')
def api_recents(): return {'recents': load_recents()}

def run_grouped(groups, model, shifts, workers):
    S.update(stop=False, running=True, log=[], res=[])
    log = lambda m: S['log'].append(str(m))
    total = sum(len(v) for v in groups.values())
    dt0 = time.time()
    for folder, names in groups.items():
        if S['stop']: break
        run_batch(folder, None, model, shifts, workers, names, trace=True)
    dt = time.time() - dt0
    log(f'★ Terminé : {total} fichier(s) en {dt/60:.1f} min')
    S['running'] = False

def run_batch(folder, out, model, shifts, workers, selected, trace=False):
    S.update(stop=False, running=True, log=[], res=[])
    log = lambda m: S['log'].append(str(m))
    try:
        dev, devname = detect_device()
        S['device'] = f"{devname} → {dev}"
        out = stem_out(folder, out or None)
        os.makedirs(out, exist_ok=True)
        log(f'Machine : {devname} → {dev}')
        todo = [f for f in selected if not os.path.exists(os.path.join(out, os.path.splitext(f)[0] + '.stem.mp4'))]
        log(f'{len(selected)} choisis, {len(todo)} à convertir')
        t0 = time.time()
        from concurrent.futures import ThreadPoolExecutor
        def one(f):
            if S['stop']: return
            try:
                convert_gpu.make_stem(os.path.join(folder, f), out, model, dev, shifts=shifts)
                S.setdefault('res', []).append((f, 'OK'))
                log(f'✔ {f}')
            except Exception as e:
                S.setdefault('res', []).append((f, f'ERREUR: {e}'))
                log(f'✘ {f} : {e}')
        w = max(1, min(int(workers or 1), len(todo)))
        with ThreadPoolExecutor(max_workers=w) as ex: list(ex.map(one, todo))
        dt = time.time() - t0
        log(f'Terminé en {dt/60:.1f} min ({dt/max(1,len(todo)):.1f} s/morceau)')
        push_recent(folder)
    except Exception as e:
        log(f'FATAL: {traceback.format_exc()[-500:]}')
    finally:
        S['running'] = False

@app.post('/api/launch')
def api_launch(data: dict):
    if S['running']: return {'ok': False, 'msg': 'Batch déjà en cours'}
    fulls = data.get('selectedFull') or []
    groups = {}
    for fp in fulls:
        d = os.path.dirname(fp); n = os.path.basename(fp)
        if os.path.isfile(fp): groups.setdefault(d, []).append(n)
    if not fulls: return {'ok': False, 'msg': 'Aucun fichier sélectionné'}
    print(f'[TRACE] launch -> {len(fulls)} fichier(s) dans {len(groups)} dossier(s)', flush=True)
    th = threading.Thread(target=run_grouped, args=(groups, data.get('model', 'htdemucs'),
                            int(data.get('shifts', 1)), int(data.get('workers', 3))), daemon=True)
    th.start()
    return {'ok': True}

@app.post('/api/stop')
def api_stop(): S['stop'] = True; return {'ok': True, 'msg': 'Arrêt demandé (reprise possible)'}

@app.get('/api/poll')
def api_poll():
    res = S.get('res') or []
    return {'log': S['log'][-80:], 'running': S.get('running', False), 'done': sum(1 for _, s in res if s == 'OK'), 'total': len(res), 'device': S.get('device', '')}

HTML = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html'), encoding='utf-8').read()

# Dialog natif Windows : endpoint + déclenchement front
@app.get('/dialog')
def dialog():
    import subprocess
    ps = ("Add-Type -AssemblyName System.Windows.Forms | Out-Null;"
          "$own = New-Object Windows.Forms.Form; $own.TopMost = $true; $own.Size = New-Object Drawing.Size(1,1); $own.StartPosition = 'Manual'; $own.Location = New-Object Drawing.Point(-2000, -2000); $own.ShowInTaskbar = $false;"
          "$own.Show();"
          "$f = New-Object Windows.Forms.OpenFileDialog;"
          "$f.Title = 'Sélectionne 1, 20 ou tous les fichiers (Ctrl/Shift)';"
          "$f.Filter = 'Audio|*.mp3;*.wav;*.flac;*.m4a;*.aac;*.ogg;*.opus;*.wma|Tous fichiers|*.*';"
          "$f.Multiselect = $true;"
          "$r = $f.ShowDialog($own); $own.Hide();"
          "if ($r -eq 'OK') { $f.FileNames }")
    try:
        r = subprocess.run(['powershell','-NoProfile','-STA','-Command',ps], capture_output=True, text=True, timeout=1800)
        paths = [l.strip() for l in (r.stdout or '').splitlines() if l.strip()]
        print(f'[TRACE] dialog -> {len(paths)} fichier(s)', flush=True)
        return {'paths': paths}
    except Exception as e:
        return {'paths': [], 'error': str(e)}

@app.get('/', response_class=HTMLResponse)
def home():
    html = HTML.replace('async function browse(){ await fetch(\'/api/recents\'); } /* replacé par dialog natif ci-dessous */', '''
async function browse(){
  const r = await fetch('/dialog').then(x=>x.json());
  if(r.path){ $('folder').value = r.path; scan(); }
}''')
    return html

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=9005, log_level='error')