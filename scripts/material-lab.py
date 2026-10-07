"""Generate exact CPU experiment recordings and serve the isolated read-only lab.

The browser replays recorded samples; no request steps a game world or uses an
LLM. Only the generated lab directory's six named assets are exposed. Run the
TypeScript build first; native build/output stay in build/, not the repository.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = {"index.html", "lab.css", "lab.js", "contract.js", "material.json", "manifest.json"}


def prepare(native: Path, output: Path):
    native = native.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    compiled = ROOT / "build/material-lab/ui/lab.js"
    if not compiled.is_file():
        raise RuntimeError("Build the client first: npm ci && npm run build in client/")
    subprocess.run([str(native), str(output / "material.json")], check=True, timeout=120)
    for name in ("index.html", "lab.css"):
        shutil.copyfile(ROOT / "client/experiments" / name, output / name)
    if compiled.resolve() != (output / "lab.js").resolve():
        shutil.copyfile(compiled, output / "lab.js")
        shutil.copyfile(compiled.with_name("contract.js"), output / "contract.js")
    sources = ["tools/material_lab_record.cpp", "src/fastlattice/SolidMatterPatch.cpp",
               "src/fastlattice/ConstituentPartition.cpp", "src/fastlattice/CpuLatticeBackend.cpp",
               "src/material/MaterialCatalog.cpp", "client/experiments/lab.ts", "client/experiments/contract.ts"]
    manifest = {
        "schema": "banjo.material-lab-manifest.v1",
        "source_revision": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "kind": "recorded CPU experiments; read-only replay",
        "identity_note": "Checkout revision/workspace hashes and actual binary fingerprint; revision alone does not prove artifact/source equivalence.",
        "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources},
        "assets_sha256": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in FILES if name != "manifest.json"},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


class LabHandler(SimpleHTTPRequestHandler):
    def guess_type(self, path):
        mime = super().guess_type(path)
        if mime.startswith("text/") or mime in {"application/javascript", "application/json"}:
            return mime + "; charset=utf-8"
        return mime

    def send_head(self):
        # No directory listing, arbitrary workspace paths, legacy host or APIs.
        name = self.path.split("?", 1)[0]
        if name == "/":
            self.path = "/index.html"
        elif name not in {"/" + item for item in FILES}:
            self.send_error(404, "No lab asset at this path")
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/material-lab/ui")
    parser.add_argument("--port", type=int, default=18891)
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    prepare(args.native, output)
    if args.generate_only:
        print(f"Generated lab in {output}")
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(LabHandler, directory=str(output)))
    print(f"Material lab: http://127.0.0.1:{server.server_port}/ (recorded experiment replay)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
