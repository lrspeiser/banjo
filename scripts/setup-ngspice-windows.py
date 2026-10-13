"""Install pinned official ngspice 47 DLL dependencies in an ignored build folder.

Does not edit PATH or install system software. Uses py7zr to read 7z archives.
Archives must match the SHA-256 values published on the official release pages.
"""
from pathlib import Path
import argparse
import hashlib
import html
import re
import urllib.request
import py7zr

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'https://downloads.sourceforge.net/project/ngspice/ng-spice-rework/47/'
ARCHIVES = {
    'ngspice-47_dll_64.7z': '5bf5eec7db989f74849cdb32f7df62693f4f149cceeebcbd222eb35c2bb821eb',
    'ngspice-47_64.7z': '59225971bd68cdd1199443649aa4615a9e6d684933f205ab49006a3942518f5a',
}


def verified_archive(folder, name, expected):
    archive = folder / name
    if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest() == expected:
        return archive
    url = RELEASE + name
    for attempt in range(3):
        print('Downloading', name, flush=True)
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        if data.startswith(b"7z\xbc\xaf\x27\x1c"):
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError(f'{name}: release checksum mismatch')
            archive.write_bytes(data)
            return archive
        # SourceForge can return its HTML download page before the archive.
        match = re.search(r'data-release-url="([^"]+)"', data.decode('utf-8', errors='replace'))
        if not match:
            raise RuntimeError(f'{name}: download returned no archive or release link')
        url = html.unescape(match.group(1))
        if not url.startswith('https://downloads.sourceforge.net/project/ngspice/'):
            raise RuntimeError('unexpected release destination')
    raise RuntimeError(f'{name}: no verified archive after three download pages')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'build/ngspice-47')
    args = parser.parse_args()
    folder = args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for name, checksum in ARCHIVES.items():
        archive = verified_archive(folder, name, checksum)
        with py7zr.SevenZipFile(archive, 'r') as package:
            # Only named ABI/runtime files, rather than extracting scripts,
            # unrelated code models, examples or arbitrary archive paths.
            targets = (['Spice64_dll/include/ngspice/sharedspice.h',
                        'Spice64_dll/lib/lib-vs/ngspice.lib',
                        'Spice64_dll/dll-vs/ngspice.dll',
                        'Spice64_dll/dll-vs/libomp140.x86_64.dll']
                       if '_dll_' in name else
                       ['Spice64/bin/sndfile.dll', 'Spice64/bin/samplerate.dll'])
            package.extract(path=folder, targets=targets)
    shared = folder / 'Spice64_dll'
    # The DLL archive omits its audio dependencies; the companion official
    # Windows executable archive contains these exact named dependencies.
    for name in ('sndfile.dll', 'samplerate.dll'):
        candidates = list((folder / 'Spice64').rglob(name))
        if len(candidates) != 1:
            raise RuntimeError(f'missing or ambiguous official dependency: {name}')
        (shared / 'dll-vs' / name).write_bytes(candidates[0].read_bytes())
    print('Configure with:', flush=True)
    print(f'-DNGSPICE_INCLUDE_DIR="{shared / "include/ngspice"}"')
    print(f'-DNGSPICE_LIBRARY="{shared / "lib/lib-vs/ngspice.lib"}"')


if __name__ == '__main__':
    main()
