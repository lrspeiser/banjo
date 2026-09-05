#include "prediction/BallScenarioProjection.hpp"

#include "core/Plane.hpp"
#include "material/MaterialCompiler.hpp"
#include "physics/ContactMechanics.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>
#include <stdexcept>

namespace banjo {
namespace {

[[nodiscard]] double sphereVolume(double radius_m) {
    return (4.0 / 3.0) * std::numbers::pi * radius_m * radius_m * radius_m;
}

[[nodiscard]] bool finiteVector(const Vec3 &value) {
    return std::isfinite(value.x) && std::isfinite(value.y) &&
           std::isfinite(value.z);
}

[[nodiscard]] std::uint64_t saturatedProduct(
    std::size_t bonds,
    unsigned iterations,
    unsigned substeps,
    unsigned steps) {
    const long double product =
        static_cast<long double>(bonds) * static_cast<long double>(iterations) *
        static_cast<long double>(substeps) * static_cast<long double>(steps);
    const long double maximum =
        static_cast<long double>(std::numeric_limits<std::uint64_t>::max());
    return product >= maximum
               ? std::numeric_limits<std::uint64_t>::max()
               : static_cast<std::uint64_t>(product);
}

[[nodiscard]] PredictedFailureMode classifyFailure(
    const BallScenarioInput &input,
    const ImpactProjection &impact) {
    if (impact.relative_normal_speed_m_s <= 0.0) {
        return PredictedFailureMode::None;
    }

    if (input.target_material.model == MaterialModel::BrittleBond) {
        const double brittle_index = std::max(
            impact.fracture_energy_ratio,
            impact.tensile_stress_ratio);
        if (brittle_index < 0.75) {
            return PredictedFailureMode::Elastic;
        }
        if (brittle_index < 1.5) {
            return PredictedFailureMode::SurfaceDamage;
        }
        if (brittle_index < 5.0) {
            return PredictedFailureMode::BrittleCrack;
        }
        return PredictedFailureMode::Fragmentation;
    }

    if (impact.yield_stress_ratio >= 1.0) {
        return PredictedFailureMode::Yielding;
    }
    return PredictedFailureMode::Elastic;
}

[[nodiscard]] RuntimeStrategy chooseRuntimeStrategy(
    const BallScenarioInput &input,
    PredictedFailureMode failure,
    std::uint64_t estimated_constraint_solves) {
    const bool material_response =
        failure == PredictedFailureMode::BrittleCrack ||
        failure == PredictedFailureMode::Fragmentation ||
        failure == PredictedFailureMode::SurfaceDamage;
    if (!material_response ||
        input.target_material.model != MaterialModel::BrittleBond) {
        return RuntimeStrategy::RigidRealtime;
    }
    if (input.cached_material_outcome_available) {
        return RuntimeStrategy::CachedMaterial;
    }
    if (estimated_constraint_solves <= input.realtime_constraint_budget) {
        return RuntimeStrategy::MaterialRealtime;
    }
    if (input.realtime_constraint_budget > 0U &&
        estimated_constraint_solves <= input.realtime_constraint_budget * 4ULL) {
        return RuntimeStrategy::HybridAdaptive;
    }
    return RuntimeStrategy::PrecomputeRecommended;
}

} // namespace

std::string_view predictedFailureModeName(PredictedFailureMode mode) {
    switch (mode) {
    case PredictedFailureMode::None:
        return "no contact";
    case PredictedFailureMode::Elastic:
        return "elastic response";
    case PredictedFailureMode::SurfaceDamage:
        return "surface damage";
    case PredictedFailureMode::Yielding:
        return "plastic yielding";
    case PredictedFailureMode::BrittleCrack:
        return "brittle cracking";
    case PredictedFailureMode::Fragmentation:
        return "fragmentation";
    }
    return "unknown";
}

std::string_view inclineMotionRegimeName(InclineMotionRegime regime) {
    switch (regime) {
    case InclineMotionRegime::AtRest:
        return "at rest";
    case InclineMotionRegime::RollingWithoutSlip:
        return "rolling without slip";
    case InclineMotionRegime::Sliding:
        return "sliding";
    case InclineMotionRegime::Detached:
        return "detached / ballistic";
    }
    return "unknown";
}

std::string_view runtimeStrategyName(RuntimeStrategy strategy) {
    switch (strategy) {
    case RuntimeStrategy::RigidRealtime:
        return "rigid realtime";
    case RuntimeStrategy::MaterialRealtime:
        return "material realtime";
    case RuntimeStrategy::HybridAdaptive:
        return "adaptive hybrid";
    case RuntimeStrategy::PrecomputeRecommended:
        return "precompute recommended";
    case RuntimeStrategy::CachedMaterial:
        return "cached material outcome";
    }
    return "unknown";
}

ScenarioProjection projectBallScenario(const BallScenarioInput &input) {
    if (input.striker_radius_m <= 0.0 || input.target_radius_m <= 0.0 ||
        input.striker_speed_m_s < 0.0 || input.target_speed_m_s < 0.0 ||
        !finiteVector(input.gravity_world_m_s2) ||
        input.sphere_inertia_factor <= 0.0 || input.voxel_size_m <= 0.0 ||
        input.material_substeps == 0U || input.constraint_iterations == 0U ||
        input.estimated_material_steps == 0U) {
        throw std::invalid_argument("ball scenario input is invalid");
    }

    const CompiledContactMaterial striker_contact =
        compileContactMaterial(input.striker_material);
    const CompiledContactMaterial target_contact =
        compileContactMaterial(input.target_material);
    const CompiledContactMaterial surface_contact =
        compileContactMaterial(input.surface_material);
    const CombinedContactMaterial impact_contact =
        combineContactMaterials(striker_contact, target_contact);
    const CombinedContactMaterial incline_contact =
        combineContactMaterials(striker_contact, surface_contact);

    ScenarioProjection projection;
    ImpactProjection &impact = projection.impact;
    impact.striker_mass_kg = sphereVolume(input.striker_radius_m) *
                             input.striker_material.density_kg_m3;
    impact.target_mass_kg = sphereVolume(input.target_radius_m) *
                            input.target_material.density_kg_m3;
    impact.reduced_mass_kg =
        (impact.striker_mass_kg * impact.target_mass_kg) /
        (impact.striker_mass_kg + impact.target_mass_kg);
    impact.reduced_radius_m =
        (input.striker_radius_m * input.target_radius_m) /
        (input.striker_radius_m + input.target_radius_m);
    impact.relative_normal_speed_m_s =
        std::max(0.0, input.striker_speed_m_s - input.target_speed_m_s);
    impact.effective_modulus_pa = impact_contact.effective_modulus_pa;
    impact.combined_static_friction = impact_contact.static_friction;
    impact.combined_dynamic_friction = impact_contact.dynamic_friction;
    impact.combined_restitution = impact_contact.restitution;
    impact.combined_rolling_resistance = impact_contact.rolling_resistance;

    const HertzSphereImpactResult hertz = projectHertzSphereImpact({
        impact.effective_modulus_pa,
        impact.reduced_radius_m,
        impact.reduced_mass_kg,
        impact.relative_normal_speed_m_s,
    });
    impact.available_energy_j = hertz.available_energy_j;
    impact.maximum_indent_m = hertz.maximum_indent_m;
    impact.peak_force_n = hertz.peak_force_n;
    impact.contact_radius_m = hertz.contact_radius_m;
    impact.peak_contact_pressure_pa = hertz.peak_pressure_pa;

    const double nominal_fracture_area =
        std::numbers::pi * input.target_radius_m * input.target_radius_m;
    impact.fracture_energy_threshold_j =
        nominal_fracture_area * input.target_material.fracture_energy_j_m2 *
        std::max(
            0.0,
            input.target_material.calibration.activation_energy_scale);
    if (impact.fracture_energy_threshold_j > 0.0) {
        impact.fracture_energy_ratio =
            impact.available_energy_j / impact.fracture_energy_threshold_j;
    }
    if (input.target_material.tensile_strength_pa > 0.0) {
        impact.tensile_stress_ratio =
            hertz.maximum_subsurface_shear_pa /
            input.target_material.tensile_strength_pa;
    }
    if (input.target_material.compressive_strength_pa > 0.0) {
        impact.compressive_stress_ratio =
            impact.peak_contact_pressure_pa /
            input.target_material.compressive_strength_pa;
    }
    const double yield_reference =
        input.target_material.yield_strength_pa > 0.0
            ? input.target_material.yield_strength_pa
            : input.target_material.hardness_pa;
    if (yield_reference > 0.0) {
        impact.yield_stress_ratio =
            impact.peak_contact_pressure_pa / yield_reference;
    }

    const double momentum =
        impact.striker_mass_kg * input.striker_speed_m_s +
        impact.target_mass_kg * input.target_speed_m_s;
    const double relative_after =
        -impact.combined_restitution * impact.relative_normal_speed_m_s;
    impact.striker_post_speed_m_s =
        (momentum + impact.target_mass_kg * relative_after) /
        (impact.striker_mass_kg + impact.target_mass_kg);
    impact.target_post_speed_m_s =
        (momentum - impact.striker_mass_kg * relative_after) /
        (impact.striker_mass_kg + impact.target_mass_kg);
    impact.predicted_failure = classifyFailure(input, impact);

    InclineProjection &incline = projection.incline;
    incline.slope_angle_degrees = input.slope_angle_degrees;
    const SupportPlaneFrame plane =
        makeSupportPlaneFromSlopeDegrees(input.slope_angle_degrees);
    incline.gravity_tangent_m_s2 =
        dot(input.gravity_world_m_s2, plane.tangent_world);
    incline.gravity_outward_m_s2 =
        dot(input.gravity_world_m_s2, plane.normal_world);
    incline.gravity_normal_m_s2 =
        std::max(0.0, -incline.gravity_outward_m_s2);
    incline.available_static_friction = incline_contact.static_friction;
    incline.available_dynamic_friction = incline_contact.dynamic_friction;
    incline.rolling_resistance = incline_contact.rolling_resistance;
    incline.required_static_friction =
        incline.gravity_normal_m_s2 > 1.0e-12
            ? input.sphere_inertia_factor /
                  (1.0 + input.sphere_inertia_factor) *
                  std::abs(incline.gravity_tangent_m_s2) /
                  incline.gravity_normal_m_s2
            : std::numeric_limits<double>::infinity();
    incline.no_slip_angle_limit_degrees =
        std::atan(
            incline.available_static_friction *
            (1.0 + input.sphere_inertia_factor) /
            input.sphere_inertia_factor) *
        180.0 / std::numbers::pi;

    const double tangent_magnitude =
        std::abs(incline.gravity_tangent_m_s2);
    const double direction =
        incline.gravity_tangent_m_s2 >= 0.0 ? 1.0 : -1.0;
    if (incline.gravity_outward_m_s2 > 1.0e-9) {
        incline.regime = InclineMotionRegime::Detached;
        incline.acceleration_along_slope_m_s2 =
            incline.gravity_tangent_m_s2;
    } else if (tangent_magnitude <=
               incline.rolling_resistance * incline.gravity_normal_m_s2) {
        incline.regime = InclineMotionRegime::AtRest;
        incline.acceleration_along_slope_m_s2 = 0.0;
    } else if (incline.gravity_normal_m_s2 > 1.0e-12 &&
               incline.available_static_friction + 1.0e-12 >=
                   incline.required_static_friction) {
        incline.regime = InclineMotionRegime::RollingWithoutSlip;
        incline.acceleration_along_slope_m_s2 =
            (incline.gravity_tangent_m_s2 -
             direction * incline.rolling_resistance *
                 incline.gravity_normal_m_s2) /
            (1.0 + input.sphere_inertia_factor);
    } else {
        incline.regime = InclineMotionRegime::Sliding;
        incline.acceleration_along_slope_m_s2 =
            incline.gravity_tangent_m_s2 -
            direction * incline.available_dynamic_friction *
                incline.gravity_normal_m_s2;
    }

    projection.estimated_constraint_solves = saturatedProduct(
        input.estimated_bonds,
        input.constraint_iterations,
        input.material_substeps,
        input.estimated_material_steps);
    projection.runtime_strategy = chooseRuntimeStrategy(
        input,
        impact.predicted_failure,
        projection.estimated_constraint_solves);
    return projection;
}

} // namespace banjo
