#include "physics/FractureComponentState.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {

void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

bool finite(Vec3 value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

void addPointInertia(Mat3 &inertia, Vec3 r, double mass) {
    const double radius2 = lengthSquared(r);
    const double values[3]{r.x, r.y, r.z};
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j)
            inertia.m[i][j] += mass * ((i == j ? radius2 : 0.) - values[i] * values[j]);
}

} // namespace

FractureComponentStateResult extractFractureComponentStates(
    const FractureTopology &topology,
    const FractureSeparation &separation,
    const std::vector<Vec3> &positions,
    const std::vector<Vec3> &velocities,
    Vec3 common_origin,
    const FractureComponentStateLimits &limits) {
    require(limits.maximum_local_nodes > 0 && limits.maximum_local_nodes <= 65536 &&
                limits.maximum_tetrahedra > 0 && limits.maximum_tetrahedra <= 16384 &&
                limits.maximum_components > 0 && limits.maximum_components <= 16384 &&
                limits.maximum_node_visits > 0 && limits.maximum_node_visits <= 196608,
            "Invalid fracture component-state count budget");
    require(finite(common_origin), "Fracture component common origin must be finite");
    const std::size_t node_count = topology.local_nodal_masses_kg.size();
    const std::size_t tet_count = topology.tetrahedra.size();
    require(node_count > 0 && node_count <= limits.maximum_local_nodes &&
                positions.size() == node_count && velocities.size() == node_count,
            "Fracture component local-node state is invalid or exceeds budget");
    require(tet_count > 0 && tet_count <= limits.maximum_tetrahedra &&
                topology.duplicated_definition.elements.size() == tet_count &&
                topology.local_to_original_node.size() == node_count,
            "Fracture component topology is invalid or exceeds budget");
    require(separation.components.size() > 0 &&
                separation.components.size() <= limits.maximum_components &&
                separation.component_by_tetrahedron.size() == tet_count,
            "Fracture component partition is invalid or exceeds budget");
    for (std::size_t i = 0; i < node_count; ++i)
        require(finite(positions[i]) && finite(velocities[i]) &&
                    std::isfinite(topology.local_nodal_masses_kg[i]) &&
                    topology.local_nodal_masses_kg[i] > 0.,
                "Invalid fracture component nodal state or mass");

    std::vector<bool> tet_seen(tet_count, false);
    std::vector<bool> node_seen(node_count, false);
    FractureComponentStateResult out;
    out.common_origin_m = common_origin;
    out.components.reserve(separation.components.size());
    const auto charge_node = [&] {
        require(out.node_visits < limits.maximum_node_visits,
                "Fracture component node-visit budget exhausted");
        ++out.node_visits;
    };
    for (std::size_t component_id = 0; component_id < separation.components.size(); ++component_id) {
        const auto &members = separation.components[component_id];
        require(!members.empty() && std::is_sorted(members.begin(), members.end()),
                "Fracture component tetrahedra must be nonempty and sorted");
        FractureComponentState component;
        component.component = static_cast<unsigned>(component_id);
        component.tetrahedra = members;
        for (const unsigned tet : members) {
            require(tet < tet_count && !tet_seen[tet] &&
                        separation.component_by_tetrahedron[tet] == component_id,
                    "Fracture component tetrahedron partition mismatch");
            tet_seen[tet] = true;
            const auto &element = topology.duplicated_definition.elements[tet];
            for (const unsigned node : element.nodes) {
                charge_node();
                require(node < node_count && !node_seen[node],
                        "Fracture component tetrahedron node is invalid or repeated");
                node_seen[node] = true;
                const double mass = topology.local_nodal_masses_kg[node];
                require(mass == topology.tetrahedra[tet].mass_kg * .25,
                        "Fracture component local mass differs from compiled tetrahedron mass");
                component.mass_kg += mass;
                component.center_of_mass_m += mass * positions[node];
                component.linear_momentum_kg_m_s += mass * velocities[node];
                component.kinetic_energy_j += .5 * mass * lengthSquared(velocities[node]);
            }
        }
        require(std::isfinite(component.mass_kg) && component.mass_kg > 0.,
                "Invalid fracture component mass");
        component.center_of_mass_m = component.center_of_mass_m / component.mass_kg;
        component.center_of_mass_velocity_m_s =
            component.linear_momentum_kg_m_s / component.mass_kg;
        component.translational_kinetic_energy_j =
            .5 * component.mass_kg * lengthSquared(component.center_of_mass_velocity_m_s);
        for (const unsigned tet : members) {
            const auto &element = topology.duplicated_definition.elements[tet];
            for (const unsigned node : element.nodes) {
                charge_node();
                const double mass = topology.local_nodal_masses_kg[node];
                const Vec3 r = positions[node] - component.center_of_mass_m;
                const Vec3 relative_velocity =
                    velocities[node] - component.center_of_mass_velocity_m_s;
                component.angular_momentum_about_com_kg_m2_s +=
                    mass * cross(r, relative_velocity);
                addPointInertia(component.inertia_about_com_kg_m2, r, mass);
            }
        }
        double inertia_scale = 0.;
        for (unsigned i = 0; i < 3; ++i)
            inertia_scale = std::max(inertia_scale,
                                     std::abs(component.inertia_about_com_kg_m2.m[i][i]));
        const double determinant = component.inertia_about_com_kg_m2.determinant();
        const double determinant_tolerance =
            std::max(1.e-300, inertia_scale * inertia_scale * inertia_scale * 1.e-12);
        component.inertia_singular = !std::isfinite(determinant) ||
                                     std::abs(determinant) <= determinant_tolerance;
        if (!component.inertia_singular) {
            const auto inverse = component.inertia_about_com_kg_m2.inverse(0.);
            require(inverse.has_value(), "Fracture component inertia inverse failed");
            component.best_fit_angular_velocity_rad_s =
                *inverse * component.angular_momentum_about_com_kg_m2_s;
            require(finite(component.best_fit_angular_velocity_rad_s),
                    "Fracture component angular velocity exceeds numeric range");
            component.rigid_rotational_kinetic_energy_j =
                .5 * dot(component.best_fit_angular_velocity_rad_s,
                         component.angular_momentum_about_com_kg_m2_s);
        }
        for (const unsigned tet : members) {
            const auto &element = topology.duplicated_definition.elements[tet];
            for (const unsigned node : element.nodes) {
                charge_node();
                const Vec3 r = positions[node] - component.center_of_mass_m;
                const Vec3 unresolved = velocities[node] -
                    component.center_of_mass_velocity_m_s -
                    cross(component.best_fit_angular_velocity_rad_s, r);
                component.internal_kinetic_energy_j +=
                    .5 * topology.local_nodal_masses_kg[node] * lengthSquared(unresolved);
            }
        }
        component.kinetic_decomposition_residual_j = component.kinetic_energy_j -
            component.translational_kinetic_energy_j -
            component.rigid_rotational_kinetic_energy_j - component.internal_kinetic_energy_j;
        require(finite(component.center_of_mass_m) &&
                    finite(component.linear_momentum_kg_m_s) &&
                    finite(component.angular_momentum_about_com_kg_m2_s) &&
                    std::isfinite(component.kinetic_energy_j) &&
                    std::isfinite(component.internal_kinetic_energy_j),
                "Fracture component result exceeds numeric range");
        out.mass_kg += component.mass_kg;
        out.linear_momentum_kg_m_s += component.linear_momentum_kg_m_s;
        out.angular_momentum_about_common_origin_kg_m2_s +=
            component.angular_momentum_about_com_kg_m2_s +
            cross(component.center_of_mass_m - common_origin,
                  component.linear_momentum_kg_m_s);
        out.kinetic_energy_j += component.kinetic_energy_j;
        out.components.push_back(std::move(component));
    }
    require(std::all_of(tet_seen.begin(), tet_seen.end(), [](bool value) { return value; }),
            "Fracture component partition omits a tetrahedron");
    require(std::all_of(node_seen.begin(), node_seen.end(), [](bool value) { return value; }),
            "Fracture component topology omits a local node");
    require(out.node_visits == 3 * node_count,
            "Fracture topology local nodes are not tet-local");
    const double mass_tolerance = 32. * std::numeric_limits<double>::epsilon() *
                                  std::max(out.mass_kg, topology.mass_kg);
    require(std::isfinite(topology.mass_kg) && topology.mass_kg > 0. &&
                std::abs(out.mass_kg - topology.mass_kg) <= mass_tolerance,
            "Fracture component mass differs from compiled topology mass");
    require(std::isfinite(out.mass_kg) && out.mass_kg > 0. &&
                finite(out.linear_momentum_kg_m_s) &&
                finite(out.angular_momentum_about_common_origin_kg_m2_s) &&
                std::isfinite(out.kinetic_energy_j),
            "Fracture component aggregate exceeds numeric range");
    return out;
}

} // namespace banjo
