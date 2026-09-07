#include "physics/SpherePatchSnapshot.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <vector>

using namespace banjo;

namespace {

void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

SmallStrainLaw j2Law() {
    SmallStrainLaw law;
    law.kind = SmallStrainLawKind::J2Plastic;
    law.j2 = {.young_modulus_pa = 1.e6,
              .poisson_ratio = .25,
              .initial_yield_stress_pa = 1200,
              .isotropic_hardening_modulus_pa = 2.e4,
              .maximum_total_strain_norm = .08};
    law.maximum_total_strain_norm = .08;
    return law;
}

PatchDefinition definition() {
    auto result = makeTetrahedralBrick({.08, .02, .08}, {2, 1, 2}, {j2Law(), 1000});
    for (std::size_t i = 0; i < result.reference_positions_m.size(); ++i)
        if (result.reference_positions_m[i].y == 0)
            result.fixed_components[i] = {true, true, true};
    return result;
}

SpherePatchWorld world(const PatchDefinition &patch) {
    constexpr double radius = .012;
    const double mass = (4. / 3.) * std::acos(-1.) * radius * radius * radius * 7870;
    return SpherePatchWorld(
        patch, {{.007, .0325, .009}, {}, {}, radius, mass}, {},
        {.friction_coefficient = .15, .contact_margin_m = 1.e-6,
         .maximum_penetration_m = 1.e-5});
}

DynamicPatchLoad load(std::size_t nodes) {
    DynamicPatchLoad result;
    result.nodal_forces_n.resize(nodes);
    result.gravity_m_s2 = {0, -9.81, 0};
    return result;
}

bool same(Vec3 a, Vec3 b) {
    return a.x == b.x && a.y == b.y && a.z == b.z;
}

bool sameState(const SpherePatchSnapshot &a, const SpherePatchSnapshot &b) {
    if (a.patch.material_points != b.patch.material_points ||
        a.patch.revision != b.patch.revision || a.dynamic.revision != b.dynamic.revision ||
        a.dynamic.time_s != b.dynamic.time_s ||
        a.dynamic.accumulated_external_force_work_j !=
            b.dynamic.accumulated_external_force_work_j ||
        !same(a.dynamic.accumulated_support_impulse_n_s,
              b.dynamic.accumulated_support_impulse_n_s) ||
        !same(a.sphere.center_m, b.sphere.center_m) ||
        !same(a.sphere.velocity_m_s, b.sphere.velocity_m_s) ||
        !same(a.sphere.spin_rad_s, b.sphere.spin_rad_s) ||
        a.patch.displacements_m.size() != b.patch.displacements_m.size() ||
        a.dynamic.velocities_m_s.size() != b.dynamic.velocities_m_s.size())
        return false;
    for (std::size_t i = 0; i < a.patch.displacements_m.size(); ++i)
        if (!same(a.patch.displacements_m[i], b.patch.displacements_m[i])) return false;
    for (std::size_t i = 0; i < a.dynamic.velocities_m_s.size(); ++i)
        if (!same(a.dynamic.velocities_m_s[i], b.dynamic.velocities_m_s[i])) return false;
    return true;
}

std::size_t estimatedPayloadBytes(const SpherePatchSnapshot &snapshot) {
    std::size_t bytes = sizeof(snapshot);
    bytes += snapshot.definition.reference_positions_m.size() * sizeof(Vec3);
    bytes += snapshot.definition.elements.size() * sizeof(PatchTet);
    bytes += snapshot.definition.materials.size() * sizeof(PatchMaterial);
    bytes += snapshot.definition.fixed_components.size() * sizeof(std::array<bool, 3>);
    bytes += snapshot.patch.displacements_m.size() * sizeof(Vec3);
    bytes += snapshot.patch.material_points.size() * sizeof(J2State);
    bytes += snapshot.patch.last_nodal_forces_n.size() * sizeof(Vec3);
    bytes += snapshot.dynamic.velocities_m_s.size() * sizeof(Vec3);
    bytes += snapshot.accepted_evaluation.internal_forces_n.size() * sizeof(Vec3);
    bytes += snapshot.accepted_evaluation.responses.size() * sizeof(SmallStrainResponse);
    return bytes;
}

void rejectsWithoutMutation(SpherePatchWorld &target, SpherePatchSnapshot corrupt) {
    const auto before = target.snapshot();
    bool rejected = false;
    try {
        target.restoreSnapshot(corrupt);
    } catch (const std::invalid_argument &) {
        rejected = true;
    }
    check(rejected, "corrupt or incompatible snapshot must reject");
    check(sameState(target.snapshot(), before),
          "failed snapshot restore must leave the complete world unchanged");
}

} // namespace

int main(int argc, char **argv) {
    try {
        const auto patch = definition();
        auto source = world(patch);
        const auto gravity = load(patch.reference_positions_m.size());
        const Vec3 sphere_gravity{0, -9.81, 0};
        const double dt = source.material().stableTimeStepLimitS() * .025;
        bool yielded = false;
        for (unsigned step = 0; step < 12000 && !yielded; ++step) {
            const auto report = source.step(dt, gravity, {}, sphere_gravity);
            check(report.accepted, "source J2 trajectory failed before snapshot");
            for (const auto &point : source.material().patch().state().material_points)
                yielded = yielded || point.equivalent_plastic_strain > 0;
        }
        check(yielded, "snapshot fixture must contain committed plastic history");
        const auto checkpoint = source.snapshot();
        double maximum_equivalent_plastic_strain = 0.;
        double maximum_plastic_strain_norm = 0.;
        double maximum_displacement_m = 0.;
        for (const auto &point : checkpoint.patch.material_points) {
            maximum_equivalent_plastic_strain =
                std::max(maximum_equivalent_plastic_strain,
                         point.equivalent_plastic_strain);
            maximum_plastic_strain_norm =
                std::max(maximum_plastic_strain_norm,
                         frobeniusNorm(point.plastic_strain));
        }
        for (const auto displacement : checkpoint.patch.displacements_m)
            maximum_displacement_m = std::max(maximum_displacement_m, length(displacement));

        auto restored = world(patch);
        restored.restoreSnapshot(checkpoint);
        check(sameState(restored.snapshot(), checkpoint),
              "restored sphere-patch snapshot must reproduce captured semantic state exactly");
        for (unsigned step = 0; step < 300; ++step) {
            const auto a = source.step(dt, gravity, {}, sphere_gravity);
            const auto b = restored.step(dt, gravity, {}, sphere_gravity);
            check(a.accepted && b.accepted, "continued restored trajectory must remain accepted");
        }
        check(sameState(source.snapshot(), restored.snapshot()),
              "restored J2 world must continue bitwise-identically to uninterrupted control");
        const bool restart_bitwise_parity = true;

        auto corrupt = checkpoint;
        corrupt.patch.material_points[0].plastic_strain.xx += .01;
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.definition.materials[0].density_kg_m3 += 1;
        rejectsWithoutMutation(restored, corrupt);
        const bool incompatible_state_rejected_atomically = true;
        corrupt = checkpoint;
        corrupt.definition.fixed_components[0][0] =
            !corrupt.definition.fixed_components[0][0];
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.dynamic.time_s = std::numeric_limits<double>::quiet_NaN();
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.dynamic.velocities_m_s.pop_back();
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.accepted_evaluation.internal_forces_n[0].x += 1.e6;
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.accepted_evaluation.responses[0].stress_pa.xx += 1.e5;
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.accepted_evaluation.responses[0].stored_free_energy_j_m3 += 1.;
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.accepted_evaluation.responses[0].plastic_dissipation_j_m3 += 1.;
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.accepted_evaluation.maximum_displacement_gradient_norm += .01;
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        corrupt.patch.displacements_m.resize(
            checkpoint.patch.displacements_m.size() + 1000000);
        rejectsWithoutMutation(restored, std::move(corrupt));
        corrupt = checkpoint;
        corrupt.accepted_evaluation.internal_forces_n.resize(
            checkpoint.accepted_evaluation.internal_forces_n.size() + 1000000);
        rejectsWithoutMutation(restored, std::move(corrupt));
        corrupt = checkpoint;
        corrupt.sphere.center_m =
            patch.reference_positions_m[patch.elements.front().nodes.front()] +
            checkpoint.patch.displacements_m[patch.elements.front().nodes.front()];
        rejectsWithoutMutation(restored, corrupt);
        corrupt = checkpoint;
        ++corrupt.version;
        rejectsWithoutMutation(restored, corrupt);

        if (argc == 2) {
            std::ofstream evidence(argv[1]);
            check(static_cast<bool>(evidence), "snapshot evidence output could not be opened");
            evidence << std::setprecision(17)
                     << "{\n"
                     << "  \"schema\": \"banjo.metal-snapshot-evidence.v1\",\n"
                     << "  \"snapshot_storage\": \"in_memory_only\",\n"
                     << "  \"node_count\": " << checkpoint.patch.displacements_m.size() << ",\n"
                     << "  \"tetrahedron_count\": " << checkpoint.patch.material_points.size() << ",\n"
                     << "  \"material_point_count\": " << checkpoint.patch.material_points.size() << ",\n"
                     << "  \"estimated_payload_bytes_excluding_allocator_overhead\": "
                     << estimatedPayloadBytes(checkpoint) << ",\n"
                     << "  \"snapshot_time_s\": " << checkpoint.dynamic.time_s << ",\n"
                     << "  \"maximum_equivalent_plastic_strain\": "
                     << maximum_equivalent_plastic_strain << ",\n"
                     << "  \"maximum_plastic_strain_tensor_norm\": "
                     << maximum_plastic_strain_norm << ",\n"
                     << "  \"accepted_stored_free_energy_j\": "
                     << checkpoint.accepted_evaluation.stored_free_energy_j << ",\n"
                     << "  \"accepted_plastic_dissipation_j\": "
                     << checkpoint.accepted_evaluation.plastic_dissipation_j << ",\n"
                     << "  \"maximum_displacement_m\": " << maximum_displacement_m << ",\n"
                     << "  \"restart_continuation_steps\": 300,\n"
                     << "  \"restart_bitwise_parity\": "
                     << (restart_bitwise_parity ? "true" : "false") << ",\n"
                     << "  \"incompatible_state_rejected_atomically\": "
                     << (incompatible_state_rejected_atomically ? "true" : "false") << ",\n"
                     << "  \"claim_limits\": \"Synthetic small-strain J2 fixture; no compact codec or calibrated unloaded metal dent claim.\"\n"
                     << "}\n";
            check(static_cast<bool>(evidence), "snapshot evidence output failed");
        } else {
            check(argc == 1, "expected at most one evidence output path");
        }

        return 0;
    } catch (const std::exception &) {
        return 1;
    }
}
