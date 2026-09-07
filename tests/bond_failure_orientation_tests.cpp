// Orientation of the brittle bond failure criterion.
//
// The nonlocal node strain is a tensor. Judging a bond by the maximum principal
// value of that tensor makes failure direction-blind: under uniaxial tension a
// bond lying perpendicular to the loading axis fails on strain it does not
// carry, and every bond touching a highly strained node fails in the same step,
// so damage can only detach single nodes instead of forming a crack surface.
// These checks pin the resolved-along-the-bond criterion.

#include "fracture/BrittleBondSolver.hpp"
#include "fracture/ConnectedComponents.hpp"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

namespace {
using namespace banjo;

void require(bool result, const char *message) {
    if (!result) throw std::runtime_error(message);
}

constexpr double kInfinity = std::numeric_limits<double>::infinity();

// A 3x3x3 cubic lattice of unit-spaced nodes with axis-aligned nearest-neighbour
// bonds only, so every bond direction is exactly x, y or z.
struct AxisLattice {
    LatticeAsset asset;
    ActiveMatter matter;
    std::vector<Vec3> directions;

    AxisLattice(double damage_start, double damage_end) {
        asset.recipe.voxel_size_m = 1;
        for (int z = 0; z < 3; ++z)
            for (int y = 0; y < 3; ++y)
                for (int x = 0; x < 3; ++x) {
                    asset.nodes.push_back({});
                    matter.nodes.push_back({{static_cast<double>(x), static_cast<double>(y),
                                             static_cast<double>(z)}, {}, {}, 1, {}});
                }
        const auto index = [](int x, int y, int z) {
            return static_cast<std::uint32_t>(x + 3 * y + 9 * z);
        };
        for (int z = 0; z < 3; ++z)
            for (int y = 0; y < 3; ++y)
                for (int x = 0; x < 3; ++x)
                    for (const auto step : {std::array<int, 3>{1, 0, 0},
                                            std::array<int, 3>{0, 1, 0},
                                            std::array<int, 3>{0, 0, 1}}) {
                        const int nx = x + step[0], ny = y + step[1], nz = z + step[2];
                        if (nx > 2 || ny > 2 || nz > 2) continue;
                        asset.bonds.push_back({index(x, y, z), index(nx, ny, nz), 1, 1e-6,
                            damage_start, damage_end, kInfinity, kInfinity, kInfinity, kInfinity});
                        directions.push_back({static_cast<double>(step[0]),
                                              static_cast<double>(step[1]),
                                              static_cast<double>(step[2])});
                    }
        std::vector<std::uint32_t> degree(asset.nodes.size(), 0U);
        for (const auto &bond : asset.bonds) { ++degree[bond.node_a]; ++degree[bond.node_b]; }
        asset.adjacency_offsets.assign(asset.nodes.size() + 1U, 0U);
        for (std::size_t n = 0; n < asset.nodes.size(); ++n)
            asset.adjacency_offsets[n + 1U] = asset.adjacency_offsets[n] + degree[n];
        asset.adjacent_bond_indices.resize(asset.adjacency_offsets.back());
        auto cursor = asset.adjacency_offsets;
        for (std::uint32_t b = 0; b < asset.bonds.size(); ++b) {
            asset.adjacent_bond_indices[cursor[asset.bonds[b].node_a]++] = b;
            asset.adjacent_bond_indices[cursor[asset.bonds[b].node_b]++] = b;
        }
        matter.asset = &asset;
        matter.bonds.resize(asset.bonds.size());
        for (const auto &node : matter.nodes)
            matter.reference_positions_world_m.push_back(node.position_world_m);
    }

    // Impose an affine uniaxial stretch along x with the matching lateral
    // Poisson contraction, then let one solver step resolve the strain history.
    void stretchAlongX(double strain, double poisson) {
        for (auto &node : matter.nodes) {
            node.position_world_m.x *= 1 + strain;
            node.position_world_m.y *= 1 - poisson * strain;
            node.position_world_m.z *= 1 - poisson * strain;
        }
    }
};

// Under uniaxial tension only the bonds carrying that tension may be damaged.
void perpendicularBondsDoNotFailUnderUniaxialTension() {
    AxisLattice lattice(.004, .008);
    lattice.stretchAlongX(.01, .25);
    BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1, .support_enabled = false});
    // A tiny step keeps the elastic solve from relaxing the imposed geometry
    // before the strain history is accumulated.
    (void)solver.step(lattice.matter, 1e-9, {});
    std::size_t axial_broken = 0, transverse_broken = 0, transverse_total = 0;
    for (std::size_t i = 0; i < lattice.matter.bonds.size(); ++i) {
        const bool axial = lattice.directions[i].x > .5;
        if (!axial) ++transverse_total;
        if (lattice.matter.bonds[i].alive) continue;
        if (axial) ++axial_broken; else ++transverse_broken;
    }
    require(transverse_total > 0, "the fixture must contain transverse bonds");
    require(axial_broken > 0, "bonds aligned with the tension must fail above the break strain");
    require(transverse_broken == 0,
            "bonds perpendicular to a uniaxial tension carry compression and must not fail");
}

// The consequence for topology: an oriented criterion can leave a node attached
// by its surviving transverse bonds instead of detaching it as a single point.
void orientedFailureLeavesMultiNodeComponents() {
    AxisLattice lattice(.004, .008);
    lattice.stretchAlongX(.01, .25);
    BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1, .support_enabled = false});
    (void)solver.step(lattice.matter, 1e-9, {});
    const auto components = findConnectedComponents(lattice.matter);
    require(components.size() > 1, "severing every axial bond must separate the lattice");
    for (const auto &component : components)
        require(component.node_indices.size() > 1,
                "an oriented criterion must not reduce every fragment to one node");
}

// The transverse strain still governs failure in its own direction, so the
// criterion is oriented rather than simply weaker.
void alignedBondsStillFailInEachDirection() {
    for (const int axis : {0, 1, 2}) {
        AxisLattice lattice(.004, .008);
        for (auto &node : lattice.matter.nodes) {
            Vec3 &p = node.position_world_m;
            const double along = axis == 0 ? p.x : axis == 1 ? p.y : p.z;
            const double scaled = along * 1.01;
            if (axis == 0) { p.x = scaled; p.y *= .9975; p.z *= .9975; }
            else if (axis == 1) { p.y = scaled; p.x *= .9975; p.z *= .9975; }
            else { p.z = scaled; p.x *= .9975; p.y *= .9975; }
        }
        BrittleBondSolver solver({.substeps = 1, .constraint_iterations = 1, .support_enabled = false});
        (void)solver.step(lattice.matter, 1e-9, {});
        std::size_t aligned_broken = 0, other_broken = 0;
        for (std::size_t i = 0; i < lattice.matter.bonds.size(); ++i) {
            if (lattice.matter.bonds[i].alive) continue;
            const Vec3 &d = lattice.directions[i];
            const double along = axis == 0 ? d.x : axis == 1 ? d.y : d.z;
            if (along > .5) ++aligned_broken; else ++other_broken;
        }
        require(aligned_broken > 0, "the loaded direction must fail on every axis");
        require(other_broken == 0, "only the loaded direction may fail");
    }
}

} // namespace

int main() {
    try {
        perpendicularBondsDoNotFailUnderUniaxialTension();
        std::cout << "[PASS] transverse bonds survive uniaxial tension\n";
        orientedFailureLeavesMultiNodeComponents();
        std::cout << "[PASS] oriented failure yields multi-node components\n";
        alignedBondsStillFailInEachDirection();
        std::cout << "[PASS] each loading axis fails its own bonds\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
