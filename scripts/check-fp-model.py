#!/usr/bin/env python3
"""Audit a configured build's floating-point model from what CMake generated.

    python scripts/check-fp-model.py --build BUILD_DIR [--config NAME | --all-configs]
                                     [--manifest PATH] [--quiet]

Every C++ file a build compiles -- ours, Jolt's, anything else in the link --
must compile under the build's numerical profile, banjo-cpu-precise-v1
(cmake/FloatingPointModel.cmake says what it is, docs/floating-point-model.md
why). CMake is not second-guessed here: its File API reply is read after it
has generated the build. For each configuration it lists every target, every
file each target compiles and the ordered fragments of each compile command,
with generator expressions, SHELL: options, per-file options and usage
requirements already resolved. Then:

- a Ninja or Makefile build's own commands (compile_commands.json, response
  files expanded) are read as well, and each compiled C++ file must appear in
  both, once per target that compiles it;
- a Visual Studio build's generated projects are read, because MSBuild builds
  the command from their settings, and no Directory.Build.props or .targets
  may sit above the build to change them;
- the environment the build runs in is folded into each command the way the
  compiler folds it: CL before and _CL_ after for cl, and CCC_OVERRIDE_OPTIONS
  is refused for clang;
- every compiled C++ file, and every header under the build's own and fetched
  include directories, is searched for floating-point pragmas, attributes and
  calls that change the floating-point environment; each use found must be one
  listed below as allowed;
- every file that can include Jolt's headers must see Jolt's own JPH_
  definitions, so Jolt's inline code takes the same paths in every object.

A floating-point option this script does not know is reported, never skipped.
Exit 0 when every file keeps the profile, 1 when any does not, 2 when the
audit could not be done.
"""
import argparse
import json
import os
import re
import shlex
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PROFILE = "banjo-cpu-precise-v1"
COMPILED_TYPES = {"STATIC_LIBRARY", "SHARED_LIBRARY", "MODULE_LIBRARY", "OBJECT_LIBRARY", "EXECUTABLE"}


class AuditError(Exception):
    """The audit could not be done (exit 2), as distinct from a build that fails it."""


# --------------------------------------------------------------------------
# Command lines
# --------------------------------------------------------------------------

def split_windows(text):
    """Split a command line as CommandLineToArgvW does (MSVC's cl reads it so)."""
    args, current, have, quoted = [], [], False, False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n" and not quoted:
            if have:
                args.append("".join(current))
                current, have = [], False
            i += 1
            continue
        if c == "\\":
            j = i
            while j < n and text[j] == "\\":
                j += 1
            count = j - i
            if j < n and text[j] == '"':
                current.append("\\" * (count // 2))
                have = True
                if count % 2:
                    current.append('"')
                    i = j + 1
                else:
                    i = j
            else:
                current.append("\\" * count)
                have = True
                i = j
            continue
        if c == '"':
            if quoted and i + 1 < n and text[i + 1] == '"':
                current.append('"')
                i += 2
            else:
                quoted = not quoted
                i += 1
            have = True
            continue
        current.append(c)
        have = True
        i += 1
    if have:
        args.append("".join(current))
    return args


def split_command(text, family):
    """A fragment or command in the build system's own shell syntax."""
    if family == "msvc" or os.name == "nt":
        return split_windows(text)
    return shlex.split(text, posix=True)


def read_response_file(path):
    data = Path(path).read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def expand_response_files(args, family, directory=None, depth=0):
    """Replace every @file argument with the arguments in the file, as the
    compiler does, recursively."""
    out = []
    for arg in args:
        if arg.startswith("@") and len(arg) > 1:
            if depth >= 8:
                raise AuditError(f"response files nest deeper than 8 at {arg}")
            path = Path(arg[1:])
            if not path.is_absolute() and directory:
                path = Path(directory) / path
            if not path.is_file():
                raise AuditError(f"a command names the response file {path}, which is not there")
            out.extend(expand_response_files(split_command(read_response_file(path), family),
                                             family, directory, depth + 1))
        else:
            out.append(arg)
    return out


# --------------------------------------------------------------------------
# The profile's rules, one compiler family at a time
# --------------------------------------------------------------------------

def msvc_problems(args):
    """What keeps a cl command from compiling /fp:precise without contraction.

    The last /fp: model wins and /fp:precise is cl's default; /fp:contract adds
    fused multiply-adds to either; /fp:except[-] changes no result."""
    model, contract, problems = "precise", None, []
    for arg in args:
        if not arg or arg[0] not in "/-":
            continue
        option = arg[1:].lower()
        if option.startswith("fp:"):
            value = option[3:]
            if value in ("precise", "fast", "strict"):
                model = value
            elif value == "contract":
                contract = arg
            elif value in ("except", "except-"):
                continue
            else:
                problems.append(f"{arg} is a floating-point option this audit does not know")
        elif option in ("qfast_transcendentals", "qimprecise_fwaits"):
            problems.append(f"{arg} is not in the profile")
    if model != "precise":
        problems.insert(0, f"/fp:{model}")
    if contract:
        problems.append(contract)
    return problems


GNU_FLOAT_OPTION = re.compile(
    r"^-(?:f(?:no-)?(?:fast-math|unsafe-math-optimizations|associative-math|reciprocal-math|"
    r"finite-math-only|signed-zeros|trapping-math|math-errno|rounding-math|signaling-nans|"
    r"cx-limited-range|cx-fortran-rules|approx-func|honor-nans|honor-infinities|"
    r"protect-parens|fp-int-builtin-inexact)"
    r"|ffp-contract=.*|ffp-model=.*|ffp-exception-behavior=.*|fexcess-precision=.*|"
    r"fdenormal-fp-math.*|ffp-eval-method=.*|mfpmath=.*|Ofast|mdaz-ftz|mno-daz-ftz)$")
# Options that only say what the default already is.
GNU_DEFAULTS = {
    "-fno-fast-math", "-fno-unsafe-math-optimizations", "-fno-associative-math",
    "-fno-reciprocal-math", "-fno-finite-math-only", "-fsigned-zeros", "-ftrapping-math",
    "-fmath-errno", "-fno-rounding-math", "-fno-signaling-nans", "-fno-cx-limited-range",
    "-fno-cx-fortran-rules", "-fno-approx-func", "-fhonor-nans", "-fhonor-infinities",
    "-mfpmath=sse",
}


def gnu_problems(args):
    """What keeps a GCC or Clang command from -ffp-contract=off without fast math.

    GCC contracts by default in C++ and Clang within an expression, so the
    profile has to be said, and said last."""
    contract, fast, problems = None, None, []
    for arg in args:
        if not GNU_FLOAT_OPTION.match(arg):
            continue
        if arg.startswith("-ffp-contract="):
            contract = arg.split("=", 1)[1]
        elif arg in ("-ffast-math", "-Ofast"):
            fast, contract = arg, "fast"
        elif arg == "-fno-fast-math":
            fast = None
        elif arg in GNU_DEFAULTS:
            continue
        elif arg == "-ffp-model=strict":
            contract = "off"
        elif arg == "-ffp-model=precise":
            contract = "on"
        else:
            problems.append(f"{arg} is not in the profile" if arg.startswith("-f") or arg == "-Ofast"
                            else f"{arg} is a floating-point option this audit does not know")
    if fast:
        problems.insert(0, fast)
    if contract != "off":
        problems.insert(0, f"-ffp-contract={contract}" if contract
                        else "no -ffp-contract=off, so the compiler would contract")
    return problems


def compile_problems(args, family):
    return msvc_problems(args) if family == "msvc" else gnu_problems(args)


def link_problems(args, family):
    """GCC and Clang link crtfastmath.o, which turns denormals to zero for the
    whole process at startup, when fast math reaches the link."""
    if family != "gnu":
        return []
    return [f"{arg} on the link line links crtfastmath, which flushes denormals for the whole program"
            for arg in args if arg in ("-ffast-math", "-Ofast", "-funsafe-math-optimizations")]


# --------------------------------------------------------------------------
# Floating-point pragmas, attributes and environment calls in the source
# --------------------------------------------------------------------------

SOURCE_PATTERNS = {
    "float_control": re.compile(r"float_control\s*\("),
    "fp_contract": re.compile(r"pragma\s+(?:STDC\s+)?(?:FP_CONTRACT|fp_contract)\b|"
                              r"(?:_Pragma\s*\(\s*\"\s*|__pragma\s*\(\s*)(?:STDC\s+)?(?:FP_CONTRACT|fp_contract)\b"),
    "fenv_access": re.compile(r"pragma\s+(?:STDC\s+)?(?:FENV_ACCESS|FENV_ROUND|fenv_access)\b|"
                              r"(?:_Pragma\s*\(\s*\"\s*|__pragma\s*\(\s*)(?:STDC\s+)?(?:FENV_ACCESS|FENV_ROUND|fenv_access)\b"),
    "optimize_pragma": re.compile(r"pragma\s+GCC\s+optimize|pragma\s+clang\s+fp\b|"
                                  r"_Pragma\s*\(\s*\"\s*(?:GCC\s+optimize|clang\s+fp)"),
    "optimize_attribute": re.compile(r"__attribute__\s*\(\(\s*optimize|\[\[\s*gnu::optimize"),
    "fp_environment": re.compile(
        r"\b(?:_controlfp_s|_controlfp|_control87|__control87_2|_mm_setcsr|fesetround|fesetenv|"
        r"feupdateenv|feholdexcept|fesetexceptflag)\s*\(|_MM_SET_ROUNDING_MODE|"
        r"_MM_SET_FLUSH_ZERO_MODE|_MM_SET_DENORMALS_ZERO_MODE"),
    "flush_denormals": re.compile(r"\bFPFlushDenormals\b"),
}

# A pragma that only makes floating point stricter agrees with the profile
# wherever it is: precise semantics asked for (Jolt's JPH_PRECISE_MATH_ON), the
# pop that ends such a push (JPH_PRECISE_MATH_OFF), contraction turned off.
STRICTER_PRAGMAS = [
    (r"float_control\(\s*precise\s*,\s*on\s*(?:,\s*push\s*)?\)", "asks for precise semantics, which the profile has"),
    (r"float_control\(\s*pop\s*\)", "pops a float_control push; only pushes of precise semantics are allowed"),
    (r"fp_contract\s*\(\s*off\s*\)|FP_CONTRACT\s+OFF", "turns contraction off, as the profile does"),
    (r"optimize\s*\(\s*\"fp-contract=off\"\s*\)", "turns contraction off, as the profile does"),
]

# Each other allowed use: the file it is in (the end of its path), which
# pattern, what the line has to say, and why it is harmless under the profile.
ALLOWED_SOURCE_USES = [
    ("Jolt/Core/FPControlWord.h", "fp_environment", r"_mm_setcsr|_controlfp_s",
     "the helper behind Jolt's floating-point exception masks (FPException.h), which "
     "restores what it changed and never touches rounding or denormals"),
    ("Jolt/Core/FPFlushDenormals.h", "flush_denormals", r"class\s+FPFlushDenormals",
     "the class's definition; Jolt uses it nowhere, and a use anywhere is refused"),
]


def strip_comments(text):
    """The text with // and /* */ comments blanked, line numbers kept."""
    out, i, n = [], 0, len(text)
    in_string = None
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue
        if c in "\"'":
            in_string = c
            out.append(c)
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def scan_source(path):
    """Every (line, pattern, text) in one file."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits = []
    for number, line in enumerate(strip_comments(text).splitlines(), start=1):
        for name, pattern in SOURCE_PATTERNS.items():
            if pattern.search(line):
                hits.append((number, name, line.strip()))
    return hits


def allowed_use(path, name, line):
    if name in ("float_control", "fp_contract", "optimize_pragma"):
        for pattern, why in STRICTER_PRAGMAS:
            if re.search(pattern, line):
                return why
    # Paths are compared without case: Windows gives them lower-cased.
    posix = str(path).replace("\\", "/").lower()
    for suffix, pattern, must, why in ALLOWED_SOURCE_USES:
        if posix.endswith(suffix.lower()) and name == pattern and re.search(must, line):
            return why
    return None


INCLUDE_LINE = re.compile(r'^\s*#\s*include\s*([<"])([^>"\n]+)[>"]', re.M)


def reachable_files(roots, include_dirs):
    """Every file the compiled files can include: the #include lines followed,
    through the including file's own directory for "..." and through the build's
    include directories for both kinds, whatever #if surrounds them. More than
    the compiler reads, never less -- but for what it finds only in the
    toolchain's own directories, which are not the build's to change."""
    dirs = [Path(d) for d in include_dirs]
    seen, stack, resolved = set(), list(roots), {}
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        seen.add(f)
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        here = Path(f).parent
        for kind, name in INCLUDE_LINE.findall(strip_comments(text)):
            key = (str(here) if kind == '"' else "", name)
            if key not in resolved:
                candidates = ([here] if kind == '"' else []) + dirs
                resolved[key] = next((os.path.normcase(os.path.normpath(str(c / name)))
                                      for c in candidates if (c / name).is_file()), None)
            if resolved[key] and resolved[key] not in seen:
                stack.append(resolved[key])
    return seen


# --------------------------------------------------------------------------
# CMake's File API reply
# --------------------------------------------------------------------------

def load_reply(build):
    reply = build / ".cmake" / "api" / "v1" / "reply"
    indexes = sorted(reply.glob("index-*.json")) if reply.is_dir() else []
    if not indexes:
        raise AuditError(f"no CMake File API reply in {reply}: configure {build} again "
                         "(CMake 3.27 or newer answers the query in the same run)")
    index = json.loads(indexes[-1].read_text(encoding="utf-8"))

    def newest(kind, major):
        found = [o for o in index.get("objects", [])
                 if o.get("kind") == kind and o.get("version", {}).get("major") == major]
        if not found:
            raise AuditError(f"the File API reply in {reply} has no {kind} v{major}")
        return json.loads((reply / found[-1]["jsonFile"]).read_text(encoding="utf-8"))

    return reply, newest("codemodel", 2), newest("toolchains", 1)


def normalise(path, base):
    p = Path(path)
    if not p.is_absolute():
        p = Path(base) / p
    return os.path.normcase(os.path.normpath(str(p)))


def fragment_origin(target, fragment):
    """Where an option was added, from the fragment's backtrace."""
    graph = target.get("backtraceGraph")
    node = fragment.get("backtrace")
    if graph is None or node is None:
        return ""
    nodes, files, commands = graph.get("nodes", []), graph.get("files", []), graph.get("commands", [])
    if node >= len(nodes):
        return ""
    entry = nodes[node]
    where = files[entry["file"]] if entry.get("file") is not None and entry["file"] < len(files) else "?"
    line = entry.get("line")
    command = commands[entry["command"]] if entry.get("command") is not None and entry["command"] < len(commands) else ""
    return f"{where}:{line} {command}".strip() if line else where


# --------------------------------------------------------------------------
# Visual Studio projects
# --------------------------------------------------------------------------

MSBUILD = "{http://schemas.microsoft.com/developer/msbuild/2003}"
FP_MODEL_OPTION = {"precise": "/fp:precise", "fast": "/fp:fast", "strict": "/fp:strict"}


def _config_of(condition):
    match = re.search(r"==\s*'([^'|]*)\|", condition or "")
    return match.group(1) if match else None


def vcxproj_settings(path, config):
    """{normalised source: [cl arguments from its settings]} for one configuration.

    MSBuild writes /fp: from FloatingPointModel and appends AdditionalOptions."""
    root = ET.parse(path).getroot()
    default_model, default_extra = None, []
    for group in root.iter(MSBUILD + "ItemDefinitionGroup"):
        if _config_of(group.get("Condition")) != config:
            continue
        compile_ = group.find(MSBUILD + "ClCompile")
        if compile_ is None:
            continue
        model = compile_.find(MSBUILD + "FloatingPointModel")
        if model is not None and model.text:
            default_model = model.text.strip().lower()
        extra = compile_.find(MSBUILD + "AdditionalOptions")
        if extra is not None and extra.text:
            default_extra = split_windows(extra.text.replace("%(AdditionalOptions)", ""))
    settings = {}
    for item in root.iter(MSBUILD + "ClCompile"):
        include = item.get("Include")
        if not include:
            continue
        model, extra, excluded = default_model, list(default_extra), False
        for child in item:
            if child.get("Condition") is not None and _config_of(child.get("Condition")) != config:
                continue
            tag = child.tag.replace(MSBUILD, "")
            text = (child.text or "").strip()
            if tag == "FloatingPointModel" and text:
                model = text.lower()
            elif tag == "AdditionalOptions":
                extra = default_extra + split_windows(text.replace("%(AdditionalOptions)", ""))
            elif tag == "ExcludedFromBuild" and text.lower() == "true":
                excluded = True
        if excluded:
            continue
        args = []
        if model:
            args.append(FP_MODEL_OPTION.get(model, f"/fp:{model}"))
        settings[normalise(include, Path(path).parent)] = args + extra
    return settings


def directory_build_files(start):
    """Directory.Build.props and .targets MSBuild would import into a project."""
    found, here = [], Path(start).resolve()
    for directory in [here, *here.parents]:
        for name in ("Directory.Build.props", "Directory.Build.targets"):
            if (directory / name).is_file():
                found.append(str(directory / name))
    return found


# --------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------

def audit(build, configs_wanted, all_configs):
    build = Path(build).resolve()
    profile_path = build / "banjo-fp-profile.json"
    if not profile_path.is_file():
        raise AuditError(f"{profile_path} is missing: this build did not include "
                         "cmake/FloatingPointModel.cmake")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("profile") != PROFILE:
        raise AuditError(f"the build asks for profile {profile.get('profile')!r}, "
                         f"and this audit knows {PROFILE!r}")
    family = profile.get("family")
    if family not in ("msvc", "gnu"):
        raise AuditError(f"no audit rules for compiler family {family!r}")
    reply, codemodel, toolchains = load_reply(build)
    source_dir = codemodel["paths"]["source"]
    build_dir = codemodel["paths"]["build"]

    cxx = next((t for t in toolchains.get("toolchains", []) if t.get("language") == "CXX"), None)
    compiler = (cxx or {}).get("compiler", {})
    if compiler.get("id") and compiler.get("id") != profile.get("compiler_id"):
        raise AuditError(f"the File API says the C++ compiler is {compiler.get('id')}, "
                         f"the profile was written for {profile.get('compiler_id')}")

    configurations = {c["name"]: c for c in codemodel["configurations"]}
    if all_configs:
        chosen = list(configurations)
    elif configs_wanted is not None:
        if configs_wanted not in configurations:
            raise AuditError(f"no configuration {configs_wanted!r} in this build "
                             f"(it has {', '.join(repr(c) for c in configurations)})")
        chosen = [configs_wanted]
    elif len(configurations) == 1:
        chosen = list(configurations)
    else:
        raise AuditError("this build has several configurations: say --config NAME or --all-configs")

    environment = {}
    prefix, suffix, env_problems = [], [], []
    if family == "msvc":
        for name in ("CL", "_CL_"):
            if os.environ.get(name):
                environment[name] = os.environ[name]
        prefix = split_windows(os.environ.get("CL", ""))
        suffix = split_windows(os.environ.get("_CL_", ""))
    elif profile.get("compiler_id") in ("Clang", "AppleClang") and os.environ.get("CCC_OVERRIDE_OPTIONS"):
        environment["CCC_OVERRIDE_OPTIONS"] = os.environ["CCC_OVERRIDE_OPTIONS"]
        env_problems.append("CCC_OVERRIDE_OPTIONS is set, and it edits every clang command line")

    generator = profile.get("generator", "")
    result = {"profile": PROFILE, "family": family, "compiler": compiler, "generator": generator,
              "source": source_dir, "build": build_dir, "environment": environment,
              "configurations": {}, "violations": [], "source_uses": {"allowed": [], "refused": []},
              "jolt_definitions": {}}
    violations = result["violations"]
    for problem in env_problems:
        violations.append({"configuration": "*", "target": "*", "file": "*", "problem": problem})

    scan_files, include_dirs = set(), set()
    for name in chosen:
        config = configurations[name]
        counts = {"cxx_files": 0, "targets": 0, "outside": {}}
        cxx_expected = {}   # normalised source -> times compiled, for the cross-checks
        jolt_defines, jolt_includes, groups_seeing_jolt = None, set(), []
        for ref in config["targets"]:
            target = json.loads((reply / ref["jsonFile"]).read_text(encoding="utf-8"))
            if target.get("type") not in COMPILED_TYPES or target.get("imported"):
                continue
            counts["targets"] += 1
            sources = target.get("sources", [])
            for group in target.get("compileGroups", []):
                language = group.get("language", "")
                files = [normalise(sources[i]["path"], source_dir) for i in group.get("sourceIndexes", [])]
                if language != "CXX":
                    counts["outside"][language] = counts["outside"].get(language, 0) + len(files)
                    continue
                args, origin = [], {}
                for fragment in group.get("compileCommandFragments", []):
                    pieces = split_command(fragment.get("fragment", ""), family)
                    for piece in pieces:
                        origin.setdefault(piece, fragment_origin(target, fragment))
                    args.extend(pieces)
                problems = compile_problems(prefix + args + suffix, family)
                for f in files:
                    counts["cxx_files"] += 1
                    cxx_expected[f] = cxx_expected.get(f, 0) + 1
                    scan_files.add(f)
                    for problem in problems:
                        option = problem.split()[0]
                        violations.append({"configuration": name, "target": target["name"],
                                           "file": os.path.relpath(f, source_dir) if f.startswith(os.path.normcase(source_dir)) else f,
                                           "problem": problem, "added_at": origin.get(option, "")})
                for include in group.get("includes", []):
                    include_dirs.add(normalise(include["path"], source_dir))
                defines = sorted(d["define"] for d in group.get("defines", []) if d["define"].startswith("JPH_"))
                if target["name"] == "Jolt":
                    jolt_defines = defines
                    jolt_includes.update(normalise(i["path"], source_dir) for i in group.get("includes", []))
                else:
                    sees = [normalise(i["path"], source_dir) for i in group.get("includes", [])]
                    groups_seeing_jolt.append((target["name"], defines, sees, files))
            link = target.get("link")
            if link:
                link_args = []
                for fragment in link.get("commandFragments", []):
                    if fragment.get("role") == "flags":
                        link_args.extend(split_command(fragment.get("fragment", ""), family))
                for problem in link_problems(link_args, family):
                    violations.append({"configuration": name, "target": target["name"], "file": "(link)",
                                       "problem": problem})
        # Jolt's feature definitions reach every file that can include Jolt.
        if jolt_defines is not None:
            jolt_root = next((d for d in jolt_includes if (Path(d) / "Jolt" / "Jolt.h").is_file()), None)
            result["jolt_definitions"][name] = jolt_defines
            for target_name, defines, sees, files in groups_seeing_jolt:
                if jolt_root and jolt_root in sees and defines != jolt_defines:
                    missing = sorted(set(jolt_defines) - set(defines))
                    extra = sorted(set(defines) - set(jolt_defines))
                    for f in files:
                        violations.append({"configuration": name, "target": target_name,
                                           "file": os.path.relpath(f, source_dir),
                                           "problem": "sees Jolt's headers with other JPH_ definitions "
                                                      f"than Jolt was built with (missing {missing}, extra {extra})"})
        # What the build tool will really run.
        cross = cross_check(build, name, family, prefix, suffix, cxx_expected, source_dir, generator,
                            configurations, violations)
        counts["commands_cross_checked"] = cross
        result["configurations"][name] = counts

    # Pragmas, attributes and environment calls, in every file the compiled
    # C++ files can include.
    scan_files = reachable_files(sorted(scan_files), sorted(include_dirs))
    for path in sorted(scan_files):
        for line, pattern, text in scan_source(path):
            why = allowed_use(path, pattern, text)
            entry = {"file": path, "line": line, "pattern": pattern, "text": text[:160]}
            if why:
                result["source_uses"]["allowed"].append({**entry, "why": why})
            else:
                result["source_uses"]["refused"].append(entry)
                violations.append({"configuration": "*", "target": "*", "file": f"{path}:{line}",
                                   "problem": f"{pattern}: {text[:120]}"})
    result["files_searched"] = len(scan_files)
    return result


def cross_check(build, name, family, prefix, suffix, expected, source_dir, generator, configurations, violations):
    """Compare the File API's account with the commands the build tool runs."""
    if generator.startswith("Visual Studio"):
        return vs_cross_check(build, name, family, prefix, suffix, expected, source_dir, violations)
    database = build / "compile_commands.json"
    if not database.is_file():
        violations.append({"configuration": name, "target": "*", "file": str(database),
                           "problem": f"no compile_commands.json, so the {generator} commands cannot be checked"})
        return 0
    if len(configurations) != 1:
        return 0   # a multi-config Ninja database is for one configuration only
    seen = {}
    checked = 0
    for entry in json.loads(database.read_text(encoding="utf-8")):
        f = normalise(entry["file"], entry.get("directory", "."))
        if entry.get("arguments"):
            args = list(entry["arguments"])
        else:
            args = split_command(entry["command"], family)
        args = expand_response_files(args[1:], family, entry.get("directory"))
        is_cxx = f in expected
        if not is_cxx:
            continue
        seen[f] = seen.get(f, 0) + 1
        checked += 1
        for problem in compile_problems(prefix + args + suffix, family):
            violations.append({"configuration": name, "target": "(compile_commands.json)",
                               "file": os.path.relpath(f, source_dir), "problem": problem})
    for f, times in expected.items():
        if seen.get(f, 0) != times:
            violations.append({"configuration": name, "target": "(compile_commands.json)",
                               "file": os.path.relpath(f, source_dir),
                               "problem": f"compiled {times} time(s) by the File API's account and "
                                          f"{seen.get(f, 0)} in compile_commands.json"})
    return checked


def vs_cross_check(build, name, family, prefix, suffix, expected, source_dir, violations):
    imports = directory_build_files(build)
    for path in imports:
        violations.append({"configuration": name, "target": "*", "file": path,
                           "problem": "MSBuild imports this into every project the build generates"})
    checked = 0
    found = {}
    for project in build.rglob("*.vcxproj"):
        if "CMakeFiles" in project.parts:
            continue
        for f, args in vcxproj_settings(project, name).items():
            if f not in expected:
                continue
            found[f] = found.get(f, 0) + 1
            checked += 1
            for problem in compile_problems(prefix + args + suffix, family):
                violations.append({"configuration": name, "target": project.stem,
                                   "file": os.path.relpath(f, source_dir), "problem": f"{problem} (in {project.name})"})
    for f, times in expected.items():
        if found.get(f, 0) < times:
            violations.append({"configuration": name, "target": "(vcxproj)", "file": os.path.relpath(f, source_dir),
                               "problem": f"compiled {times} time(s) by the File API's account and "
                                          f"{found.get(f, 0)} in the generated projects"})
    return checked


def report(result, quiet):
    lines = []
    compiler = result["compiler"]
    lines.append(f"Floating-point model {result['profile']} ({result['family']}, "
                 f"{compiler.get('id', '?')} {compiler.get('version', '?')}, {result['generator']})")
    for name, counts in result["configurations"].items():
        outside = ", ".join(f"{lang or '?'} {n}" for lang, n in sorted(counts["outside"].items()))
        lines.append(f"  {name or '(no build type)'}: {counts['cxx_files']} C++ files in {counts['targets']} "
                     f"targets; {counts['commands_cross_checked']} commands cross-checked"
                     + (f"; outside the C++ profile: {outside}" if outside else ""))
    uses = result["source_uses"]
    lines.append(f"  {result['files_searched']} sources and headers searched: "
                 f"{len(uses['allowed'])} allowed uses, {len(uses['refused'])} refused")
    if result["environment"]:
        lines.append(f"  environment: {result['environment']}")
    violations = result["violations"]
    if violations:
        lines.append(f"FAILED: {len(violations)} place(s) would compile outside the profile:")
        for v in violations[:60]:
            where = f" (added at {v['added_at']})" if v.get("added_at") else ""
            lines.append(f"  [{v['configuration'] or '(no build type)'}] {v['target']}: {v['file']}: {v['problem']}{where}")
        if len(violations) > 60:
            lines.append(f"  ... and {len(violations) - 60} more (the manifest has them all)")
        lines.append("  Everything linked into the engine compiles to one floating-point model; "
                     "see cmake/FloatingPointModel.cmake and docs/floating-point-model.md.")
    else:
        lines.append("OK: every C++ file keeps the profile in every configuration audited")
    if not quiet or violations:
        print("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--all-configs", action="store_true")
    parser.add_argument("--manifest")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = audit(args.build, args.config, args.all_configs)
    except AuditError as error:
        print(f"Floating-point model: the audit could not be done: {error}")
        return 2
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(result, indent=1), encoding="utf-8")
    report(result, args.quiet)
    return 1 if result["violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
