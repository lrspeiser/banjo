#include "fracture/BrittleBondSolver.hpp"
#include "physics/MechanicalAccounting.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <vector>

namespace banjo {
namespace {

struct NodeStrainState {
    double tensile{};
    double compressive{};
    double shear{};
};

[[nodiscard]] std::size_t countBrokenBonds(const ActiveMatter &matter) {
    return static_cast<std::size_t>(std::count_if(
        matter.bonds.begin(), matter.bonds.end(), [](const ActiveBondState &bond) {
            return !bond.alive;
        }));
}

void applySupportContact(
    ActiveNodeState &node, const BrittleSolverSettings &settings) {
    if (!settings.support_enabled) return;
    const auto &plane = settings.support_plane;
    if (!insideSupportFootprint(plane, node.position_world_m,
            settings.support_half_tangent_m, settings.support_half_bitangent_m)) return;
    const double distance = signedDistanceToPlane(plane, node.position_world_m);
    if (distance > 1.0e-8) return;
    const double normal_speed = dot(node.velocity_m_s, plane.normal_world);
    if (normal_speed < 0.0) {
        const double restitution = -normal_speed > 0.5
            ? std::clamp(settings.surface_restitution, 0.0, 1.0) : 0.0;
        const double normal_delta = -(1.0 + restitution) * normal_speed;
        node.velocity_m_s += normal_delta * plane.normal_world;
        const Vec3 tangent = projectVectorOntoPlane(plane, node.velocity_m_s);
        const double speed = length(tangent);
        if (speed > 1.0e-12) {
            const double friction_delta = speed <= settings.surface_static_friction * normal_delta
                ? speed : std::min(speed, settings.surface_dynamic_friction * normal_delta);
            node.velocity_m_s -= (friction_delta / speed) * tangent;
        }
    }
    // Split position correction, after reconstructing velocities. A penetrating
    // point is not given artificial rebound energy by moving it out of the floor.
    node.position_world_m -= distance * plane.normal_world;
}

void accumulateContactStats(SphereMaterialContactStats &out,
                            const SphereMaterialContactStats &in) {
    out.impulse_contacts += in.impulse_contacts;
    out.impulse_to_material_n_s += in.impulse_to_material_n_s;
    out.angular_impulse_to_sphere_kg_m2_s += in.angular_impulse_to_sphere_kg_m2_s;
    out.dissipated_kinetic_energy_j += in.dissipated_kinetic_energy_j;
    out.maximum_penetration_m = std::max(out.maximum_penetration_m, in.maximum_penetration_m);
    out.maximum_position_correction_m = std::max(out.maximum_position_correction_m, in.maximum_position_correction_m);
    out.position_correction_angular_momentum_delta_kg_m2_s +=
        in.position_correction_angular_momentum_delta_kg_m2_s;
}

// Radial pair damping is translation/rotation invariant and exchanges equal,
// opposite central impulses. It must not damp whole-object motion in a vacuum.
double dampInternalBonds(ActiveMatter &matter, double dt) {
    const double fraction = 1.0 - std::exp(-matter.material.bond_damping * dt);
    double loss = 0.0;
    if (fraction <= 0.0) return loss;
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) {
        if (!matter.bonds[i].alive) continue;
        const auto &bond = matter.asset->bonds[i];
        auto &a = matter.nodes[bond.node_a];
        auto &b = matter.nodes[bond.node_b];
        if (a.mass_kg <= 0.0 || b.mass_kg <= 0.0) continue;
        const Vec3 normal = normalized(b.position_world_m - a.position_world_m);
        const double relative_speed = dot(b.velocity_m_s - a.velocity_m_s, normal);
        const double inverse_mass = 1.0 / a.mass_kg + 1.0 / b.mass_kg;
        const double impulse = -fraction * relative_speed / inverse_mass;
        a.velocity_m_s -= (impulse / a.mass_kg) * normal;
        b.velocity_m_s += (impulse / b.mass_kg) * normal;
        loss += -(impulse * relative_speed + 0.5 * inverse_mass * impulse * impulse);
    }
    return loss;
}

void solveBond(
    ActiveMatter &matter,
    std::size_t bond_index,
    double substep_dt_s) {
    ActiveBondState &state = matter.bonds[bond_index];
    if (!state.alive) {
        return;
    }

    const BondRest &rest = matter.asset->bonds[bond_index];
    ActiveNodeState &a = matter.nodes[rest.node_a];
    ActiveNodeState &b = matter.nodes[rest.node_b];

    const Vec3 delta = b.position_world_m - a.position_world_m;
    const double current_length = length(delta);
    if (current_length <= 1.0e-12) {
        return;
    }

    const double constraint = current_length - rest.rest_length_m;
    const double stretch = constraint / rest.rest_length_m;
    state.peak_tensile_stretch =
        std::max(state.peak_tensile_stretch, stretch);
    state.peak_compressive_strain =
        std::max(state.peak_compressive_strain, -stretch);

    const Vec3 direction = delta / current_length;
    const double inverse_mass_a = a.mass_kg > 0.0 ? 1.0 / a.mass_kg : 0.0;
    const double inverse_mass_b = b.mass_kg > 0.0 ? 1.0 / b.mass_kg : 0.0;
    const double alpha = rest.compliance / (substep_dt_s * substep_dt_s);
    const double delta_lambda =
        (-constraint - alpha * state.accumulated_lambda) /
        (inverse_mass_a + inverse_mass_b + alpha);

    state.accumulated_lambda += delta_lambda;
    a.position_world_m -= inverse_mass_a * delta_lambda * direction;
    b.position_world_m += inverse_mass_b * delta_lambda * direction;
}

[[nodiscard]] Vec3 centerOfMass(const ActiveMatter &matter) {
    double total_mass = 0.0;
    Vec3 weighted{};
    for (const ActiveNodeState &node : matter.nodes) {
        total_mass += node.mass_kg;
        weighted += node.mass_kg * node.position_world_m;
    }
    return total_mass > 0.0 ? weighted / total_mass : Vec3{};
}

[[nodiscard]] Mat3 pointMassInertia(
    const ActiveMatter &matter,
    const Vec3 &center_of_mass) {
    Mat3 inertia{};
    for (const ActiveNodeState &node : matter.nodes) {
        const Vec3 r = node.position_world_m - center_of_mass;
        inertia.m[0][0] += node.mass_kg * (r.y * r.y + r.z * r.z);
        inertia.m[1][1] += node.mass_kg * (r.x * r.x + r.z * r.z);
        inertia.m[2][2] += node.mass_kg * (r.x * r.x + r.y * r.y);
        inertia.m[0][1] -= node.mass_kg * r.x * r.y;
        inertia.m[1][0] = inertia.m[0][1];
        inertia.m[0][2] -= node.mass_kg * r.x * r.z;
        inertia.m[2][0] = inertia.m[0][2];
        inertia.m[1][2] -= node.mass_kg * r.y * r.z;
        inertia.m[2][1] = inertia.m[1][2];
    }
    return inertia;
}

void removeRigidMomentumComponents(
    const ActiveMatter &matter,
    std::vector<Vec3> &delta_velocity) {
    if (matter.nodes.empty() || delta_velocity.size() != matter.nodes.size()) {
        return;
    }

    double total_mass = 0.0;
    Vec3 linear_momentum{};
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        total_mass += matter.nodes[index].mass_kg;
        linear_momentum += matter.nodes[index].mass_kg * delta_velocity[index];
    }
    if (total_mass <= 0.0) {
        return;
    }

    const Vec3 mean_delta = linear_momentum / total_mass;
    for (Vec3 &velocity : delta_velocity) {
        velocity -= mean_delta;
    }

    const Vec3 center = centerOfMass(matter);
    Vec3 angular_momentum{};
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        const Vec3 r = matter.nodes[index].position_world_m - center;
        angular_momentum +=
            cross(r, matter.nodes[index].mass_kg * delta_velocity[index]);
    }

    const Mat3 inertia = pointMassInertia(matter, center);
    if (const auto inverse = inertia.inverse(1.0e-18)) {
        const Vec3 angular_velocity = *inverse * angular_momentum;
        for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
            const Vec3 r = matter.nodes[index].position_world_m - center;
            delta_velocity[index] -= cross(angular_velocity, r);
        }
    }

    Vec3 residual_momentum{};
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        residual_momentum +=
            matter.nodes[index].mass_kg * delta_velocity[index];
    }
    const Vec3 residual_mean = residual_momentum / total_mass;
    for (Vec3 &velocity : delta_velocity) {
        velocity -= residual_mean;
    }
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

[[nodiscard]] std::array<double, 3> symmetricEigenvalues(Mat3 matrix) {
    for (unsigned iteration = 0; iteration < 12U; ++iteration) {
        std::size_t p = 0U;
        std::size_t q = 1U;
        double maximum = std::abs(matrix.m[p][q]);
        for (const auto pair :
             std::array<std::array<std::size_t, 2>, 3>{
                 std::array<std::size_t, 2>{0U, 1U},
                 std::array<std::size_t, 2>{0U, 2U},
                 std::array<std::size_t, 2>{1U, 2U},
             }) {
            const double magnitude =
                std::abs(matrix.m[pair[0]][pair[1]]);
            if (magnitude > maximum) {
                maximum = magnitude;
                p = pair[0];
                q = pair[1];
            }
        }
        if (maximum <= 1.0e-12) {
            break;
        }

        const double app = matrix.m[p][p];
        const double aqq = matrix.m[q][q];
        const double apq = matrix.m[p][q];
        const double angle = 0.5 * std::atan2(2.0 * apq, aqq - app);
        const double cosine = std::cos(angle);
        const double sine = std::sin(angle);

        for (std::size_t index = 0; index < 3U; ++index) {
            if (index == p || index == q) {
                continue;
            }
            const double aip = matrix.m[index][p];
            const double aiq = matrix.m[index][q];
            matrix.m[index][p] = cosine * aip - sine * aiq;
            matrix.m[p][index] = matrix.m[index][p];
            matrix.m[index][q] = sine * aip + cosine * aiq;
            matrix.m[q][index] = matrix.m[index][q];
        }

        matrix.m[p][p] = cosine * cosine * app -
                         2.0 * sine * cosine * apq +
                         sine * sine * aqq;
        matrix.m[q][q] = sine * sine * app +
                         2.0 * sine * cosine * apq +
                         cosine * cosine * aqq;
        matrix.m[p][q] = 0.0;
        matrix.m[q][p] = 0.0;
    }

    std::array<double, 3> values{
        matrix.m[0][0],
        matrix.m[1][1],
        matrix.m[2][2],
    };
    std::sort(values.begin(), values.end());
    return values;
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
            addScaledOuterProduct(
                current_rest_covariance,
                current_edge,
                rest_edge,
                weight);
            addScaledOuterProduct(
                rest_covariance,
                rest_edge,
                rest_edge,
                weight);
            ++live_neighbors;
        }
        if (live_neighbors < 3U) {
            continue;
        }

        const auto inverse_rest = rest_covariance.inverse(1.0e-16);
        if (!inverse_rest) {
            continue;
        }
        const Mat3 deformation_gradient =
            multiply(current_rest_covariance, *inverse_rest);
        const Mat3 right_cauchy_green = multiply(
            transpose(deformation_gradient),
            deformation_gradient);
        Mat3 green_lagrange_strain{};
        for (std::size_t row = 0; row < 3U; ++row) {
            for (std::size_t column = 0; column < 3U; ++column) {
                const double identity = row == column ? 1.0 : 0.0;
                green_lagrange_strain.m[row][column] =
                    0.5 * (right_cauchy_green.m[row][column] - identity);
            }
        }

        const std::array<double, 3> principal =
            symmetricEigenvalues(green_lagrange_strain);
        strains[node_index].tensile = std::max(0.0, principal[2]);
        strains[node_index].compressive = std::max(0.0, -principal[0]);
        strains[node_index].shear =
            std::max(0.0, 0.5 * (principal[2] - principal[0]));
    }
    return strains;
}

[[nodiscard]] double damageProgress(
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

void accumulateFailureCounts(
    const ActiveMatter &matter,
    MaterialStepStats &stats) {
    for (const ActiveBondState &bond : matter.bonds) {
        if (bond.alive) {
            continue;
        }
        switch (bond.failure_mode) {
        case BondFailureMode::Tension:
            ++stats.tensile_failures;
            break;
        case BondFailureMode::Compression:
            ++stats.compressive_failures;
            break;
        case BondFailureMode::Shear:
            ++stats.shear_failures;
            break;
        case BondFailureMode::None:
            break;
        }
    }
}

} // namespace

BrittleBondSolver::BrittleBondSolver(BrittleSolverSettings settings)
    : settings_(settings) {
    if (settings_.substeps == 0U ||
        settings_.constraint_iterations == 0U) {
        throw std::invalid_argument(
            "solver requires at least one substep and constraint iteration");
    }
    if (!settings_.use_support_plane) {
        settings_.support_plane = makeSupportPlane(
            {0.0, settings_.floor_height_m, 0.0},
            {0.0, 1.0, 0.0});
        settings_.surface_dynamic_friction = settings_.floor_friction;
    }
}

ActiveMatter BrittleBondSolver::activate(
    MatterBodyId body_id,
    const LatticeAsset &asset,
    const CompiledBrittleMaterial &material,
    const RigidSnapshot &rigid,
    const ImpactEvent &impact) const {
    if (!impact.involves(body_id)) {
        throw std::invalid_argument(
            "activation impact does not involve body");
    }

    ActiveMatter matter;
    matter.body_id = body_id;
    matter.asset = &asset;
    matter.material = material;
    matter.nodes.reserve(asset.nodes.size());
    matter.reference_positions_world_m.reserve(asset.nodes.size());
    matter.bonds.resize(asset.bonds.size());

    for (const LatticeNodeRest &rest_node : asset.nodes) {
        const Vec3 rotated_local = rigid.orientation_world.rotate(
            rest_node.local_position_m - asset.rest_center_of_mass_m);
        const Vec3 position =
            rigid.center_of_mass_world_m + rotated_local;
        const Vec3 velocity =
            rigid.linear_velocity_m_s +
            cross(rigid.angular_velocity_rad_s, rotated_local);
        matter.nodes.push_back({
            position,
            position,
            velocity,
            rest_node.represented_volume_m3 * material.density_kg_m3,
            rigid.angular_velocity_rad_s,
        });
        matter.reference_positions_world_m.push_back(position);
    }

    injectInternalImpactPulse(
        matter,
        impact,
        normalized(impact.normalInto(body_id)));
    return matter;
}

void BrittleBondSolver::injectInternalImpactPulse(
    ActiveMatter &matter,
    const ImpactEvent &impact,
    const Vec3 &normal_into_target) const {
    if (matter.nodes.empty() || impact.available_normal_energy_j <= 0.0) {
        return;
    }

    const double influence_radius = std::max(
        2.5 * matter.asset->recipe.voxel_size_m,
        0.30 * matter.asset->recipe.radius_m);
    std::vector<Vec3> delta_velocity(matter.nodes.size());

    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        const ActiveNodeState &node = matter.nodes[index];
        const double distance =
            length(node.position_world_m - impact.contact_point_world_m);
        const double normalized_distance = distance / influence_radius;
        const double weight = normalized_distance < 1.0
                                  ? std::exp(
                                        -4.0 * normalized_distance *
                                        normalized_distance)
                                  : 0.0;
        delta_velocity[index] = weight * normal_into_target;
    }

    removeRigidMomentumComponents(matter, delta_velocity);

    double raw_internal_energy = 0.0;
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        raw_internal_energy +=
            0.5 * matter.nodes[index].mass_kg *
            lengthSquared(delta_velocity[index]);
    }
    if (raw_internal_energy <= 1.0e-12) {
        return;
    }

    const double requested_energy = std::min(
        settings_.maximum_internal_energy_j,
        settings_.impact_internal_energy_fraction *
            impact.available_normal_energy_j);
    const double scale =
        std::sqrt(requested_energy / raw_internal_energy);
    for (std::size_t index = 0; index < matter.nodes.size(); ++index) {
        matter.nodes[index].velocity_m_s +=
            scale * delta_velocity[index];
    }
}

MaterialStepStats BrittleBondSolver::step(
    ActiveMatter &matter,
    double frame_dt_s,
    const Vec3 &gravity_m_s2,
    CoupledSphereState *sphere,
    const SphereMaterialContactSettings &contact) const {
    if (matter.asset == nullptr || frame_dt_s <= 0.0) {
        throw std::invalid_argument(
            "active matter and positive frame step are required");
    }

    MaterialStepStats stats;
    const std::size_t broken_before = countBrokenBonds(matter);
    const double substep_dt =
        frame_dt_s / static_cast<double>(settings_.substeps);

    for (unsigned substep = 0; substep < settings_.substeps; ++substep) {
        for (ActiveBondState &bond : matter.bonds) {
            bond.peak_tensile_stretch = 0.0;
            bond.peak_compressive_strain = 0.0;
            bond.peak_shear_strain = 0.0;
            bond.accumulated_lambda = 0.0;
        }

        for (ActiveNodeState &node : matter.nodes) {
            node.previous_position_world_m = node.position_world_m;
            node.velocity_m_s += substep_dt * gravity_m_s2;
        }
        if (sphere) {
            accumulateContactStats(stats.rigid_contact, solveSphereMaterialContacts(
                matter, *sphere, substep_dt, contact));
        }
        for (ActiveNodeState &node : matter.nodes) {
            node.position_world_m += substep_dt * node.velocity_m_s;
        }

        const auto before_constraints = measureMaterialMechanics(matter, gravity_m_s2);
        for (unsigned iteration = 0;
             iteration < settings_.constraint_iterations;
             ++iteration) {
            for (std::size_t bond_index = 0;
                 bond_index < matter.bonds.size();
                 ++bond_index) {
                solveBond(matter, bond_index, substep_dt);
            }
        }

        for (ActiveNodeState &node : matter.nodes) {
            node.velocity_m_s =
                (node.position_world_m - node.previous_position_world_m) / substep_dt;
        }
        const auto after_constraints = measureMaterialMechanics(matter, gravity_m_s2);
        stats.constraint_angular_momentum_delta_kg_m2_s +=
            after_constraints.angular_momentum_kg_m2_s - before_constraints.angular_momentum_kg_m2_s;
        stats.constraint_mechanical_energy_delta_j +=
            after_constraints.mechanicalEnergy() - before_constraints.mechanicalEnergy();
        stats.internal_damping_loss_j += dampInternalBonds(matter, substep_dt);
        if (sphere) {
            accumulateContactStats(stats.rigid_contact, solveSphereMaterialContacts(
                matter, *sphere, substep_dt, contact, true));
        }
        for (ActiveNodeState &node : matter.nodes) {
            applySupportContact(node, settings_);
        }

        const std::vector<NodeStrainState> node_strains =
            calculateNodeStrains(matter);
        for (std::size_t bond_index = 0;
             bond_index < matter.bonds.size();
             ++bond_index) {
            ActiveBondState &state = matter.bonds[bond_index];
            if (!state.alive) {
                continue;
            }
            const BondRest &rest = matter.asset->bonds[bond_index];
            const NodeStrainState &strain_a = node_strains[rest.node_a];
            const NodeStrainState &strain_b = node_strains[rest.node_b];
            state.peak_tensile_stretch = std::max({
                state.peak_tensile_stretch,
                strain_a.tensile,
                strain_b.tensile,
            });
            state.peak_compressive_strain = std::max({
                state.peak_compressive_strain,
                strain_a.compressive,
                strain_b.compressive,
            });
            state.peak_shear_strain = std::max({
                state.peak_shear_strain,
                strain_a.shear,
                strain_b.shear,
            });

            stats.maximum_tensile_stretch = std::max(
                stats.maximum_tensile_stretch,
                state.peak_tensile_stretch);
            stats.maximum_compressive_strain = std::max(
                stats.maximum_compressive_strain,
                state.peak_compressive_strain);
            stats.maximum_shear_strain = std::max(
                stats.maximum_shear_strain,
                state.peak_shear_strain);

            const double tensile_damage = damageProgress(
                state.peak_tensile_stretch,
                rest.damage_start_stretch,
                rest.damage_end_stretch);
            const double compressive_damage = damageProgress(
                state.peak_compressive_strain,
                rest.compression_damage_start_strain,
                rest.compression_damage_end_strain);
            const double shear_damage = damageProgress(
                state.peak_shear_strain,
                rest.shear_damage_start_strain,
                rest.shear_damage_end_strain);

            double driving_damage = tensile_damage;
            BondFailureMode driving_mode = BondFailureMode::Tension;
            if (compressive_damage > driving_damage) {
                driving_damage = compressive_damage;
                driving_mode = BondFailureMode::Compression;
            }
            if (shear_damage > driving_damage) {
                driving_damage = shear_damage;
                driving_mode = BondFailureMode::Shear;
            }
            if (driving_damage > state.damage) {
                state.damage = driving_damage;
                state.failure_mode = driving_mode;
            }
            if (state.damage >= 1.0) {
                // This is removed stored energy, not a calibrated crack-work law.
                // Name it explicitly so damage cannot silently erase the ledger.
                const double extension = length(matter.nodes[rest.node_b].position_world_m -
                    matter.nodes[rest.node_a].position_world_m) - rest.rest_length_m;
                if (rest.compliance > 0.0)
                    stats.unassigned_bond_removal_energy_j += .5 * extension * extension / rest.compliance;
                state.alive = false;
                matter.connectivity_dirty = true;
            }
        }
    }

    const std::size_t broken_after = countBrokenBonds(matter);
    stats.broken_bonds_this_step = broken_after - broken_before;
    stats.total_broken_bonds = broken_after;
    stats.live_bonds = matter.bonds.size() - broken_after;
    accumulateFailureCounts(matter, stats);

    for (const ActiveNodeState &node : matter.nodes) {
        const double speed = length(node.velocity_m_s);
        stats.maximum_speed_m_s =
            std::max(stats.maximum_speed_m_s, speed);
        stats.kinetic_energy_j +=
            0.5 * node.mass_kg * speed * speed;
        const double cell_size = matter.asset->recipe.voxel_size_m;
        stats.kinetic_energy_j += node.mass_kg * cell_size * cell_size / 12.0 *
            lengthSquared(node.spin_angular_velocity_rad_s);
    }
    for (std::size_t bond_index = 0;
         bond_index < matter.bonds.size();
         ++bond_index) {
        if (!matter.bonds[bond_index].alive) {
            continue;
        }
        const BondRest &rest = matter.asset->bonds[bond_index];
        const double extension =
            length(
                matter.nodes[rest.node_b].position_world_m -
                matter.nodes[rest.node_a].position_world_m) -
            rest.rest_length_m;
        if (rest.compliance > 0.0) {
            stats.estimated_elastic_energy_j +=
                0.5 * extension * extension / rest.compliance;
        }
    }

    ++matter.step_index;
    return stats;
}

} // namespace banjo
