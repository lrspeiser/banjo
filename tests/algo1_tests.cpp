// Algorithm 1 checked against the engine it lives in.
//
//  1. The intact modal field is the field an explicit lattice integrates to.
//     An independent leapfrog on the engine's own bond forces (nonlinear, from
//     actual positions, using the asset's compliances) converges at second
//     order onto the library's closed form.
//  2. The Woodbury-corrected static field equals a direct solve of the lattice
//     with the same bonds removed, to roundoff. This is the identity the
//     cascade rests on, checked for one bond and for several at once.
//  3. The screen's bound is never violated by sampling. Every peak the shared
//     criterion records over a swept impact stays under the bound one
//     matrix-vector product produced, on a plate with a full spectrum and on a
//     one-cell-thick plate whose out-of-plane response is a mechanism.

#include "algo1/CrackCascade.hpp"
#include "algo1/ImpulseLibrary.hpp"
#include "fracture/BondFailure.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/Lattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::algo1;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

struct Plate {
    LatticeAsset asset;
    ActiveMatter matter;
    CompiledBrittleMaterial compiled;
    std::vector<std::uint8_t> dof_free;
};

// A uniform-cube plate. `clamp_ring` holds the perimeter ring of cells in every
// axis; otherwise the plate is free and the caller may hold what it likes.
Plate makePlate(MaterialPreset preset, unsigned nx, unsigned ny, unsigned nz, double h, bool clamp_ring) {
    Plate plate;
    const auto material = makeReferenceMaterial(preset, 971);
    plate.compiled = withStrengthDerivedFailure(compileElasticLatticeReference(material, h, 2), material);
    plate.asset = generateBoxLattice({nx, ny, nz, h, 2}, plate.compiled);
    plate.matter.asset = &plate.asset;
    plate.matter.material = plate.compiled;
    plate.matter.bonds.resize(plate.asset.bonds.size());
    plate.dof_free.assign(3U * plate.asset.nodes.size(), 1U);
    for (std::uint32_t i = 0; i < plate.asset.nodes.size(); ++i) {
        const auto &node = plate.asset.nodes[i];
        const Vec3 position = node.local_position_m;
        plate.matter.nodes.push_back(
            {position, position, {}, node.represented_volume_m3 * plate.compiled.density_kg_m3, {}});
        plate.matter.reference_positions_world_m.push_back(position);
        const bool held = clamp_ring && (node.grid.x == 0 || node.grid.z == 0 ||
            node.grid.x + 1 == static_cast<int>(nx) || node.grid.z + 1 == static_cast<int>(nz));
        if (held) for (unsigned axis = 0; axis < 3U; ++axis) plate.dof_free[3U * i + axis] = 0U;
    }
    return plate;
}

ImpulseLibrary build(const Plate &plate) {
    LibraryOptions options;
    return ImpulseLibrary::create(plate.matter, plate.dof_free, options, "test", {});
}

void writeDisplacement(const ImpulseLibrary &library, ActiveMatter &matter, const std::vector<double> &field) {
    for (std::uint32_t node = 0; node < matter.nodes.size(); ++node)
        matter.nodes[node].position_world_m =
            matter.reference_positions_world_m[node] + library.nodeValue(field, node);
}

// ---- 1. the intact modal field is what an explicit lattice integrates to -----

// Total bond force on every node from the current positions, using the asset's
// own rest lengths and compliances. Nothing modal is involved.
void latticeForces(const ActiveMatter &matter, const std::vector<Vec3> &position, std::vector<Vec3> &force) {
    force.assign(matter.nodes.size(), Vec3{});
    for (std::size_t bond = 0; bond < matter.bonds.size(); ++bond) {
        if (!matter.bonds[bond].alive) continue;
        const BondRest &rest = matter.asset->bonds[bond];
        if (!(rest.compliance > 0.0)) continue;
        const Vec3 edge = position[rest.node_b] - position[rest.node_a];
        const double current = length(edge);
        if (current <= 1.0e-15) continue;
        const Vec3 direction = edge * (1.0 / current);
        const Vec3 pull = direction * ((current - rest.rest_length_m) / rest.compliance);
        force[rest.node_a] += pull;
        force[rest.node_b] -= pull;
    }
}

// One explicit-lattice run against the closed form: returns the largest
// absolute difference and the peak displacement of the closed form.
struct FieldComparison { double error{}, scale{}; };

FieldComparison compareExplicitLattice(Plate &plate, const ImpulseLibrary &library,
                                       double amplitude_m_s, double dt, double horizon) {
    std::vector<double> velocity(library.dofs(), 0.0);
    for (std::size_t dof = 0; dof < library.dofs(); ++dof) {
        const std::uint32_t full = library.dofOfFree()[dof];
        const Vec3 &p = plate.matter.reference_positions_world_m[full / 3U];
        if (full % 3U == 1U) velocity[dof] = -amplitude_m_s * std::cos(30.0 * p.x) * std::cos(30.0 * p.z);
    }
    std::vector<double> qdot(library.modes(), 0.0);
    for (std::size_t dof = 0; dof < library.dofs(); ++dof) {
        const double weight = library.dofMass()[dof] * velocity[dof];
        const double *row = library.phi().row(dof);
        for (std::size_t mode = 0; mode < library.modes(); ++mode) qdot[mode] += weight * row[mode];
    }
    std::vector<double> q(library.modes(), 0.0), closed_form;
    for (std::size_t mode = 0; mode < library.modes(); ++mode) {
        const double w = library.omega()[mode];
        q[mode] = library.isRigidMode(mode) ? qdot[mode] * horizon : qdot[mode] / w * std::sin(w * horizon);
    }
    library.displacement(q, closed_form);

    std::vector<Vec3> position(plate.matter.nodes.size()), rate(plate.matter.nodes.size(), Vec3{});
    for (std::size_t node = 0; node < position.size(); ++node)
        position[node] = plate.matter.reference_positions_world_m[node];
    for (std::size_t dof = 0; dof < library.dofs(); ++dof) {
        const std::uint32_t full = library.dofOfFree()[dof];
        double *component = &rate[full / 3U].x;
        component[full % 3U] = velocity[dof];
    }
    std::vector<Vec3> force;
    const auto steps = static_cast<unsigned>(std::llround(horizon / dt));
    latticeForces(plate.matter, position, force);
    for (unsigned step = 0; step < steps; ++step) {
        for (std::size_t node = 0; node < position.size(); ++node) {
            if (library.freeDofOf()[3U * node] == kFixedDof) continue;
            rate[node] += force[node] * (0.5 * dt / plate.matter.nodes[node].mass_kg);
            position[node] += rate[node] * dt;
        }
        latticeForces(plate.matter, position, force);
        for (std::size_t node = 0; node < position.size(); ++node) {
            if (library.freeDofOf()[3U * node] == kFixedDof) continue;
            rate[node] += force[node] * (0.5 * dt / plate.matter.nodes[node].mass_kg);
        }
    }
    FieldComparison comparison;
    for (std::size_t dof = 0; dof < library.dofs(); ++dof) {
        const std::uint32_t full = library.dofOfFree()[dof];
        const Vec3 moved = position[full / 3U] - plate.matter.reference_positions_world_m[full / 3U];
        const double explicit_value = (&moved.x)[full % 3U];
        comparison.error = std::max(comparison.error, std::abs(explicit_value - closed_form[dof]));
        comparison.scale = std::max(comparison.scale, std::abs(closed_form[dof]));
    }
    return comparison;
}

void intactFieldMatchesTheExplicitLattice() {
    Plate plate = makePlate(MaterialPreset::Glass, 5, 2, 5, 0.02, true);
    const ImpulseLibrary library = build(plate);
    require(library.stats().mechanism_modes == 0, "a two-layer clamped plate has no mechanism");
    const double horizon = 4.0e-6;

    // The step ladder: the explicit lattice agrees with the closed form to a
    // few parts per million and stops improving, because what is left is not a
    // time-step error.
    double coarse = 0.0;
    for (const double dt : {2.0e-8, 1.0e-8, 5.0e-9, 2.5e-9}) {
        const FieldComparison comparison = compareExplicitLattice(plate, library, 0.5, dt, horizon);
        std::cout << "  explicit lattice dt=" << dt << "  max |u_explicit - u_modal| = " << comparison.error
                  << "  (peak displacement " << comparison.scale << ", relative "
                  << comparison.error / comparison.scale << ")\n";
        require(comparison.error < 1.0e-5 * comparison.scale,
                "the explicit lattice and the closed form agree to parts per million");
        if (coarse > 0.0) require(comparison.error <= coarse, "refining the step does not make it worse");
        coarse = comparison.error;
    }
    // The amplitude ladder identifies what is left: the lattice's geometric
    // nonlinearity, which the linear basis does not carry. Halving the motion
    // halves the relative residual; a linear-algebra error would not move.
    double previous_relative = 0.0;
    for (const double amplitude : {0.5, 0.25, 0.125}) {
        const FieldComparison comparison = compareExplicitLattice(plate, library, amplitude, 2.5e-9, horizon);
        const double relative = comparison.error / comparison.scale;
        std::cout << "  amplitude " << amplitude << " m/s: relative residual " << relative << "\n";
        if (previous_relative > 0.0)
            require(relative < 0.75 * previous_relative,
                    "the residual falls with the amplitude: it is the lattice's geometric nonlinearity");
        previous_relative = relative;
    }
}

// ---- 2. the Woodbury correction equals a direct solve -----------------------

// u = u0 + S D (Kappa^-1 - D^T S D)^-1 D^T u0, formed exactly as the cascade
// forms it, from the library's own compliance columns.
std::vector<double> woodburyResponse(const ImpulseLibrary &library, const std::vector<double> &intact,
                                     const std::vector<std::uint32_t> &released) {
    const std::size_t k = released.size();
    const std::size_t n = library.dofs();
    std::vector<std::vector<double>> columns;
    std::vector<double> scratch;
    for (const std::uint32_t bond : released) {
        const double *column = library.complianceColumn(bond, scratch);
        columns.emplace_back(column, column + n);
    }
    std::vector<double> middle(k * k, 0.0), load(k, 0.0);
    for (std::size_t p = 0; p < k; ++p) {
        const BondGradient &gradient = library.gradients()[released[p]];
        for (std::size_t q = 0; q < k; ++q) {
            double sum = 0.0;
            for (unsigned entry = 0; entry < gradient.count; ++entry)
                sum += gradient.value[entry] * columns[q][gradient.dof[entry]];
            middle[p * k + q] = (p == q ? 1.0 / gradient.stiffness_n_m : 0.0) - sum;
        }
        load[p] = library.bondExtension(released[p], intact);
    }
    // Gaussian elimination with partial pivoting on the k x k system.
    std::vector<double> solution = load;
    for (std::size_t column = 0; column < k; ++column) {
        std::size_t pivot = column;
        for (std::size_t row = column + 1; row < k; ++row)
            if (std::abs(middle[row * k + column]) > std::abs(middle[pivot * k + column])) pivot = row;
        require(std::abs(middle[pivot * k + column]) > 0.0, "the released set leaves a solvable system");
        if (pivot != column) {
            for (std::size_t entry = 0; entry < k; ++entry)
                std::swap(middle[column * k + entry], middle[pivot * k + entry]);
            std::swap(solution[column], solution[pivot]);
        }
        for (std::size_t row = column + 1; row < k; ++row) {
            const double factor = middle[row * k + column] / middle[column * k + column];
            if (factor == 0.0) continue;
            for (std::size_t entry = column; entry < k; ++entry)
                middle[row * k + entry] -= factor * middle[column * k + entry];
            solution[row] -= factor * solution[column];
        }
    }
    for (std::size_t row = k; row-- > 0;) {
        for (std::size_t entry = row + 1; entry < k; ++entry)
            solution[row] -= middle[row * k + entry] * solution[entry];
        solution[row] /= middle[row * k + row];
    }
    std::vector<double> field = intact;
    for (std::size_t p = 0; p < k; ++p)
        for (std::size_t dof = 0; dof < n; ++dof) field[dof] += solution[p] * columns[p][dof];
    return field;
}

void woodburyEqualsADirectSolve() {
    Plate plate = makePlate(MaterialPreset::Glass, 5, 2, 5, 0.02, true);
    const ImpulseLibrary library = build(plate);
    require(library.stats().rigid_modes == 0, "the clamped plate's stiffness is positive definite");

    std::mt19937 generator(12345);
    std::uniform_real_distribution<double> spread(-1.0, 1.0);
    std::vector<double> force(library.dofs(), 0.0);
    for (double &entry : force) entry = spread(generator);
    std::vector<double> intact;
    library.staticResponse(force, intact);

    // Bonds that join two free cells, spread through the plate.
    std::vector<std::uint32_t> free_bonds;
    for (std::uint32_t bond = 0; bond < plate.matter.bonds.size(); ++bond) {
        const BondGradient &gradient = library.gradients()[bond];
        if (gradient.count == 6U && gradient.stiffness_n_m > 0.0) free_bonds.push_back(bond);
    }
    require(free_bonds.size() >= 8, "the test plate has interior bonds to release");

    for (const std::size_t count : {std::size_t{1}, std::size_t{2}, std::size_t{5}}) {
        std::vector<std::uint32_t> released;
        for (std::size_t index = 0; index < count; ++index)
            released.push_back(free_bonds[index * (free_bonds.size() / count == 0 ? 1 : free_bonds.size() / count)]);
        std::sort(released.begin(), released.end());
        released.erase(std::unique(released.begin(), released.end()), released.end());

        const std::vector<double> woodbury = woodburyResponse(library, intact, released);

        Plate reduced = makePlate(MaterialPreset::Glass, 5, 2, 5, 0.02, true);
        for (const std::uint32_t bond : released) reduced.matter.bonds[bond].alive = false;
        const ImpulseLibrary direct_library = build(reduced);
        require(direct_library.stats().rigid_modes == 0,
                "releasing these bonds leaves the reduced stiffness positive definite");
        std::vector<double> direct;
        direct_library.staticResponse(force, direct);

        double error = 0.0, scale = 0.0;
        for (std::size_t dof = 0; dof < library.dofs(); ++dof) {
            error = std::max(error, std::abs(woodbury[dof] - direct[dof]));
            scale = std::max(scale, std::abs(direct[dof]));
        }
        std::cout << "  released " << released.size() << " bonds: max |u_woodbury - u_direct| = " << error
                  << " on a field of " << scale << " (relative " << error / scale << ")\n";
        require(error <= 1.0e-9 * scale, "the Woodbury field equals the direct solve of the reduced lattice");
    }
}

// ---- 3. the screen's bound is never violated by sampling ---------------------

void screenBoundIsNeverViolated(unsigned nx, unsigned ny, unsigned nz, bool clamp_ring,
                                double impulse_n_s, const char *label) {
    Plate plate = makePlate(MaterialPreset::Glass, nx, ny, nz, 0.02, clamp_ring);
    if (!clamp_ring) {
        // Ledge support: the outermost cells of the bottom layer are held in y.
        for (std::uint32_t node = 0; node < plate.asset.nodes.size(); ++node) {
            const auto grid = plate.asset.nodes[node].grid;
            if (grid.y == 0 && (grid.x == 0 || grid.x + 1 == static_cast<int>(nx)))
                plate.dof_free[3U * node + 1U] = 0U;
        }
    }
    const ImpulseLibrary library = build(plate);

    // One impulse straight down at the cell nearest the centre of the top face.
    std::uint32_t struck = 0;
    double best = 1.0e30;
    for (std::uint32_t node = 0; node < plate.asset.nodes.size(); ++node) {
        const auto grid = plate.asset.nodes[node].grid;
        if (grid.y + 1 != static_cast<int>(ny)) continue;
        const Vec3 &p = plate.matter.reference_positions_world_m[node];
        const double radial = p.x * p.x + p.z * p.z;
        if (radial < best) { best = radial; struck = node; }
    }
    std::vector<double> q(library.modes(), 0.0), qdot(library.modes(), 0.0);
    library.addNodeImpulse(qdot, struck, {0.0, -impulse_n_s, 0.0});

    const double horizon = 3.0e-4;
    std::vector<double> amplitude_bound(library.modes(), 0.0);
    for (std::size_t mode = 0; mode < library.modes(); ++mode)
        amplitude_bound[mode] = library.isRigidMode(mode) ? std::abs(qdot[mode]) * horizon
                                                          : std::abs(qdot[mode]) / library.omega()[mode];
    StrainBounds bounds;
    boundCriterionStrain(plate.matter, library, amplitude_bound, bounds);

    const double dt = 2.0e-7;
    const auto steps = static_cast<unsigned>(std::llround(horizon / dt));
    std::vector<double> field;
    resetBondStrainPeaks(plate.matter);
    for (unsigned step = 1; step <= steps; ++step) {
        for (std::size_t mode = 0; mode < library.modes(); ++mode) {
            const double x = q[mode], v = qdot[mode];
            if (library.isRigidMode(mode)) { q[mode] = x + v * dt; continue; }
            const double w = library.omega()[mode];
            q[mode] = x * std::cos(w * dt) + v / w * std::sin(w * dt);
            qdot[mode] = -x * w * std::sin(w * dt) + v * std::cos(w * dt);
        }
        library.displacement(q, field);
        writeDisplacement(library, plate.matter, field);
        accumulateBondStrainPeaks(plate.matter);
    }
    double worst = 0.0;
    std::size_t reached = 0, offender = 0;
    for (std::size_t bond = 0; bond < plate.matter.bonds.size(); ++bond) {
        if (!plate.matter.bonds[bond].alive) continue;
        const auto &state = plate.matter.bonds[bond];
        const double peak = std::max({state.peak_tensile_stretch, state.peak_compressive_strain,
                                      state.peak_shear_strain});
        const double bound = bounds.criterion[bond];
        if (bound > 0.0) {
            if (peak / bound > worst) { worst = peak / bound; offender = bond; }
            if (peak > 0.1 * bound) ++reached;
        }
    }
    {
        const auto &state = plate.matter.bonds[offender];
        const BondRest &rest = plate.matter.asset->bonds[offender];
        std::cout << "    worst bond " << offender << " peaks t=" << state.peak_tensile_stretch
                  << " c=" << state.peak_compressive_strain << " s=" << state.peak_shear_strain
                  << " bound=" << bounds.criterion[offender] << " axial=" << bounds.axial[offender]
                  << " relative=" << bounds.relative[offender]
                  << " nodeA=" << bounds.node_bound[rest.node_a]
                  << " nodeB=" << bounds.node_bound[rest.node_b] << "\n";
    }
    require(worst <= 1.0 + 1.0e-9,
            std::string("the screen's bound holds for every bond (") + label + ")");
    std::cout << "  " << label << ": " << steps << " samples, tightest bond reached "
              << worst << " of its bound, " << reached << " bonds within a decade of it\n";
    require(worst > 0.0, "the sweep strains something");
}

} // namespace

int main() {
    try {
        intactFieldMatchesTheExplicitLattice();
        std::cout << "[PASS] the intact modal field is what an explicit lattice converges to\n";
        woodburyEqualsADirectSolve();
        std::cout << "[PASS] the Woodbury-corrected static field equals a direct solve with the bonds removed\n";
        screenBoundIsNeverViolated(5, 2, 5, true, 2.0e-3, "clamped 5x2x5, full spectrum");
        screenBoundIsNeverViolated(7, 1, 5, false, 5.0e-4, "ledges 7x1x5, out-of-plane mechanism");
        std::cout << "[PASS] the screen's bound is never violated by sampling\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
