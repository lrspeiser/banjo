// A body that comes out of a lattice run with everything it went in with is
// still itself, and must keep its name.
//
// A run can break bonds inside a body without separating anything from it. The
// body is then the same body, bent: its name has to stand, because the name is
// what the already-answered set is keyed on (`held_through`). Rename it and the
// new name has never been tried at this contact, so the host is offered it
// again, runs it again, and gets another new name -- for ever, at a few hundred
// milliseconds a turn.
//
// That is what happened. `applyPending` asked "is this component all of its
// PART?", which a fragment can never be, so every fragment that broke bonds
// without shedding a cell was renamed. Measured on a glass tabletop before the
// fix: one body asked sixteen times at a single instant, its name grown to
// "... piece 1" thirty-four times over, and 9.7 s of a 14.3 s drop test spent on
// runs that separated nothing. The same test is 3.9 s after it.
//
// The scene here is an ice plate bridged on piers and struck hard, which is the
// cheapest thing that makes a cascade of fragments that keep wanting to break:
// 66 of its runs come back with one piece, and each of those bodies has to still
// be there under the name it was asked by.

#include "fastlattice/LiveWorld.hpp"

#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &what) {
    if (!ok) throw std::runtime_error(what);
}

// 300 x 20 x 300 mm of ice bridged between two iron piers, a 100 mm iron ball
// dropped on it from 12 m. Ice because it comes apart into the most pieces of
// any material in the catalogue, so the cascade is deep and the case is met many
// times in one run rather than once by luck.
TileImpactRequest platePlusPiers() {
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.backend = BackendKind::CpuParallel;
    SceneBody left, right, plate, ball;
    left.name = "pier left";
    left.shape = BodyShape::Box;
    left.material = MaterialPreset::Iron;
    left.dimensions_m = {0.04, 0.20, 0.30};
    left.center_m = {-0.13, 0.10, 0.0};
    left.anchored = true;
    right = left;
    right.name = "pier right";
    right.center_m = {0.13, 0.10, 0.0};
    plate.name = "plate";
    plate.shape = BodyShape::Box;
    plate.material = MaterialPreset::Ice;
    plate.dimensions_m = {0.30, 0.02, 0.30};
    plate.center_m = {0.0, 0.21, 0.0};
    ball.name = "ball";
    ball.shape = BodyShape::Sphere;
    ball.material = MaterialPreset::Iron;
    ball.dimensions_m = {0.10, 0.10, 0.10};
    ball.center_m = {0.0, 12.0, 0.0};
    r.bodies = {left, right, plate, ball};
    return r;
}

void aBodyThatShedNothingKeepsItsName() {
    const auto live = LiveWorld::open(platePlusPiers());
    const double dt = 1.0 / 120.0;
    std::size_t held_runs = 0, on_fragments = 0, asked_twice_over = 0;
    for (int tick = 0; tick < 900; ++tick) {
        live->step(dt);
        for (int guard = 0; guard < 64; ++guard) {
            const std::vector<std::string> offered = live->breakable();
            if (offered.empty()) break;
            const std::string name = offered.front();
            const bool fragment = name.find(" piece ") != std::string::npos;
            const std::size_t pieces = live->fracture(name, 0.003);
            if (pieces != 1) continue;
            // It held: nothing came off it, so it is the same body and must
            // still be in the world under the name it was asked by.
            ++held_runs;
            if (fragment) ++on_fragments;
            bool still_there = false;
            for (const LiveBodyPose &body : live->poses())
                if (body.name == name) { still_there = true; break; }
            require(still_there,
                    "a run that separated nothing renamed \"" + name +
                        "\", so the same contact will be offered again for ever");
            // And it must not be offered again for the same contact.
            const std::vector<std::string> again = live->breakable();
            for (const std::string &offered_now : again)
                if (offered_now == name) ++asked_twice_over;
        }
    }
    require(held_runs >= 8, "this scene stopped producing runs that hold (" +
                                std::to_string(held_runs) + "); it proves nothing");
    require(on_fragments >= 4, "no run that held was on a FRAGMENT (" +
                                  std::to_string(on_fragments) +
                                  "), which is the case that was broken");
    require(asked_twice_over == 0,
            std::to_string(asked_twice_over) +
                " bodies were offered again straight after coming through whole");
    std::cout << "  " << held_runs << " runs held, " << on_fragments
              << " of them on fragments, none renamed and none re-offered\n";
}

}  // namespace

int main() {
    try {
        aBodyThatShedNothingKeepsItsName();
    } catch (const std::exception &error) {
        std::cerr << "fragment identity: " << error.what() << "\n";
        return 1;
    }
    std::cout << "fragment identity: a body that shed nothing is still itself\n";
    return 0;
}
