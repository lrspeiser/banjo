#pragma once

// A body carrying a sustained load: statics, not a blow.
//
// Every other break the live world works out starts from a contact -- a
// closing speed, an impedance, an energy -- and is run in the dynamic lattice
// for a few milliseconds. A shelf with too much stacked on it is struck by
// nothing, and a few milliseconds is a hundredth of the time a loaded beam
// takes to bend: measured (tests/thermal_geometry_tests.cpp), a loaded oak
// plank put into that run arrived with no supports under it, fell freely with
// its load, and broke -- or did not -- on how far the resting load's cells had
// sunk into it, which is the rigid solver's contact allowance and not the load.
//
// So a sustained load is answered the way statics answers it. The body's own
// lattice -- its bonds as heat has left them (docs/thermal-mechanics.md) -- is
// solved for equilibrium under its own weight and the weight of what rests on
// it, held up where it rests on something; the ONE shared failure criterion
// (fracture/BondFailure.hpp, unchanged) is applied to the strain that gives;
// every bond past it is removed, the lattice is solved again, and so on until
// nothing more fails or it breaks through between its supports. Pieces are
// what is left connected.
// Nothing is precut, animated or pushed.
//
// What statics cannot say, it says it cannot: supports are unilateral (a piece
// that would have to be pulled down to stay put is let go, and rigid modes it
// is then free to perform are deflated and reported), and a solve that does
// not converge stops the run and says so rather than guessing.

#include "core/Math.hpp"
#include "fracture/ActiveMatter.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace banjo {

struct SustainedLoadScene {
    // Per node of the matter: the force on it, newtons -- its own weight, and
    // its share of the weight resting on it.
    std::vector<Vec3> loads_n;
    // Nodes held from below where the body rests on something: unilateral,
    // along +y. A support that would have to pull is let go.
    std::vector<std::uint32_t> supported_nodes;
};

struct SustainedLoadSettings {
    unsigned maximum_rounds{400};
    unsigned maximum_support_passes{24};
    double relative_tolerance{1.0e-9};
    unsigned maximum_iterations{200000};
};

struct SustainedLoadResult {
    bool converged{};
    // "held": nothing more reaches the criterion at this load and it is still
    // in the pieces it was given (bonds_removed says whether it cracked);
    // "broke": it came apart -- statics stops as soon as the supports it bears
    // on are in different pieces, because what they do next is motion, and a
    // chip that comes off without parting them is solved on without; or why it
    // stopped: "supports did not settle", "did not converge" (with the solver's
    // reason), "round limit".
    std::string stop;
    unsigned rounds{};
    unsigned solves{};
    std::size_t bonds_removed{};
    // The largest ratio of a live bond's strain to its removal threshold at the
    // first solve: below one, the lattice carries the load; how far below is
    // how much margin it has. The same criterion the dynamic lane applies.
    double first_failure_ratio{};
    double first_deflection_m{};
    // Supports let go because they would have had to pull.
    std::size_t supports_released{};
    // The displacement of every node from where it was given, at the end.
    std::vector<Vec3> displacement_m;
};

// `matter` is changed: removed bonds are marked dead with their failure mode,
// and every node is left at its equilibrium position with zero velocity.
[[nodiscard]] SustainedLoadResult solveSustainedLoad(ActiveMatter &matter, const SustainedLoadScene &scene,
                                                     const SustainedLoadSettings &settings = {});

} // namespace banjo
