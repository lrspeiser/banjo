"""Public, credential-free identity for the files selected by this host.

Capture once per host/world startup, not on the simulation step. File hashes
identify actual artifacts; they do not claim the native binary was built from
the current checkout. Until native build provenance is embedded, it is unknown.
"""
from __future__ import annotations

from functools import lru_cache
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("playground", "mcp", "bindings", "src", "include", "tools", "cmake", "runtime")
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".html", ".css", ".cpp", ".hpp", ".h", ".cmake", ".rs", ".toml"}
CLIENT_SUFFIXES = {".js", ".mjs", ".html", ".css"}


def digest_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def source_files(root):
    for folder in SOURCE_ROOTS:
        directory = root / folder
        if not directory.is_dir():
            continue
        yield from files_in(directory, SOURCE_SUFFIXES, {"vendor", "target", "runs", "__pycache__"})
    for name in ("CMakeLists.txt", "Cargo.toml", "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml"):
        if (root / name).is_file():
            yield root / name


def files_in(directory, suffixes, excluded):
    for folder, children, files in os.walk(directory):
        children[:] = [name for name in children if name not in excluded]
        for name in files:
            path = Path(folder) / name
            if path.suffix in suffixes:
                yield path


def digest_set(root, paths):
    hasher = hashlib.sha256()
    count = 0
    for path in sorted(set(paths)):
        hasher.update(path.relative_to(root).as_posix().encode() + b"\0")
        hasher.update(digest_file(path).encode() + b"\n")
        count += 1
    return {"sha256": hasher.hexdigest(), "files": count}


def git_identity(root):
    try:
        revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, timeout=3).strip()
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain",
            "--untracked-files=normal", "--", *SOURCE_ROOTS, "CMakeLists.txt", "Cargo.toml",
            "Cargo.lock", "rust-toolchain.toml", ".cargo/config.toml"], stderr=subprocess.DEVNULL, text=True, timeout=3)
        return {"revision": revision if re.fullmatch(r"[0-9a-f]{40,64}", revision) else None,
                "source_dirty": bool(dirty.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"revision": None, "source_dirty": None}


@lru_cache(maxsize=32)
def _artifact_hash(path, size, modified_ns):
    return digest_file(Path(path))


def artifact(path):
    if path is None:
        return {"available": False, "sha256": None, "build_provenance": "unrecorded"}
    path = Path(path).resolve()
    if not path.is_file():
        return {"name": path.name, "available": False, "sha256": None,
                "build_provenance": "unrecorded"}
    stat = path.stat()
    return {"name": path.name, "available": True, "bytes": stat.st_size,
            "sha256": _artifact_hash(str(path), stat.st_size, stat.st_mtime_ns),
            "build_provenance": "unrecorded"}


def capture(*, root=ROOT, native=None, clock_enabled=False, inprocess=False):
    root = Path(root).resolve()
    source = digest_set(root, source_files(root))
    client_root = root / "playground"
    clients = files_in(client_root, CLIENT_SUFFIXES, {"runs", "__pycache__"}) if client_root.is_dir() else []
    header = root / "include/banjo/banjo.h"
    match = re.search(r"#define BANJO_ABI_VERSION (\d+)", header.read_text(encoding="utf-8")) if header.is_file() else None
    manifest = {"schema": "banjo.build-manifest.v1", "application": {**git_identity(root), **source},
        "client": digest_set(root, clients),
        "native": {name: artifact(path) for name, path in sorted((native or {}).items())},
        "expected_header_abi": int(match[1]) if match else None,
        "actual_native_abi": None,
        "configuration": {"clock_enabled": bool(clock_enabled), "inprocess": bool(inprocess)},
        "capture": "startup files; native source/numeric provenance unrecorded"}
    manifest["id"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return manifest


@lru_cache(maxsize=1)
def startup_source():
    return capture()


def for_app(app):
    configuration = {'clock_enabled': os.environ.get('BANJO_WORLD_CLOCK', '1') != '0',
                     'inprocess': bool(getattr(app, 'live_inprocess', False))}
    cached = getattr(app, "build_manifest", None)
    if isinstance(cached, dict) and cached.get('configuration') == configuration:
        return cached
    native = {}
    engine = getattr(app, "engine_path", None)
    if engine:
        import fracture_lab
        engine = Path(engine)
        native = {"platform": engine,
                  "live": fracture_lab.executable(engine, "lattice").with_name("banjo_live_world_run" + engine.suffix),
                  "library": Path(os.environ["BANJO_LIBRARY"]) if os.environ.get("BANJO_LIBRARY") else
                      engine.with_name("banjo.dll" if engine.suffix == ".exe" else "libbanjo.so")}
    manifest = deepcopy(cached if isinstance(cached, dict) else startup_source())
    if not isinstance(cached, dict):
        manifest['native'] = {name: artifact(path) for name, path in sorted(native.items())}
    manifest['configuration'] = configuration
    manifest.pop('id')
    manifest['id'] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    app.build_manifest = manifest
    return app.build_manifest
