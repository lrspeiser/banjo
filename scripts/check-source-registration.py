"""Fail when a C++ source file under src/ or tests/ is never added to a build target.

A file that no CMake target lists is compiled by nobody: it does not fail to build,
its tests never run, and nothing reports it. Four such .cpp files, with their
headers, sat committed in this repository for days; one failed its own tests the
day it was finally wired in.

Every source file under the roots below must either appear in the argument list of
an `add_library`, `add_executable` or `target_sources` command, or be named in
INTENTIONALLY_UNBUILT with a reason and a `docs/` reference. An unlisted orphan is
an error. A listed one is fine, but stays visible: this script prints the allowlist
on every run, and fails if an entry becomes stale (file deleted) or redundant (the
file is now in a target), so an exclusion cannot quietly become permanent.

Run it locally from anywhere:

    python scripts/check-source-registration.py

Exit status is 0 when every source file is accounted for and 1 otherwise. There are
no third-party dependencies; Python 3.9 or newer is enough.
"""
from pathlib import Path
import argparse
import os
import re
import sys

# Source files under these roots must be registered in a CMake target.
CHECKED_ROOTS = ('src', 'tests')

SOURCE_SUFFIXES = ('.cpp', '.cc', '.cxx', '.c++', '.c')

# CMake commands that put a file into a build target.
SOURCE_COMMANDS = ('add_library', 'add_executable', 'target_sources')

# Commands that would make source registration unverifiable by reading the text.
UNVERIFIABLE_COMMANDS = ('aux_source_directory',)

# Directories never searched, plus any directory holding a CMakeCache.txt (a build tree).
SKIPPED_DIRS = ('__pycache__', 'node_modules')

# Sources that are deliberately committed without being built. Each entry needs a
# reason naming an existing docs/*.md file that explains and bounds the exclusion.
# Remove an entry as soon as its file is registered or deleted; a stale entry fails.
INTENTIONALLY_UNBUILT = {}


def strip_comments(text):
    """Remove CMake # comments, leaving quoted strings intact."""
    out = []
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == '\\' and index + 1 < len(text):
                out.append(text[index:index + 2])
                index += 2
                continue
            if char == '"':
                quoted = False
            out.append(char)
        elif char == '"':
            quoted = True
            out.append(char)
        elif char == '#':
            while index < len(text) and text[index] != '\n':
                index += 1
            continue
        else:
            out.append(char)
        index += 1
    return ''.join(out)


def split_arguments(text):
    """Split a CMake argument list into arguments, honouring quotes."""
    arguments = []
    current = []
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == '\\' and index + 1 < len(text):
                current.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                quoted = False
            else:
                current.append(char)
        elif char == '"':
            quoted = True
        elif char.isspace():
            if current:
                arguments.append(''.join(current))
                current = []
        else:
            current.append(char)
        index += 1
    if current:
        arguments.append(''.join(current))
    return arguments


COMMAND_START = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)[ \t\r\n]*\(')


def parse_commands(text):
    """Yield (command_name_lowercase, [arguments]) for every command invocation."""
    body = strip_comments(text)
    index = 0
    while True:
        match = COMMAND_START.search(body, index)
        if match is None:
            return
        cursor = match.end()
        depth = 1
        quoted = False
        while cursor < len(body) and depth:
            char = body[cursor]
            if quoted:
                if char == '\\':
                    cursor += 1
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            cursor += 1
        if depth:
            return
        yield match.group(1).lower(), split_arguments(body[match.end():cursor - 1])
        index = cursor


def is_source(argument):
    return argument.lower().endswith(SOURCE_SUFFIXES)


def normalise(path):
    slashed = path.replace('\\', '/')
    while slashed.startswith('./'):
        slashed = slashed[2:]
    return slashed


def collect_cmake_files(repo):
    """Every CMakeLists.txt and .cmake file in the repository, build trees excluded."""
    found = []
    for directory, subdirectories, filenames in os.walk(repo):
        if 'CMakeCache.txt' in filenames:
            subdirectories[:] = []
            continue
        subdirectories[:] = sorted(
            name for name in subdirectories
            if not name.startswith('.') and name not in SKIPPED_DIRS)
        for name in sorted(filenames):
            if name == 'CMakeLists.txt' or name.endswith('.cmake'):
                found.append(Path(directory) / name)
    return found


def collect_sources_on_disk(repo):
    """Every source file under the checked roots, build trees excluded."""
    found = []
    for root in CHECKED_ROOTS:
        if not (repo / root).is_dir():
            raise SystemExit(
                'error: ' + str(repo / root) + ' does not exist, so this check '
                'would pass without inspecting anything. Point --repo at the '
                'repository root.')
        for directory, subdirectories, filenames in os.walk(repo / root):
            if 'CMakeCache.txt' in filenames:
                subdirectories[:] = []
                continue
            subdirectories[:] = sorted(
                name for name in subdirectories
                if not name.startswith('.') and name not in SKIPPED_DIRS)
            for name in sorted(filenames):
                if is_source(name):
                    path = Path(directory) / name
                    found.append(normalise(str(path.relative_to(repo))))
    return sorted(found)


def read_references(repo, cmake_files):
    """Return (registered, mentioned_elsewhere, problems) as repository-relative paths.

    `registered` is what a build target actually compiles. `mentioned_elsewhere` is a
    source path that appears in some other command, which is a useful hint but is not
    registration. `problems` records anything that would make this check unsound.
    """
    registered = set()
    mentioned = set()
    problems = []
    for cmake_file in cmake_files:
        location = normalise(str(cmake_file.relative_to(repo)))
        base = cmake_file.parent
        text = cmake_file.read_text(encoding='utf-8', errors='replace')
        for command, arguments in parse_commands(text):
            if command in UNVERIFIABLE_COMMANDS:
                problems.append(
                    location + ': ' + command + '() adds sources this check cannot '
                    'enumerate. List sources explicitly or teach this script to '
                    'resolve them.')
                continue
            if command == 'file' and arguments and arguments[0].upper() in ('GLOB', 'GLOB_RECURSE'):
                problems.append(
                    location + ': file(' + arguments[0] + ') can feed a target a '
                    'source list this check cannot enumerate. List sources '
                    'explicitly or teach this script to resolve them.')
                continue
            for argument in arguments:
                if not is_source(argument):
                    continue
                if '${' in argument or '$<' in argument:
                    if command in SOURCE_COMMANDS:
                        problems.append(
                            location + ': ' + command + '() takes the unresolved '
                            'source argument "' + argument + '". This check cannot '
                            'expand CMake variables.')
                    continue
                try:
                    resolved = (base / argument).resolve().relative_to(repo.resolve())
                except ValueError:
                    continue
                target = normalise(str(resolved))
                if command in SOURCE_COMMANDS:
                    registered.add(target)
                else:
                    mentioned.add(target)
    return registered, mentioned, problems


def check_allowlist(repo, on_disk, registered):
    """Reject an allowlist entry that is stale, redundant, or not justified."""
    failures = []
    for path, reason in sorted(INTENTIONALLY_UNBUILT.items()):
        if path not in on_disk:
            failures.append(
                path + ': allowlisted but not present under ' +
                '/, '.join(CHECKED_ROOTS) + '/. Delete the allowlist entry.')
            continue
        if path in registered:
            failures.append(
                path + ': allowlisted but now built by a CMake target. Delete the '
                'allowlist entry so a future omission is caught again.')
        documents = re.findall(r'docs/[\w./-]+\.md', reason)
        if not documents:
            failures.append(
                path + ': the allowlist reason must cite the docs/*.md file that '
                'justifies leaving this source out of the build.')
        for document in documents:
            if not (repo / document).is_file():
                failures.append(
                    path + ': the allowlist reason cites ' + document +
                    ', which does not exist.')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--repo', default=str(Path(__file__).resolve().parent.parent),
        help='repository root (default: the parent of scripts/)')
    arguments = parser.parse_args()
    repo = Path(arguments.repo).resolve()

    # Refuse to walk anything before confirming this really is the repository
    # root, so a mistyped --repo cannot report a vacuous pass.
    if not (repo / 'CMakeLists.txt').is_file():
        print('error: ' + str(repo / 'CMakeLists.txt') + ' does not exist. Point '
              '--repo at the repository root.')
        return 1
    on_disk = collect_sources_on_disk(repo)
    cmake_files = collect_cmake_files(repo)
    registered, mentioned, problems = read_references(repo, cmake_files)

    orphans = [
        path for path in on_disk
        if path not in registered and path not in INTENTIONALLY_UNBUILT]
    allowlist_failures = check_allowlist(repo, on_disk, registered)

    print('CMake files read:      ' + str(len(cmake_files)))
    print('Sources under ' + '/, '.join(CHECKED_ROOTS) + '/: ' + str(len(on_disk)))
    print('Registered in a target: ' + str(len(on_disk) - len(orphans) - len(
        [path for path in INTENTIONALLY_UNBUILT if path in on_disk])))
    print('')
    print('Deliberately unbuilt (' + str(len(INTENTIONALLY_UNBUILT)) + '):')
    for path, reason in sorted(INTENTIONALLY_UNBUILT.items()):
        print('  ' + path)
        print('      ' + ' '.join(reason.split()))

    if problems:
        print('')
        print('This check can no longer prove that every source is built:')
        for problem in problems:
            print('  ' + problem)

    if allowlist_failures:
        print('')
        print('Allowlist is out of date:')
        for failure in allowlist_failures:
            print('  ' + failure)

    if orphans:
        print('')
        print(str(len(orphans)) + ' source file(s) belong to no CMake target, so '
              'nothing compiles them:')
        for path in orphans:
            note = ''
            if path in mentioned:
                note = ('  (named in CMake, but not by ' +
                        ', '.join(command + '()' for command in SOURCE_COMMANDS) + ')')
            print('  ' + path + note)
        print('')
        print('Add each file to the target that should compile it, or, if it is '
              'meant to stay out of the build, add it to INTENTIONALLY_UNBUILT in '
              'scripts/check-source-registration.py with a reason citing the '
              'docs/*.md note that justifies it.')

    if orphans or problems or allowlist_failures:
        print('')
        print('FAIL: every source under ' + '/, '.join(CHECKED_ROOTS) +
              '/ must be built or explicitly excluded.')
        return 1
    print('')
    print('OK: every source under ' + '/, '.join(CHECKED_ROOTS) +
          '/ is built by a CMake target or explicitly excluded.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
