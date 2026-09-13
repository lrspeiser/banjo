#include "fracture/SustainedLoad.hpp"

#include "fracture/BondFailure.hpp"
#include "fracture/ConnectedComponents.hpp"
#include "fracture/QuasiStaticFracture.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

// Which connected piece each node is in, over the live bonds: the solver
// deflates each piece's rigid modes on its own.
std::vector<std::uint32_t> componentOfNode(const ActiveMatter &matter) {
    std::vector<std::uint32_t> of(matter.nodes.size(), 0U);
    const auto components = findConnectedComponents(matter);
    for (std::size_t k = 0; k < components.size(); ++k)
        for (const std::uint32_t node : components[k].node_indices)
            if (node < of.size()) of[node] = static_cast<std::uint32_t>(k);
    return of;
}

// The largest ratio of a live bond's recorded peak to its removal threshold:
// the dynamic lane's own measure of how near the lattice is to failing.
double failureRatio(const ActiveMatter &matter) {
    double ratio = 0.0;
    for (std::size_t b = 0; b < matter.bonds.size(); ++b) {
        const ActiveBondState &state = matter.bonds[b];
        if (!state.alive) continue;
        const BondRest &rest = matter.asset->bonds[b];
        const auto part = [](double peak, double end) { return std::isfinite(end) && end > 0.0 ? peak / end : 0.0; };
        ratio = std::max({ratio, part(state.peak_tensile_stretch, rest.damage_end_stretch),
                          part(state.peak_compressive_strain, rest.compression_damage_end_strain),
                          part(state.peak_shear_strain, rest.shear_damage_end_strain)});
    }
    return ratio;
}

}  // namespace

SustainedLoadResult solveSustainedLoad(ActiveMatter &matter, const SustainedLoadScene &scene,
                                       const SustainedLoadSettings &settings) {
    SustainedLoadResult out;
    const std::size_t count = matter.nodes.size();
    if (matter.asset == nullptr || count == 0) throw std::invalid_argument("a sustained load needs matter");
    if (scene.loads_n.size() != count) throw std::invalid_argument("a sustained load needs one force per node");
    if (matter.reference_positions_world_m.size() != count)
        throw std::invalid_argument("a sustained load needs the matter's reference configuration");
    const std::vector<Vec3> &reference = matter.reference_positions_world_m;

    // Displacements are from the reference configuration, starting from where
    // the matter was given: a body that came in bent starts bent.
    std::vector<Vec3> displacement(count);
    for (std::size_t i = 0; i < count; ++i) displacement[i] = matter.nodes[i].position_world_m - reference[i];
    // A support holds a node where it was given, against moving down.
    std::vector<double> held_at(count, 0.0);
    for (const std::uint32_t node : scene.supported_nodes)
        if (node < count) held_at[node] = displacement[node].y;

    StaticLatticeSolver solver(matter);
    std::vector<std::uint32_t> component_of = componentOfNode(matter);
    const auto piecesIn = [](const std::vector<std::uint32_t> &of) {
        return of.empty() ? std::size_t{0}
                          : static_cast<std::size_t>(*std::max_element(of.begin(), of.end())) + 1;
    };
    // What it came in as: a lattice its dead bonds already part (char carries
    // nothing) is not broken again by being asked.
    const std::size_t pieces_given = piecesIn(component_of);
    std::vector<std::uint32_t> supports = scene.supported_nodes;
    // Whether the supports it bears on are in more than one piece: the load
    // path between them has been cut.
    const auto supportsParted = [&](const std::vector<std::uint32_t> &of) {
        bool seen = false;
        std::uint32_t first = 0;
        for (const std::uint32_t node : supports) {
            if (node >= of.size()) continue;
            if (!seen) {
                first = of[node];
                seen = true;
            } else if (of[node] != first) {
                return true;
            }
        }
        return false;
    };
    const bool parted_given = supportsParted(component_of);
    StaticSolveSettings solve_settings;
    solve_settings.relative_tolerance = settings.relative_tolerance;
    solve_settings.maximum_iterations = settings.maximum_iterations;

    const auto place = [&]() {
        for (std::size_t i = 0; i < count; ++i) {
            matter.nodes[i].position_world_m = reference[i] + displacement[i];
            matter.nodes[i].previous_position_world_m = matter.nodes[i].position_world_m;
            matter.nodes[i].velocity_m_s = {};
        }
    };

    for (unsigned round = 0; round < settings.maximum_rounds; ++round) {
        out.rounds = round + 1;
        // Equilibrium with every support that pushes; one that would have to
        // pull is let go and the lattice solved again without it.
        bool solved_ok = false;
        for (unsigned pass = 0; pass < settings.maximum_support_passes; ++pass) {
            std::vector<StaticConstraint> constraints;
            constraints.reserve(supports.size());
            for (const std::uint32_t node : supports)
                constraints.push_back({node, Vec3{0.0, 1.0, 0.0}, held_at[node], true});
            const StaticSolveResult solved =
                solver.solve(scene.loads_n, constraints, displacement, solve_settings, &component_of);
            ++out.solves;
            if (!solved.converged) {
                out.stop = std::string("did not converge") + (solved.failure ? std::string(": ") + solved.failure : "");
                place();
                out.displacement_m = displacement;
                return out;
            }
            double largest = 0.0;
            for (const double reaction : solved.reactions_n) largest = std::max(largest, std::abs(reaction));
            std::vector<std::uint32_t> pushing;
            pushing.reserve(supports.size());
            for (std::size_t k = 0; k < supports.size(); ++k) {
                if (solved.reactions_n[k] < -1.0e-9 * largest) {
                    ++out.supports_released;
                    continue;
                }
                pushing.push_back(supports[k]);
            }
            if (pushing.size() == supports.size()) {
                solved_ok = true;
                break;
            }
            supports = std::move(pushing);
        }
        if (!solved_ok) {
            out.stop = "supports did not settle";
            break;
        }
        // The shared criterion, on the strain this equilibrium gives.
        place();
        resetBondStrainPeaks(matter);
        accumulateBondStrainPeaks(matter);
        if (round == 0) {
            out.first_failure_ratio = failureRatio(matter);
            for (std::size_t i = 0; i < count; ++i)
                out.first_deflection_m = std::max(out.first_deflection_m, std::abs(displacement[i].y));
        }
        std::vector<std::uint32_t> failing;
        std::vector<BondFailureMode> modes;
        for (std::size_t b = 0; b < matter.bonds.size(); ++b) {
            if (!matter.bonds[b].alive) continue;
            const BondDamageEvaluation damage = evaluateBondDamage(matter.bonds[b], matter.asset->bonds[b]);
            if (damage.damage < 1.0) continue;
            failing.push_back(static_cast<std::uint32_t>(b));
            modes.push_back(damage.mode);
        }
        if (failing.empty()) {
            // Nothing more fails at this load. It held -- cracked on the way
            // (bonds_removed) or not -- unless pieces came off it as it went.
            out.converged = true;
            out.stop = piecesIn(component_of) > pieces_given ? "broke" : "held";
            break;
        }
        (void)removeBondsAtCurrentState(matter, failing, modes);
        out.bonds_removed += failing.size();
        solver.rebuild();
        component_of = componentOfNode(matter);
        // Broken through between its supports. What its pieces do from here is
        // motion, which the rigid world answers; went on, statics would keep the
        // load where it was on pieces that are falling. It did, once: a concrete
        // shelf under five 450 mm iron crates was in 70 pieces after three
        // rounds, and a fourth solve on those pieces spent 840 ms running out of
        // its iteration budget and said "did not converge" over a shelf in
        // pieces. A chip that comes off without parting the supports is not
        // that: the rest still spans between them and is solved again without
        // it. (Stopping at the first chip instead left the owner's heated beam
        // 7 cells lighter and carrying its 212 kg cube on a section that read 0%.)
        if (!parted_given && supportsParted(component_of)) {
            out.converged = true;
            out.stop = "broke";
            break;
        }
        if (round + 1 == settings.maximum_rounds) out.stop = "round limit";
    }
    place();
    out.displacement_m = displacement;
    return out;
}

} // namespace banjo
