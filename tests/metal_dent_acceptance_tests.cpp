#include "physics/SpherePatchWorld.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <vector>

using namespace banjo;

namespace {

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

SmallStrainLaw illustrativeJ2() {
    SmallStrainLaw law;
    law.kind = SmallStrainLawKind::J2Plastic;
    law.j2 = {.young_modulus_pa = 1.e6,
              .poisson_ratio = 0.25,
              .initial_yield_stress_pa = 1200,
              .isotropic_hardening_modulus_pa = 2.e4,
              .maximum_total_strain_norm = 0.08};
    law.maximum_total_strain_norm = 0.08;
    return law;
}

PatchDefinition supportedPatch() {
    auto definition = makeTetrahedralBrick({0.08, 0.02, 0.08}, {2, 1, 2},
                                           {illustrativeJ2(), 1000});
    for (std::size_t i = 0; i < definition.reference_positions_m.size(); ++i)
        if (definition.reference_positions_m[i].y == 0)
            definition.fixed_components[i] = {true, true, true};
    return definition;
}

SpherePatchWorld makeWorld(const PatchDefinition &definition) {
    constexpr double radius = 0.012;
    const double sphere_mass =
        (4.0 / 3.0) * std::acos(-1.0) * radius * radius * radius * 7870;
    return SpherePatchWorld(
        definition, {{0.007, 0.0325, 0.009}, {}, {}, radius, sphere_mass}, {},
        {.friction_coefficient = 0.15,
         .contact_margin_m = 1.e-6,
         .maximum_penetration_m = 1.e-5});
}

DynamicPatchLoad gravityLoad(std::size_t count) {
    DynamicPatchLoad load;
    load.nodal_forces_n.resize(count);
    load.gravity_m_s2 = {0, -9.81, 0};
    return load;
}

bool same(Vec3 a, Vec3 b) {
    return a.x == b.x && a.y == b.y && a.z == b.z;
}

bool samePatch(const PatchState &a, const PatchState &b) {
    if (a.material_points != b.material_points || a.revision != b.revision ||
        a.accumulated_trapezoidal_external_work_j !=
            b.accumulated_trapezoidal_external_work_j ||
        a.accumulated_backward_euler_external_work_j !=
            b.accumulated_backward_euler_external_work_j ||
        a.displacements_m.size() != b.displacements_m.size() ||
        a.last_nodal_forces_n.size() != b.last_nodal_forces_n.size())
        return false;
    for (std::size_t i = 0; i < a.displacements_m.size(); ++i)
        if (!same(a.displacements_m[i], b.displacements_m[i])) return false;
    for (std::size_t i = 0; i < a.last_nodal_forces_n.size(); ++i)
        if (!same(a.last_nodal_forces_n[i], b.last_nodal_forces_n[i])) return false;
    return true;
}

bool sameDynamic(const DynamicPatchState &a, const DynamicPatchState &b) {
    if (a.time_s != b.time_s || a.accumulated_external_force_work_j !=
                                  b.accumulated_external_force_work_j ||
        !same(a.accumulated_support_impulse_n_s, b.accumulated_support_impulse_n_s) ||
        a.revision != b.revision || a.velocities_m_s.size() != b.velocities_m_s.size())
        return false;
    for (std::size_t i = 0; i < a.velocities_m_s.size(); ++i)
        if (!same(a.velocities_m_s[i], b.velocities_m_s[i])) return false;
    return true;
}

bool sameSphere(const PatchSphere &a, const PatchSphere &b) {
    return same(a.center_m, b.center_m) && same(a.velocity_m_s, b.velocity_m_s) &&
           same(a.spin_rad_s, b.spin_rad_s) && a.radius_m == b.radius_m &&
           a.mass_kg == b.mass_kg;
}

} // namespace

int main() {
    try {
        const auto definition = supportedPatch();
        auto uninterrupted = makeWorld(definition);
        auto challenged = makeWorld(definition);
        const auto load = gravityLoad(definition.reference_positions_m.size());
        const Vec3 sphere_gravity{0, -9.81, 0};
        const double dt = uninterrupted.material().stableTimeStepLimitS() * 0.025;
        bool yielded = false;
        unsigned steps_to_yield = 0;
        double maximum_step_energy_residual = 0;
        for (; steps_to_yield < 12000; ++steps_to_yield) {
            const auto first = uninterrupted.step(dt, load, {}, sphere_gravity);
            const auto second = challenged.step(dt, load, {}, sphere_gravity);
            check(first.accepted && second.accepted,
                  "illustrative sphere/J2 trajectory must reach yielding within its bounds");
            maximum_step_energy_residual =
                std::max(maximum_step_energy_residual,
                         std::abs(first.numerical_energy_balance_residual_j));
            for (const auto &point : uninterrupted.material().patch().state().material_points)
                yielded = yielded || point.equivalent_plastic_strain > 0;
            if (yielded) break;
        }
        check(yielded, "sphere contact must create committed J2 history in this acceptance fixture");
        check(samePatch(uninterrupted.material().patch().state(),
                        challenged.material().patch().state()) &&
                  sameDynamic(uninterrupted.material().state(), challenged.material().state()) &&
                  sameSphere(uninterrupted.sphere(), challenged.sphere()),
              "identical pre-rejection J2 trajectories must agree exactly");

        const PatchState accepted_patch = challenged.material().patch().state();
        const DynamicPatchState accepted_dynamic = challenged.material().state();
        const PatchSphere accepted_sphere = challenged.sphere();
        const auto rejected = challenged.step(
            2 * challenged.material().stableTimeStepLimitS(), load, {}, sphere_gravity);
        check(!rejected.accepted, "over-stability-limit J2 step must reject");
        check(samePatch(challenged.material().patch().state(), accepted_patch) &&
                  sameDynamic(challenged.material().state(), accepted_dynamic) &&
                  sameSphere(challenged.sphere(), accepted_sphere),
              "rejected post-yield step must preserve full 3D J2 and sphere state exactly");

        for (unsigned step = 0; step < 200; ++step) {
            const auto first = uninterrupted.step(dt, load, {}, sphere_gravity);
            const auto second = challenged.step(dt, load, {}, sphere_gravity);
            check(first.accepted && second.accepted,
                  "post-rejection J2 continuation must remain accepted");
        }
        check(samePatch(uninterrupted.material().patch().state(),
                        challenged.material().patch().state()) &&
                  sameDynamic(uninterrupted.material().state(), challenged.material().state()) &&
                  sameSphere(uninterrupted.sphere(), challenged.sphere()),
              "rejected trial must not alter deterministic continuation of retained J2 state");

        double maximum_equivalent_plastic_strain = 0;
        double maximum_plastic_tensor_norm = 0;
        for (const auto &point : challenged.material().patch().state().material_points) {
            maximum_equivalent_plastic_strain =
                std::max(maximum_equivalent_plastic_strain,
                         point.equivalent_plastic_strain);
            maximum_plastic_tensor_norm =
                std::max(maximum_plastic_tensor_norm, frobeniusNorm(point.plastic_strain));
        }
        check(maximum_equivalent_plastic_strain > 0 && maximum_plastic_tensor_norm > 0,
              "retained dent state must include tensor plastic strain, not only a display scalar");
        std::cout << "[INFO] dt_s=" << dt << " steps_to_yield=" << steps_to_yield + 1
                  << " max_eq_plastic=" << maximum_equivalent_plastic_strain
                  << " max_plastic_tensor_norm=" << maximum_plastic_tensor_norm
                  << " plastic_dissipation_j="
                  << challenged.material().report().plastic_dissipation_j
                  << " max_step_energy_residual_j=" << maximum_step_energy_residual << '\n';
        std::cout << "[PASS] sphere-driven J2 state rollback and deterministic continuation\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
