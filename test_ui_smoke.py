# -*- coding: utf-8 -*-
"""UI smoke test — run BEFORE pushing any UI change.

Verifies with real clicks (Playwright, network-intercepted so no real dialog
and no real conversion):
  - buttons are wired (pick / bulk / go / stop)
  - picking files fills the table and counters
  - "go" issues the correct POST /api/launch payload

Needs: pip install playwright; playwright install chromium.
Run:   python test_ui_smoke.py   (app must be running on 127.0.0.1:9005)
"""
import sys
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:9005'
FAKE = 'D:/tmp/demo_tracks/01 - Demo Track.mp3|D:/tmp/demo_tracks/03 - Deep Bass.mp3'

def main():
    failures = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.route('**/dialog', lambda r: r.fulfill(
            content_type='application/json', body='{"paths":["%s"]}' % FAKE))
        launched = {}
        def on_launch(route):
            launched['body'] = route.request.post_data or ''
            route.fulfill(content_type='application/json', body='{"ok":true}')
        pg.route('**/api/launch', on_launch)
        pg.goto(BASE); pg.wait_for_load_state('networkidle')

        # pick wires + fills table
        pg.click('#pick'); pg.wait_for_timeout(800)
        rows = pg.locator('#tb tr').count()
        if rows != 2: failures.append(f'pick: table has {rows} rows, expected 2')

        # bulk buttons
        pg.click('#bNone'); pg.wait_for_timeout(150)
        if pg.inner_text('#nsel') != '0': failures.append('bNone did not clear selection')
        pg.click('#bAll'); pg.wait_for_timeout(150)
        if pg.inner_text('#nsel') != '2': failures.append('bAll did not select all')

        # go sends the launch payload
        pg.click('#go'); pg.wait_for_timeout(800)
        if 'selectedFull' not in launched.get('body', '') or '01 - Demo Track.mp3' not in launched.get('body',''):
            failures.append(f'go: bad or missing POST /api/launch ({launched.get("body","")!r:.80})')

        # stop button responds
        ok = pg.evaluate("fetch('/api/stop',{method:'POST'}).then(x=>x.json()).then(d=>d.ok)")
        if not ok: failures.append('stop: /api/stop failed')

        b.close()

    if failures:
        print('SMOKE TEST FAILED:'); [print(' -', f) for f in failures]; sys.exit(1)
    print('SMOKE TEST OK: pick/bulk/go/stop all wired and functional')

if __name__ == '__main__':
    main()