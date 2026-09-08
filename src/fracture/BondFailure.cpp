#include "fracture/BondFailure.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {

// The full nonlocal Green-Lagrange strain at a node. A scalar principal value
// is not enough: a bond must be judged by the strain resolved along its own
// axis, otherwise a bond perpendicular to the loading direction fails on strain
// it does not carry, and every bond at a highly strained node fails at once.
struct NodeStrainState {
    Mat3 green_lagrange{};
    bool valid{};
    // Eigen-directions the neighbourhood spans: 3 for solid matter, 2 for a
    // sheet one cell thick, fewer where fracture has stripped the node.
    int rank{};
};

// Strain resolved onto one bond direction: the normal component along the bond
// and the transverse (shear) component on the plane whose normal is the bond.
struct ResolvedBondStrain {
    double normal{};
    double shear{};
};

[[nodiscard]] ResolvedBondStrain resolveAlongBond(const Mat3 &strain, const Vec3 &direction) {
    const Vec3 traction = strain * direction;
    const double normal = dot(direction, traction);
    return {normal, length(traction - normal * direction)};
}

void addScaledOuterProduct(
    Mat3 &matrix,
    const Vec3 &left,
    const Vec3 &right,
    double scale) {
    const std::array<double, 3> a{left.x, left.y, left.z};
    const std::array<double, 3> b{right.x, right.y, right.z};
    for (std::size_t row = 0; row < 3U; ++row) {
        for (std::size_t column = 0; column < 3U; ++column) {
            matrix.m[row][column] += scale * a[row] * b[column];
        }
    }
}

[[nodiscard]] Mat3 transpose(const Mat3 &matrix) {
    Mat3 result{};
    for (std::size_t row = 0; row < 3U; ++row) {
        for (std::size_t column = 0; column < 3U; ++column) {
            result.m[row][column] = matrix.m[column][row];
        }
    }
    return result;
}

[[nodiscard]] Mat3 multiply(const Mat3 &left, const Mat3 &right) {
    Mat3 result{};
    for (std::size_t row = 0; row < 3U; ++row) {
        for (std::size_t column = 0; column < 3U; ++column) {
            for (std::size_t index = 0; index < 3U; ++index) {
                result.m[row][column] +=
                    left.m[row][index] * right.m[index][column];
            }
        }
    }
    return result;
}

// Eigendecomposition of a symmetric 3x3 by cyclic Jacobi rotations, and the
// Moore-Penrose pseudo-inverse built from it, truncating every eigen-direction
// below a floor relative to the largest eigenvalue.
//
// A direction the neighbourhood does not sample carries no information about
// the deformation, and inverting it amplifies rounding without bound. That is
// what an absolute determinant threshold used to allow: a plate two cells thick
// reported a tensile strain of 2.3 and a compressive strain of exactly 0.5,
// which is a deformation gradient collapsed to zero, and a plate one cell thick
// was rejected outright so the criterion silently became a local stretch test.
// Truncating instead leaves the deformation gradient as the identity along the
// unmeasured direction, which is the plane-stress statement for a thin sheet
// and the only claim the neighbourhood supports.
//
// Mirrored in fastlattice/LatticePhysics.hpp (symmetricEigen3,
// symmetricPseudoInverse3); the two must stay identical.
void symmetricEigen3(const Mat3 &matrix, double eigenvalues[3], Mat3 &vectors) {
    double a[3][3];
    for (std::size_t row = 0; row < 3U; ++row)
        for (std::size_t column = 0; column < 3U; ++column)
            a[row][column] = matrix.m[row][column];
    for (std::size_t row = 0; row < 3U; ++row)
        for (std::size_t column = 0; column < 3U; ++column)
            vectors.m[row][column] = row == column ? 1.0 : 0.0;
    for (int sweep = 0; sweep < 12; ++sweep) {
        const double off = std::abs(a[0][1]) + std::abs(a[0][2]) + std::abs(a[1][2]);
        if (!(off > 0.0)) {
            break;
        }
        for (int p = 0; p < 2; ++p) {
            for (int q = p + 1; q < 3; ++q) {
                const double apq = a[p][q];
                if (!(std::abs(apq) > 0.0)) {
                    continue;
                }
                const double theta = (a[q][q] - a[p][p]) / (2.0 * apq);
                const double sign = theta >= 0.0 ? 1.0 : -1.0;
                const double t = sign / (std::abs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0);
                const double sn = t * c;
                for (int k = 0; k < 3; ++k) {
                    const double akp = a[k][p], akq = a[k][q];
                    a[k][p] = c * akp - sn * akq;
                    a[k][q] = sn * akp + c * akq;
                }
                for (int k = 0; k < 3; ++k) {
                    const double apk = a[p][k], aqk = a[q][k];
                    a[p][k] = c * apk - sn * aqk;
                    a[q][k] = sn * apk + c * aqk;
                }
                for (int k = 0; k < 3; ++k) {
                    const double vkp = vectors.m[k][p], vkq = vectors.m[k][q];
                    vectors.m[k][p] = c * vkp - sn * vkq;
                    vectors.m[k][q] = sn * vkp + c * vkq;
                }
            }
        }
    }
    eigenvalues[0] = a[0][0];
    eigenvalues[1] = a[1][1];
    eigenvalues[2] = a[2][2];
}

// Returns the number of eigen-directions kept: 3 for a solid neighbourhood, 2
// for a coplanar one (a sheet one cell thick), fewer where fracture has
// stripped a node of neighbours.
[[nodiscard]] int symmetricPseudoInverse(
    const Mat3 &matrix, Mat3 &result, Vec3 &unmeasured) {
    double eigenvalues[3];
    Mat3 vectors{};
    symmetricEigen3(matrix, eigenvalues, vectors);
    double largest = 0.0;
    for (const double value : eigenvalues) {
        largest = std::max(largest, std::abs(value));
    }
    const double floor_value = 1.0e-9 * largest;
    result = Mat3{};
    unmeasured = Vec3{};
    int rank = 0;
    int dropped = -1;
    for (std::size_t column = 0; column < 3U; ++column) {
        if (!(eigenvalues[column] > floor_value)) {
            dropped = static_cast<int>(column);
            continue;
        }
        ++rank;
        const double inverse = 1.0 / eigenvalues[column];
        for (std::size_t row = 0; row < 3U; ++row) {
            for (std::size_t col = 0; col < 3U; ++col) {
                result.m[row][col] +=
                    inverse * vectors.m[row][column] * vectors.m[col][column];
            }
        }
    }
    // Exactly one direction dropped -- a coplanar neighbourhood -- is the case
    // the strain can still be stated on: report its normal so the strain can be
    // projected into the plane. Two or more dropped leaves too little to say.
    if (rank == 2 && dropped >= 0) {
        const std::size_t column = static_cast<std::size_t>(dropped);
        unmeasured = Vec3{vectors.m[0][column], vectors.m[1][column], vectors.m[2][column]};
    }
    return rank;
}

[[nodiscard]] std::vector<NodeStrainState> calculateNodeStrains(
    const ActiveMatter &matter) {
    std::vector<NodeStrainState> strains(matter.nodes.size());
    if (matter.asset == nullptr ||
        matter.reference_positions_world_m.size() != matter.nodes.size()) {
        return strains;
    }

    for (std::size_t node_index = 0;
         node_index < matter.nodes.size();
         ++node_index) {
        Mat3 current_rest_covariance{};
        Mat3 rest_covariance{};
        std::size_t live_neighbors = 0U;
        const std::uint32_t begin =
            matter.asset->adjacency_offsets[node_index];
        const std::uint32_t end =
            matter.asset->adjacency_offsets[node_index + 1U];
        for (std::uint32_t adjacency = begin; adjacency < end; ++adjacency) {
            const std::uint32_t bond_index =
                matter.asset->adjacent_bond_indices[adjacency];
            if (!matter.bonds[bond_index].alive) {
                continue;
            }
            const BondRest &bond = matter.asset->bonds[bond_index];
            const std::uint32_t other =
                bond.node_a == node_index ? bond.node_b : bond.node_a;
            const Vec3 rest_edge =
                matter.reference_positions_world_m[other] -
                matter.reference_positions_world_m[node_index];
            const Vec3 current_edge =
                matter.nodes[other].position_world_m -
                matter.nodes[node_index].position_world_m;
            const double rest_length_squared = lengthSquared(rest_edge);
            if (rest_length_squared <= 1.0e-18) {
                continue;
            }
            const double weight = 1.0 / rest_length_squared;
            // The displacement difference, not the current edge: at rest this
            // is exactly zero, so the deformation gradient below is the
            // identity whatever the pseudo-inverse drops, and the form carries
            // no cancellation.
            addScaledOuterProduct(
                current_rest_covariance,
                current_edge - rest_edge,
                rest_edge,
                weight);
            addScaledOuterProduct(
                rest_covariance,
                rest_edge,
                rest_edge,
                weight);
            ++live_neighbors;
        }
        if (live_neighbors < 1U) {
            continue;
        }

        Mat3 inverse_rest{};
        Vec3 unmeasured{};
        const int rank =
            symmetricPseudoInverse(rest_covariance, inverse_rest, unmeasured);
        if (rank < 2) {
            continue;
        }
        // G = F - I = dA R+, E = (G + G^T + G^T G) / 2.
        const Mat3 gradient_minus_identity =
            multiply(current_rest_covariance, inverse_rest);
        const Mat3 quadratic = multiply(
            transpose(gradient_minus_identity),
            gradient_minus_identity);
        Mat3 green_lagrange_strain{};
        for (std::size_t row = 0; row < 3U; ++row) {
            for (std::size_t column = 0; column < 3U; ++column) {
                green_lagrange_strain.m[row][column] =
                    0.5 * (gradient_minus_identity.m[row][column] +
                           gradient_minus_identity.m[column][row] +
                           quadratic.m[row][column]);
            }
        }

        // A coplanar neighbourhood measures the deformation of its own plane and
        // nothing else. Leaving the unmeasured direction at rest is not a
        // neutral choice: it is not invariant under rigid rotation, so a sheet
        // that merely flexes reads as shear. Projecting removes exactly those
        // cross terms, and every live bond at such a node lies in the plane, so
        // nothing the criterion reads is lost. Mirrored in
        // fastlattice/LatticePhysics.hpp nodeStrain.
        if (lengthSquared(unmeasured) > 0.0) {
            const Vec3 traction{
                green_lagrange_strain.m[0][0] * unmeasured.x +
                    green_lagrange_strain.m[0][1] * unmeasured.y +
                    green_lagrange_strain.m[0][2] * unmeasured.z,
                green_lagrange_strain.m[1][0] * unmeasured.x +
                    green_lagrange_strain.m[1][1] * unmeasured.y +
                    green_lagrange_strain.m[1][2] * unmeasured.z,
                green_lagrange_strain.m[2][0] * unmeasured.x +
                    green_lagrange_strain.m[2][1] * unmeasured.y +
                    green_lagrange_strain.m[2][2] * unmeasured.z};
            const double normal = dot(traction, unmeasured);
            const double n[3] = {unmeasured.x, unmeasured.y, unmeasured.z};
            const double a[3] = {traction.x, traction.y, traction.z};
            for (std::size_t row = 0; row < 3U; ++row) {
                for (std::size_t column = 0; column < 3U; ++column) {
                    green_lagrange_strain.m[row][column] +=
                        -n[row] * a[column] - a[row] * n[column] +
                        normal * n[row] * n[column];
                }
            }
        }

        strains[node_index].green_lagrange = green_lagrange_strain;
        strains[node_index].valid = true;
        strains[node_index].rank = rank;
    }
    return strains;
}

[[nodiscard]] double storedBondEnergy(const ActiveMatter &matter, std::size_t bond_index) {
    const BondRest &rest = matter.asset->bonds[bond_index];
    if (rest.compliance <= 0.0) return 0.0;
    const double extension = length(matter.nodes[rest.node_b].position_world_m -
        matter.nodes[rest.node_a].position_world_m) - rest.rest_length_m;
    return 0.5 * extension * extension / rest.compliance;
}

void requireMatchingAsset(const ActiveMatter &matter) {
    if (matter.asset == nullptr || matter.bonds.size() != matter.asset->bonds.size())
        throw std::invalid_argument("bond failure requires matching lattice state");
}

} // namespace

void resetBondStrainPeaks(ActiveMatter &matter) {
    for (ActiveBondState &bond : matter.bonds) {
        bond.peak_tensile_stretch = 0.0;
        bond.peak_compressive_strain = 0.0;
        bond.peak_shear_strain = 0.0;
    }
}

void accumulateBondStrainPeaks(ActiveMatter &matter) {
    requireMatchingAsset(matter);
    const auto strains = calculateNodeStrains(matter);
    const bool has_reference =
        matter.reference_positions_world_m.size() == matter.nodes.size();
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
        auto &state = matter.bonds[i];
        if (!state.alive) continue;
        const auto &rest = matter.asset->bonds[i];
        const double stretch = length(matter.nodes[rest.node_b].position_world_m -
            matter.nodes[rest.node_a].position_world_m) / rest.rest_length_m - 1.0;
        double tensile = stretch;
        double compressive = -stretch;
        double shear = 0.0;
        if (has_reference) {
            const Vec3 rest_edge = matter.reference_positions_world_m[rest.node_b] -
                                   matter.reference_positions_world_m[rest.node_a];
            const double rest_length = length(rest_edge);
            if (rest_length > 1.0e-9) {
                const Vec3 direction = rest_edge * (1.0 / rest_length);
                for (const std::uint32_t node : {rest.node_a, rest.node_b}) {
                    if (!strains[node].valid) continue;
                    const auto resolved = resolveAlongBond(strains[node].green_lagrange, direction);
                    tensile = std::max(tensile, resolved.normal);
                    compressive = std::max(compressive, -resolved.normal);
                    shear = std::max(shear, resolved.shear);
                }
            }
        }
        state.peak_tensile_stretch = std::max(state.peak_tensile_stretch, tensile);
        state.peak_compressive_strain = std::max(state.peak_compressive_strain, compressive);
        state.peak_shear_strain = std::max(state.peak_shear_strain, shear);
    }
}

double bondDamageProgress(
    double value,
    double start,
    double end) {
    if (!std::isfinite(start) || value <= start) {
        return 0.0;
    }
    if (!std::isfinite(end) || end <= start) {
        return value > start ? 1.0 : 0.0;
    }
    return std::clamp((value - start) / (end - start), 0.0, 1.0);
}

BondDamageEvaluation evaluateBondDamage(
    const ActiveBondState &state, const BondRest &rest) {
    const double tensile_damage = bondDamageProgress(
        state.peak_tensile_stretch,
        rest.damage_start_stretch,
        rest.damage_end_stretch);
    const double compressive_damage = bondDamageProgress(
        state.peak_compressive_strain,
        rest.compression_damage_start_strain,
        rest.compression_damage_end_strain);
    const double shear_damage = bondDamageProgress(
        state.peak_shear_strain,
        rest.shear_damage_start_strain,
        rest.shear_damage_end_strain);

    BondDamageEvaluation evaluation{tensile_damage, BondFailureMode::Tension};
    if (compressive_damage > evaluation.damage) {
        evaluation.damage = compressive_damage;
        evaluation.mode = BondFailureMode::Compression;
    }
    if (shear_damage > evaluation.damage) {
        evaluation.damage = shear_damage;
        evaluation.mode = BondFailureMode::Shear;
    }
    return evaluation;
}

BondFailureSummary applyBondFailure(
    ActiveMatter &matter, std::vector<std::uint32_t> *removed_bond_indices) {
    requireMatchingAsset(matter);
    BondFailureSummary summary;
    for (std::size_t bond_index = 0; bond_index < matter.bonds.size(); ++bond_index) {
        ActiveBondState &state = matter.bonds[bond_index];
        if (!state.alive) {
            continue;
        }
        const BondRest &rest = matter.asset->bonds[bond_index];
        summary.maximum_tensile_stretch = std::max(
            summary.maximum_tensile_stretch, state.peak_tensile_stretch);
        summary.maximum_compressive_strain = std::max(
            summary.maximum_compressive_strain, state.peak_compressive_strain);
        summary.maximum_shear_strain = std::max(
            summary.maximum_shear_strain, state.peak_shear_strain);

        const auto evaluation = evaluateBondDamage(state, rest);
        if (evaluation.damage > state.damage) {
            state.damage = evaluation.damage;
            state.failure_mode = evaluation.mode;
        }
        if (state.damage >= 1.0) {
            // This is removed stored energy, not a calibrated crack-work law.
            // Name it explicitly so damage cannot silently erase the ledger.
            summary.removed_elastic_energy_j += storedBondEnergy(matter, bond_index);
            state.alive = false;
            matter.connectivity_dirty = true;
            ++summary.newly_broken;
            if (removed_bond_indices)
                removed_bond_indices->push_back(static_cast<std::uint32_t>(bond_index));
        }
    }
    return summary;
}

BondFailureSummary removeBondsAtCurrentState(
    ActiveMatter &matter,
    const std::vector<std::uint32_t> &bond_indices,
    const std::vector<BondFailureMode> &modes) {
    requireMatchingAsset(matter);
    if (bond_indices.size() != modes.size())
        throw std::invalid_argument("bond removal needs one failure mode per bond");
    BondFailureSummary summary;
    for (std::size_t entry = 0; entry < bond_indices.size(); ++entry) {
        const std::uint32_t bond_index = bond_indices[entry];
        if (bond_index >= matter.bonds.size())
            throw std::invalid_argument("bond removal index outside the lattice");
        ActiveBondState &state = matter.bonds[bond_index];
        if (!state.alive) continue;
        summary.removed_elastic_energy_j += storedBondEnergy(matter, bond_index);
        state.damage = 1.0;
        state.failure_mode = modes[entry];
        state.alive = false;
        matter.connectivity_dirty = true;
        ++summary.newly_broken;
    }
    return summary;
}

std::size_t countBrokenBonds(const ActiveMatter &matter) {
    return static_cast<std::size_t>(std::count_if(
        matter.bonds.begin(), matter.bonds.end(), [](const ActiveBondState &bond) {
            return !bond.alive;
        }));
}

BondFailureModeCounts countBondFailureModes(const ActiveMatter &matter) {
    BondFailureModeCounts counts;
    for (const ActiveBondState &bond : matter.bonds) {
        if (bond.alive) {
            continue;
        }
        switch (bond.failure_mode) {
        case BondFailureMode::Tension:
            ++counts.tensile;
            break;
        case BondFailureMode::Compression:
            ++counts.compressive;
            break;
        case BondFailureMode::Shear:
            ++counts.shear;
            break;
        case BondFailureMode::None:
            break;
        }
    }
    return counts;
}

} // namespace banjo
