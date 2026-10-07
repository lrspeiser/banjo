"""Inventory tracked Banjo code without running the server, builds or tests.

Static candidates are review inputs, not permission to delete code. Import
graphs omit dynamic imports; identifier counts include comments and strings.
Only explicitly selected tracked source roots are read, never local .env,
rooms, run logs, dependency caches or credentials. Output contains metadata,
not source bodies. Run from any directory; pass --output for a saved report.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ROOTS = {"src", "include", "playground", "mcp", "bindings", "tools",
         "scripts", "tests", "examples", "cmake", "runtime", "progression",
         "assets", "voice", "client"}
EXTENSIONS = {".py", ".js", ".mjs", ".ts", ".tsx", ".rs", ".cpp", ".hpp", ".h",
              ".c", ".cu", ".inl", ".sh", ".ps1", ".cmake", ".html", ".css",
              ".toml", ".yml", ".yaml", ".json", ".csv", ".txt"}
ROOT_FILES = {"CMakeLists.txt", "CMakePresets.json", "Cargo.toml", "Cargo.lock",
              "rust-toolchain.toml", "Dockerfile", "fly.toml", ".dockerignore",
              ".gitignore", ".gitattributes", ".clang-format", ".cargo/config.toml"}


def selected_path(name):
    """Explicit tracked-source/config/data allowlist; never read local secrets."""
    path = Path(name)
    if "vendor" in path.parts or path.name.startswith(".env"):
        return False
    return (name in ROOT_FILES or path.name == "CMakeLists.txt" or
            (path.parts[0] in ROOTS and path.suffix in EXTENSIONS) or
            (name.startswith(".github/workflows/") and path.suffix in {".yml", ".yaml"}))


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def inventory():
    names = git("ls-files").splitlines()
    selected = [name for name in names if selected_path(name)]
    contents = {name: (ROOT / name).read_text(encoding="utf-8", errors="replace")
                for name in selected}
    identifiers = Counter(token for content in contents.values()
                          for token in re.findall(r"\b[A-Za-z_]\w*\b", content))
    files, groups, imports, candidates = [], defaultdict(list), [], []
    duplicate_bodies = defaultdict(list)
    parse_errors = []
    for name, content in contents.items():
        record = {"path": name, "lines": len(content.splitlines()),
                  "bytes": len((ROOT / name).read_bytes()),
                  "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest()}
        files.append(record)
        groups[Path(name).parts[0]].append(record)
        if Path(name).suffix == ".py":
            try:
                tree = ast.parse(content, filename=name)
            except SyntaxError as error:
                parse_errors.append({"path": name, "error": str(error)})
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append({"from": name, "module": alias.name,
                                        "line": node.lineno, "relative": 0})
                elif isinstance(node, ast.ImportFrom):
                    imports.append({"from": name, "module": node.module or "",
                                    "line": node.lineno, "relative": node.level,
                                    "names": [a.name for a in node.names]})
            if Path(name).parts[0] in {"playground", "mcp"}:
                for node in tree.body:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    item = {"path": name, "name": node.name, "line": node.lineno,
                            "end_line": node.end_lineno,
                            "identifier_occurrences": identifiers[node.name],
                            "decorated": bool(node.decorator_list)}
                    if identifiers[node.name] == 1 and not node.decorator_list and node.name != "main":
                        candidates.append(item)
                    body = node.body
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                        body = body[1:]
                    if node.end_lineno - node.lineno >= 7:
                        signature = repr([ast.dump(statement, include_attributes=False) for statement in body])
                        duplicate_bodies[signature].append(item)
        elif Path(name).suffix in {".js", ".mjs"} and Path(name).parts[0] == "playground":
            for match in re.finditer(r"\b(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\(", content):
                symbol = match.group(1)
                if identifiers[symbol] == 1:
                    candidates.append({"path": name, "name": symbol,
                                       "line": content.count("\n", 0, match.start()) + 1,
                                       "identifier_occurrences": 1,
                                       "requires_export_and_dynamic_lookup_review": True})
    return {
        "schema": "banjo.static-audit.v1", "baseline_commit": git("rev-parse", "HEAD"),
        "source_state": {"modified_tracked_selected_paths":
                         [name for name in git("diff", "--name-only", "HEAD").splitlines()
                          if selected_path(name)]},
        "method": {"tracked_files_only": True, "roots": sorted(ROOTS),
                   "extensions": sorted(EXTENSIONS),
                   "explicit_files": sorted(ROOT_FILES),
                   "additional_scope": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
                   "excluded_path_components": ["vendor"],
                   "limitations": ["Static inventory, not executed coverage or proof of dead code.",
                       "Identifier references include comments and strings; counts are global, not resolved symbols.",
                       "Python duplicate bodies exclude docstrings and do not compare signatures or caller contracts.",
                       "Python import graph records syntax, including imports inside functions; it omits dynamic loading.",
                       "Tracked source, client assets, config and textual fixtures/declarations are counted separately by root; line totals are not executable-code counts.",
                       "Untracked files are excluded; modified tracked selected paths are listed and hashes describe the scanned working tree, not necessarily baseline_commit.",
                       "No simulation, performance, browser or platform qualification is performed."]},
        "totals": {"files": len(files), "lines": sum(f["lines"] for f in files)},
        "by_root": {key: {"files": len(value), "lines": sum(f["lines"] for f in value)}
                    for key, value in sorted(groups.items())},
        "largest_files": sorted(files, key=lambda f: f["lines"], reverse=True)[:30],
        "unreferenced_function_candidates": candidates,
        "duplicate_python_function_bodies": [value for value in duplicate_bodies.values() if len(value) > 1],
        "python_imports": imports, "parse_errors": parse_errors, "files": files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inventory()
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(json.dumps({key: report[key] for key in
                          ("baseline_commit", "totals", "by_root", "parse_errors")}, indent=2))
    else:
        print(encoded, end="")
    return int(bool(report["parse_errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
