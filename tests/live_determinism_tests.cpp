// The same world, twice, must come out the same.
//
// Jolt's contact collector is filled from its worker threads under a mutex, so
// the order contacts arrive in is a thread-completion order -- it is not the
// same twice. Everything that reads contacts in sequence and keeps one of them
// inherits that: `judgeStep` keeps the hardest contact on a struck body as its
// partner for the island a fracture would build, and two contacts can be
// equally hard, so on the arrival order the partner was a different body from
// run to run and the break that followed was a different break.
//
// Measured before the fix, a held ball let go from 1.4 m over a broken plate:
// the room came to rest as 376 bodies, then 380, then 376 again, in one
// process with one binary and one input. The live world's two lanes -- the
// library in this process and the engine in its own -- then disagreed about
// what was in the room roughly one run in three, which is what this is really
// about: a world that cannot repeat itself cannot be compared with anything,
// including itself.
//
// The fix is a total order over the contacts themselves
// (ImpactEvent.hpp hardestContactFirst). This pins it: the scene here is the
// one that was flaky, and it is run twice in one process with the threads
// left on, because a single-threaded run would pass either way and prove
// nothing.

#include "fastlattice/LiveWorld.hpp"

#include <cmath>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &what) {
    if (!ok) throw std::runtime_error(what);
}

// The fracture lab's own default scene, which is the one that was flaky: a
// 10 mm glass plate bridged between two iron piers at 10 mm cells, struck by a
// 60 mm iron ball already moving at 6.26 m/s. One cell thick, spanned, and
// right on the edge of how far it comes apart -- which is what it takes for
// the order two equally hard contacts arrive in to change the answer.
TileImpactRequest plateOnPiers() {
    TileImpactRequest r;
    r.cell_size_m = 0.01;
    r.backend = BackendKind::CpuParallel;   // as the world runs it
    SceneBody left, right, pane, ball;
    left.name = "pier left";
    left.shape = BodyShape::Box;
    left.material = MaterialPreset::Iron;
    left.dimensions_m = {0.06, 0.50, 0.20};
    left.center_m = {-0.095, 0.25, 0.0};
    left.anchored = true;
    right = left;
    right.name = "pier right";
    right.center_m = {0.095, 0.25, 0.0};
    pane.name = "glass plate";
    pane.shape = BodyShape::Box;
    pane.material = MaterialPreset::Glass;
    pane.dimensions_m = {0.25, 0.01, 0.20};
    pane.center_m = {0.0, 0.505, 0.0};
    ball.name = "iron ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.06, 0.06, 0.06};
    ball.center_m = {0.0, 0.560, 0.0};
    ball.velocity_m_s = {0.0, -6.26418390534633, 0.0};
    r.bodies = {left, right, pane, ball};
    return r;
}

// Everything in the world, to the micrometre, as one string.
std::string settledWorld() {
    const auto live = LiveWorld::open(plateOnPiers());
    const double dt = 1.0 / 240.0;

    const auto stepTo = [&](double until) {
        while (live->time_s() < until - 1e-12) {
            live->step(dt);
            for (const std::string &name : live->breakable()) live->fracture(name, 0.003);
        }
    };

    // Break it, then pick a piece up, carry it and let it go: a released body
    // lands among debris, and every landing is another pair of contacts to put
    // in order. This is the sequence the two lanes disagreed over.
    stepTo(0.4);
    std::string held;
    for (const LiveBodyPose &body : live->poses())
        if (!body.anchored && body.name != "pane") { held = body.name; break; }
    require(!held.empty(), "nothing in the room could be picked up");
    if (live->grab(held)) {
        live->moveHeld({0.1, 1.4, 0.0});
        live->step(dt);
        live->release();
    }
    stepTo(3.0);

    std::ostringstream out;
    for (const LiveBodyPose &body : live->poses())
        out << body.name << ' '
            << std::llround(body.position_m.x * 1e6) << ' '
            << std::llround(body.position_m.y * 1e6) << ' '
            << std::llround(body.position_m.z * 1e6) << '\n';
    return out.str();
}

std::size_t lines(const std::string &s) {
    std::size_t n = 0;
    for (const char c : s) n += c == '\n';
    return n;
}

void theSameWorldFourTimesIsTheSameWorld() {
    // Four, not two. Without a contact order this scene came out three
    // different ways in four runs, so a pair agrees by luck often enough to be
    // believed -- and a test believed wrongly is worse than one that fails.
    const std::string first = settledWorld();
    require(lines(first) > 8, "nothing broke, so this proves nothing");
    for (int attempt = 2; attempt <= 4; ++attempt) {
        const std::string again = settledWorld();
        if (first == again) continue;
        std::istringstream a(first), b(again);
        std::string x, y;
        std::size_t line = 0;
        while (std::getline(a, x)) {
            ++line;
            if (std::getline(b, y) && x == y) continue;
            throw std::runtime_error(
                "run " + std::to_string(attempt) + " came out differently at line " +
                std::to_string(line) + ": \"" + x + "\" then \"" + y + "\" (" +
                std::to_string(lines(first)) + " bodies then " +
                std::to_string(lines(again)) + ")");
        }
        throw std::runtime_error(
            "run " + std::to_string(attempt) + " came out a different length: " +
            std::to_string(lines(first)) + " bodies then " + std::to_string(lines(again)));
    }
    std::cout << "  the same world four times: " << lines(first) << " bodies, identical\n";
}

}  // namespace

int main() {
    try {
        theSameWorldFourTimesIsTheSameWorld();
    } catch (const std::exception &error) {
        std::cerr << "live determinism: " << error.what() << "\n";
        return 1;
    }
    std::cout << "live determinism: the world repeats itself\n";
    return 0;
}
