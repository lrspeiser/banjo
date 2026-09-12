#!/usr/bin/env bash
# The whole physics regression, in Release.
#
# Not the tests next to whatever was just changed -- all of them. Adding sliding
# joints meant generalising the engine's joint table and changing how a HELD
# body is driven, and the hand is used by every scene in the playground, not
# just the ones with mechanisms in them. A change like that passes every joint
# test and can still break fracture, contact or materials somewhere else.
#
# RELEASE, always. A Debug build is about ten times slower, and the timing tests
# -- foresight's warning against what the lattice run costs -- fail for the
# build configuration rather than for anything real. That has sent me looking
# for a regression that was not there.
#
#   scripts/regression.sh            everything except the four slow suites
#   scripts/regression.sh --all      everything, including those
#   scripts/regression.sh --list     what would run
#
# Takes about four minutes without --all; an hour or more with it.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
BUILD=build/integration
CONFIG=Release
LIB="$PWD/$BUILD/$CONFIG/banjo.dll"

# Measured in minutes rather than seconds, and excluded unless asked for. They
# are not flaky and they are not unimportant -- they are long.
#
#   banjo_contact_capacity_tests   973 s, from ctest's own cost data
#   banjo_network_skin_tests       30+ min, burning a whole core the entire time
#   banjo_material_showcase_tests  minutes
#   banjo_network_runtime_tests    minutes
#
# The skin one is the reason this list is worth keeping: it is not in anybody's
# notes, it had never once completed in this build directory, and the first full
# sweep sat on it for half an hour looking exactly like a hang. It is not a
# hang -- 1,839 s of CPU for 32 minutes of wall is a test doing work -- but a
# regression you run "from time to time" has to finish, or you stop running it.
SLOW="banjo_material_showcase_tests|banjo_contact_capacity_tests|banjo_network_runtime_tests|banjo_network_skin_tests"

want_all=0
list_only=0
for arg in "$@"; do
    case "$arg" in
        --all) want_all=1 ;;
        --list) list_only=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# Anything holding the binaries open makes the next build fail with LNK1104,
# and a stale binary that still runs is worse than one that will not link.
#
# Including the TEST binaries. A sweep stopped part-way -- which is what happens
# whenever the 30-minute suite is not worth waiting for -- leaves its test
# process running and its .exe locked, and the next run fails to link a file
# nobody has touched. That looked like a build problem for a while and is a
# leftover process.
taskkill //F //IM banjo_live_world_run.exe >/dev/null 2>&1
taskkill //F //IM banjo_platform_cli.exe >/dev/null 2>&1
# By PID, not by name: tasklist truncates the image name to 25 characters and
# adds a dot, so "banjo_network_skin_tests.exe" comes back as
# "banjo_network_skin_tests." and //IM matches nothing at all -- silently, which
# is the worst way for a cleanup step to fail.
for stuck in $(tasklist 2>/dev/null | awk '/^banjo_/ {print $2}'); do
    taskkill //F //PID "$stuck" >/dev/null 2>&1
done
# And a BUILD that was interrupted. MSBuild keeps compiling after whatever
# started it has gone, and it holds every .obj it is writing -- so the next run
# fails with "Permission denied" on a dozen object files and a LNK1104, which
# reads as a broken tree and is one orphaned compiler. Only cleared when no
# build is wanted; see the guard, because this would otherwise shoot the build
# this script is about to start.
if [ "${BANJO_KEEP_BUILDERS:-0}" != "1" ]; then
    for builder in $(tasklist 2>/dev/null | awk '/^(MSBuild|cl|link|mspdbsrv)\.exe/ {print $2}'); do
        taskkill //F //PID "$builder" >/dev/null 2>&1
    done
fi

if [ "$list_only" = 1 ]; then
    ctest --test-dir "$BUILD" -C "$CONFIG" -N | sed -n 's/.*: //p'
    exit 0
fi

echo "building $CONFIG..."
if ! cmake --build "$BUILD" --config "$CONFIG" > /tmp/banjo-build.log 2>&1; then
    echo "BUILD FAILED:"
    grep -iE " error |LNK[0-9]+|FAILED" /tmp/banjo-build.log | head -20
    exit 1
fi
echo "built."

export BANJO_LIBRARY="$LIB"
args=(--test-dir "$BUILD" -C "$CONFIG" --output-on-failure)
[ "$want_all" = 1 ] || args+=(-E "$SLOW")

started=$(date +%s)
ctest "${args[@]}" 2>&1 | tail -40
code=${PIPESTATUS[0]}
echo "took $(( $(date +%s) - started )) s"
[ "$want_all" = 1 ] || echo "(the four long suites were skipped; --all runs them)"
exit "$code"
