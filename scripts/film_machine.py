#!/usr/bin/env python3
"""Film a machine running on the /machine page, so a person can watch what a
test measured.

It opens the page in a headless browser, builds the machine from a
declaration (banjo.machine.v1), presses Start, and records the page for as
long as asked: the 3D view with the stations, the readings and the list of
what happened beside it. The film is of the real page and the real engine;
nothing is drawn for it.

    python scripts/film_machine.py --spec my-machine.json --seconds 8 --out build/films/my-machine.mp4

Without --spec it films the default machine. --url points at a running lab
server (scripts/voxel-lab.py); the default is http://127.0.0.1:18893/machine.
Needs Playwright (pip install playwright) and a Chrome or Edge on the machine,
and writes MP4 (H.264) with the ffmpeg that imageio-ffmpeg carries.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BROWSERS = (
    os.environ.get('BANJO_CHROME', ''),
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
)


def browser_path(hint=None):
    for candidate in (hint, *BROWSERS):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def ffmpeg_path():
    found = shutil.which('ffmpeg')
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise SystemExit('No ffmpeg: install it, or pip install imageio-ffmpeg')


def world_seconds(clock_text):
    """The world time the page's clock shows ('World 3.20 s · 1× · ...' or
    'World 1 min 4.0 s · ...', machine-view.mjs describeTime)."""
    m = re.search(r'World\s+(?:(\d+)\s*min\s+)?([\d.]+)\s*s', clock_text or '')
    return 60.0 * int(m.group(1) or 0) + float(m.group(2)) if m else 0.0


def film(url, spec, seconds, out, browser=None, width=1280, height=760, speed='1', wall_limit_s=600.0,
         focus=None, view=None):
    from playwright.sync_api import sync_playwright
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = Path(tempfile.mkdtemp(prefix='banjo-film-'))
    frames = []          # (page time in seconds, file) as Chrome painted them
    exe = browser_path(browser)
    with sync_playwright() as pw:
        launched = pw.chromium.launch(headless=True, executable_path=exe,
                                      args=['--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        context = launched.new_context(viewport={'width': width, 'height': height})
        page = context.new_page()
        problems = []
        page.on('pageerror', lambda e: problems.append(str(e)))
        page.on('console', lambda m: problems.append(m.text) if m.type == 'error' else None)

        def waiting(condition, arg=None, timeout=180000):
            try:
                page.wait_for_function(condition, arg=arg, timeout=timeout)
            except Exception:
                raise SystemExit('The page did not get there. Its clock: ' + (page.text_content('#clock') or '') +
                                 '\nPage errors: ' + '; '.join(problems[-5:]))

        page.goto(url, wait_until='load')
        # The page builds its default machine first; wait for that.
        waiting("() => /ready: press Start|paused|calculating live/.test(document.getElementById('clock').textContent)")
        if spec is not None:
            # The declaration box is folded away; fill it and press its button
            # as the page's own handler reads them.
            page.evaluate("""spec => { document.getElementById('spec').value = JSON.stringify(spec, null, 1);
                                         document.getElementById('build-json').click(); }""", spec)
            title = spec.get('title', '')
            waiting("""title => document.getElementById('title').textContent === title &&
                /ready: press Start/.test(document.getElementById('clock').textContent)""", title)
        page.select_option('#speed', speed)
        if focus is not None:
            # Look at one station: the page's own press-to-look.
            page.click(f'#stations li:nth-child({int(focus) + 1})')
        if view is not None:
            # A fixed camera: azimuth and elevation (radians), distance (m),
            # and optionally the point looked at.
            page.evaluate('v => window.machineView(v)', view)
        # Chrome's own screencast: a frame each time the page paints.
        cdp = context.new_cdp_session(page)

        def painted(event):
            path = frames_dir / f'{len(frames):05d}.jpg'
            path.write_bytes(base64.b64decode(event['data']))
            frames.append((event['metadata']['timestamp'], path))
            cdp.send('Page.screencastFrameAck', {'sessionId': event['sessionId']})

        cdp.on('Page.screencastFrame', painted)
        cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 82, 'maxWidth': width, 'maxHeight': height})
        page.wait_for_timeout(700)
        page.click('#start')
        begun = time.monotonic()
        clock = ''
        while time.monotonic() - begun < wall_limit_s:
            page.wait_for_timeout(250)
            clock = page.text_content('#clock') or ''
            if world_seconds(clock) >= seconds or 'stopped' in clock:
                break
        page.wait_for_timeout(700)
        cdp.send('Page.stopScreencast')
        events = page.eval_on_selector_all('#events li', 'items => items.map(li => li.textContent)')
        stations = page.eval_on_selector_all('#stations li', 'items => items.map(li => li.textContent)')
        context.close()
        launched.close()
    if len(frames) < 2:
        raise SystemExit('Chrome painted fewer than two frames; nothing to film')
    # Each frame shown for as long as it was on the screen, so the film runs
    # at the speed the page did.
    listing = frames_dir / 'frames.txt'
    with listing.open('w', encoding='utf-8') as f:
        for (t, path), (t_next, _) in zip(frames, frames[1:] + [(frames[-1][0] + 0.04, None)]):
            f.write(f"file '{path.as_posix()}'\nduration {max(0.001, t_next - t):.4f}\n")
        f.write(f"file '{frames[-1][1].as_posix()}'\n")
    subprocess.run([ffmpeg_path(), '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-vf', 'scale=960:-2,fps=25', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '26',
                    '-movflags', '+faststart', str(out)], check=True)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return {'film': str(out), 'clock': clock, 'stations': stations, 'events': events}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--url', default='http://127.0.0.1:18893/machine')
    ap.add_argument('--spec', help='a banjo.machine.v1 declaration (JSON file); the default machine without it')
    ap.add_argument('--seconds', type=float, default=8.0, help='world seconds to film')
    ap.add_argument('--speed', default='1', choices=['0.25', '0.5', '1', '2', '4'])
    ap.add_argument('--focus', type=int, help='look at this station (0 is the first) instead of following')
    ap.add_argument('--view', help='a fixed camera: azimuth,elevation,distance[,x,y,z] (radians, metres); '
                                   'azimuth 0 looks from +z toward -z')
    ap.add_argument('--out', required=True)
    ap.add_argument('--browser', help='path to Chrome or Edge')
    args = ap.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text(encoding='utf-8')) if args.spec else None
    view = None
    if args.view:
        v = [float(x) for x in args.view.split(',')]
        view = {'azimuth': v[0], 'elevation': v[1], 'distance': v[2], **({'at': v[3:6]} if len(v) >= 6 else {})}
    result = film(args.url, spec, args.seconds, args.out, browser=args.browser, speed=args.speed, focus=args.focus,
                  view=view)
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    sys.exit(main())
