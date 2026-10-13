# -*- coding: utf-8 -*-
"""Stem MP4 writer — emits 5-stream stem files readable by DJ software
(verified with Traktor Pro 4).

Layout: ftyp + extension uuid + mdat (5 AAC-LC 44.1 kHz streams, 192 kbps)
+ moov (5 traks) + metadata box carrying the stem manifest (names/colors, DSP).

Usage:
    python stem_writer.py <out.stem.mp4> <t0.wav> <t1.wav> <t2.wav> <t3.wav> <t4.wav>
        t0 = master mix, t1..4 = Drums, Bass, Other, Vocals
"""
import subprocess, struct, os, sys, json, tempfile, shutil

FTYP = b'\x00\x00\x00\x18' + b'ftyp' + b'mp42' + b'\x00\x00\x00\x00' + b'mp41isom'
# extension box GUID identifying the 5-track stem layout
STEM_LAYOUT_UUID = bytes.fromhex('5ca708fb328e4205a861650eca0a9596')

FFMPEG = os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg') or 'ffmpeg'
LANG_UND = 0x55c4

# AAC-LC 44.1 kHz stereo @ 192 kbps configuration (standard MP4 boxes)
TRACK_TYPE_ENTRY = bytes.fromhex(
    '000000546d703461000000000000000100000000000000000002001000000000'
    'ac440000000000306573647300000000038080801f000000048080801440150018'
    '000002ee000002ee0005808080021210060102')
ESDS = bytes.fromhex(
    '000000306573647300000000038080801f000000048080801440150018'
    '000002ee000002ee0005808080021210060102')
# track header template (92 bytes); track id @20, duration @28 are patched per track
TKHD_TEMPLATE = bytes.fromhex(
    '0000005c746b686400000001e6f2e1fae6f2e1fa0000000200000000014c7bcc00000000000000000000000001000000'
    '0001000000000000000000000000000000010000000000000000000000000000400000000000000000000000')
assert len(TKHD_TEMPLATE) == 92

DEFAULT_STEMS = [
    {"color": "#FD6C38", "name": "Drums"},
    {"color": "#D232F4", "name": "Bass"},
    {"color": "#00FFAC", "name": "Other"},
    {"color": "#45DAFD", "name": "Vocals"},
]

# default manifest (names/colors + optional mastering DSP chain, disabled)
STEM_JSON = (b'{"mastering_dsp":{"compressor":{"attack":0.003000000026077032,'
             b'"dry_wet":50,"enabled":false,"hp_cutoff":300,"input_gain":6,'
             b'"output_gain":0,"ratio":3,"release":0.300000011920929,"threshold":0},'
             b'"limiter":{"ceiling":0,"enabled":false,"release":0.001000000047497451,'
             b'"threshold":0}},"offset":0,"stems":['
             b'{"color":"#FD6C38","name":"Drums"},{"color":"#D232F4","name":"Bass"},'
             b'{"color":"#00FFAC","name":"Other"},{"color":"#45DAFD","name":"Vocals"}],'
             b'"version":2}\x00')


def default_stem_json():
    return {"mastering_dsp": {
                "compressor": {"attack": 0.003000000026077032, "dry_wet": 50, "enabled": False,
                               "hp_cutoff": 300, "input_gain": 6, "output_gain": 0, "ratio": 3,
                               "release": 0.300000011920929, "threshold": 0},
                "limiter": {"ceiling": 0, "enabled": False, "release": 0.001000000047497451,
                            "threshold": 0}},
            "offset": 0, "stems": DEFAULT_STEMS, "version": 2}


def encode_aac_m4a(wav_in, m4a_out, bitrate='192k'):
    subprocess.check_call([FFMPEG, '-y', '-loglevel', 'error', '-i', wav_in,
                           '-c:a', 'aac', '-b:a', bitrate, '-ar', '44100', m4a_out])


def _boxes(d, off, end):
    """yield (box_type, box_start, box_size) in a byte range."""
    while off + 8 <= end:
        s = int.from_bytes(d[off:off+4], 'big'); t = d[off+4:off+8]
        if s == 1:
            s = int.from_bytes(d[off+8:off+16], 'big')
        if s < 8: break
        yield t, off, min(s, end - off)
        off += s

def _find(d, off, end, typ):
    for t, o, s in _boxes(d, off, end):
        if t == typ: return o, s
    return None

def _findany(d, off, end, typ, depth=6):
    """recursive box search inside container boxes."""
    stack = [(off, end, depth)]
    while stack:
        o0, e0, dp = stack.pop()
        for t, o, s in _boxes(d, o0, e0):
            if t == typ: return o, s
            if dp > 1 and t in (b'moov', b'trak', b'mdia', b'minf', b'stbl',
                                 b'udta', b'meta', b'ilst'):
                stack.append((o + 8, o + s, dp - 1))
    return None

def parse_m4a(path):
    """single-audio .m4a -> dict(samples, n, timescale, asc, esds)."""
    d = open(path, 'rb').read()
    mdat = _find(d, 0, len(d), b'mdat');  moov = _find(d, 0, len(d), b'moov')
    if not mdat or not moov: raise RuntimeError('mdat/moov not found')
    mo_s, mo_sz = moov
    mo, mo_e = mo_s + 8, mo_s + mo_sz
    trak_boxes = [(o + 8, o + s) for t, o, s in _boxes(d, mo, mo_e) if t == b'trak']
    for lo, hi in trak_boxes:
        stbl = _findany(d, lo, hi, b'stbl')
        if not stbl: continue
        s_lo, s_e = stbl[0] + 8, stbl[0] + stbl[1]
        stsd = _find(d, s_lo, s_e, b'stsd'); stsz = _find(d, s_lo, s_e, b'stsz')
        stco = _find(d, s_lo, s_e, b'stco')
        mdhd = _findany(d, lo, hi, b'mdhd')
        if not all([stsd, stsz, stco, mdhd]): continue
        # extract AAC SpecificConfig from the esds descriptor
        e = d.index(b'esds', stsd[0])
        i = e + 4
        asc = None
        while i + 4 < stsd[0] + stsd[1]:
            if d[i] == 0x05:
                ln = d[i+1]; asc = d[i+2:i+2+ln]; break
            if d[i] in (0x03, 0x04, 0x06):
                if d[i+1] == 0x80 and d[i+2] == 0x80 and d[i+3] == 0x80:
                    ln = d[i+4]; i = i + 5 + ln
                else:
                    ln = d[i+1]; i = i + 2 + ln
            else:
                break
        if asc is None: asc = b'\x12\x10'
        # keep the full esds box for reuse in our stsd
        e0 = d.rfind(b'esds', stsd[0], stsd[0]+stsd[1])
        esds_raw = None
        if e0 >= 0:
            esz = int.from_bytes(d[e0-4:e0], 'big')
            esds_raw = d[e0-4:e0-4+esz]
        fixed = int.from_bytes(d[stsz[0]+12:stsz[0]+16], 'big')
        n = int.from_bytes(d[stsz[0]+16:stsz[0]+20], 'big')
        if fixed:
            sizes = [fixed]*n
        else:
            p0 = stsz[0]+20
            sizes = [int.from_bytes(d[p0+4*i:p0+4*i+4], 'big') for i in range(n)]
        c0 = int.from_bytes(d[stco[0]+16:stco[0]+20], 'big')
        ts = int.from_bytes(d[mdhd[0]+8+12:mdhd[0]+8+16], 'big')
        frames = [d[c0+sum(sizes[:i]):c0+sum(sizes[:i+1])] for i in range(n)]
        return dict(samples=frames, n=n, timescale=ts, asc=asc, esds=esds_raw)
    raise RuntimeError('no AAC track in ' + path)

def box(t, payload): return struct.pack('>I', 8 + len(payload)) + t + payload
def fbox(t, v, fl, payload): return box(t, struct.pack('>I', (v << 24) | fl) + payload)

def build_stbl(n, sizes, esds, timescale, chunk_offset):
    stts = fbox(b'stts', 0, 0, struct.pack('>I', 1) + struct.pack('>II', n, 1024))
    stsc = fbox(b'stsc', 0, 0, struct.pack('>I', 1) + struct.pack('>III', 1, n, 1))
    stsz = fbox(b'stsz', 0, 0, struct.pack('>I', 0) + struct.pack('>I', n) +
                b''.join(struct.pack('>I', s) for s in sizes))
    stco = fbox(b'stco', 0, 0, struct.pack('>I', 1) + struct.pack('>I', chunk_offset))
    if esds is None:
        esds = ESDS
    entry = TRACK_TYPE_ENTRY
    stsd = fbox(b'stsd', 0, 0, struct.pack('>I', 1) + entry)
    body = stts + stsc + stsd + stsz + stco
    return struct.pack('>I', 8 + len(body)) + b'stbl' + body

def build_trak(track_id, n, sizes, esds, timescale, chunk_offset):
    dur = 1024 * n
    tkhd = bytearray(TKHD_TEMPLATE)
    struct.pack_into('>I', tkhd, 20, track_id)
    struct.pack_into('>I', tkhd, 28, dur)
    tkhd = bytes(tkhd)
    mdhd = fbox(b'mdhd', 0, 0, struct.pack('>IIII', 0, 0, timescale, dur) +
                struct.pack('>HH', LANG_UND, 0))
    hdlr = fbox(b'hdlr', 0, 0, b'\x00'*4 + b'soun' + b'\x00'*12 + b'SoundHandler\x00')
    smhd = fbox(b'smhd', 0, 0, b'\x00\x00\x00\x00')
    dref = fbox(b'dref', 0, 0, struct.pack('>I', 1) + fbox(b'url ', 0, 1, b''))
    minf = box(b'minf', smhd + dref + build_stbl(n, sizes, esds, timescale, chunk_offset))
    mdia = box(b'mdia', mdhd + hdlr + minf)
    body = tkhd + mdia
    return struct.pack('>I', 8 + len(body)) + b'trak' + body

def write_stem(out_path, wavs, stems_json=None, bitrate='192k'):
    """wavs = [master, drums, bass, other, vocals] — 5 stereo 44.1 kHz files."""
    tmp = tempfile.mkdtemp(prefix='stemb_')
    from concurrent.futures import ThreadPoolExecutor
    paths = [None] * len(wavs)
    def enc(iw):
        i, w = iw
        p = os.path.join(tmp, f't{i}.m4a')
        encode_aac_m4a(w, p, bitrate)
        paths[i] = p
    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(enc, enumerate(wavs)))
    streams = [parse_m4a(p) for p in paths]
    mdat_payload = bytearray(); chunk_offsets = []
    for st in streams:
        chunk_offsets.append(len(mdat_payload))
        for smp in st['samples']: mdat_payload += smp
    ftyp = FTYP
    uuid_box = (struct.pack('>I', 40) + b'uuid' + STEM_LAYOUT_UUID +
                struct.pack('>I', 12) + b'10.0.26100.0')
    mdat_start = len(ftyp) + len(uuid_box) + 8
    traks = []
    for i, st in enumerate(streams):
        traks.append(build_trak(i + 2, st['n'], [len(x) for x in st['samples']], ESDS,
                                st['timescale'], mdat_start + chunk_offsets[i]))
    total_dur = 1024 * streams[0]['n']
    mvhd = fbox(b'mvhd', 0, 0, struct.pack('>II', 0xe6f2e1fa, 0xe6f2e1fa) +
                struct.pack('>II', 44100, total_dur) +
                struct.pack('>I', 0x00010000) + struct.pack('>HH', 0x0100, 0) +
                b'\x00' * 8 +
                struct.pack('>9I', 0x00010000, 0, 0, 0, 0x00010000, 0,
                            0, 0, 0x40000000) +
                b'\x00' * 24 +
                struct.pack('>I', 6))
    if isinstance(stems_json, bytes):
        jsb = stems_json
    elif stems_json is None:
        jsb = STEM_JSON
    else:
        jsb = json.dumps(stems_json, separators=(',', ':')).encode('ascii') + b'\x00'
    ilst = box(b'ilst', b'\x00\x00\x00\x08NITR')
    mdh = fbox(b'hdlr', 0, 0, b'\x00'*4 + b'mdir' + b'\x00'*13)
    meta = fbox(b'meta', 0, 0, mdh + ilst)
    udta = box(b'udta', meta + b'\x00\x00\x00\x08Xtra' + box(b'stem', jsb))
    moov = box(b'moov', mvhd + b''.join(traks) + udta)
    mdat = struct.pack('>I', 8 + len(mdat_payload)) + b'mdat' + bytes(mdat_payload)
    with open(out_path, 'wb') as f: f.write(ftyp + uuid_box + mdat + moov)
    return out_path

if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) != 6: print(__doc__); sys.exit(1)
    write_stem(a[0], a[1:])
    print('OK', a[0], os.path.getsize(a[0]), 'octets')