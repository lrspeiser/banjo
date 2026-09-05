#pragma once
#include "physics/ConservativeStep.hpp"
#include "physics/NormalCompliance.hpp"

namespace banjo {
struct CompliantStepSettings {
    ConservativeStepSettings solver;
    NormalComplianceLaw normal;
    // Declared validity bound on modeled interface compression, not a relaxed
    // tolerance for an unresolved rigid constraint. Must be chosen explicitly.
    double maximum_compression_m{};
    // Optional stricter nonlinear stopping budgets. These bound the physical
    // moments of the equation residual, not differences of rounded state sums.
    // Independent state-based acceptance tolerances remain in solver.
    double maximum_residual_work_j{std::numeric_limits<double>::infinity()};
    double maximum_residual_linear_impulse_kg_m_s{std::numeric_limits<double>::infinity()};
    double maximum_residual_angular_impulse_kg_m2_s{std::numeric_limits<double>::infinity()};
};
enum class CompliantStepFailure { None, Convergence, Geometry, Compression, Balance };
[[nodiscard]] constexpr const char *compliantFailureName(CompliantStepFailure failure) {
    switch (failure) {
    case CompliantStepFailure::None: return "none";
    case CompliantStepFailure::Convergence: return "nonlinear convergence";
    case CompliantStepFailure::Geometry: return "geometry boundary";
    case CompliantStepFailure::Compression: return "compression bound";
    case CompliantStepFailure::Balance: return "energy/momentum balance";
    }
    return "unknown";
}
struct CompliantStepResult {
    ConservativeStepResult balance;
    double contact_energy_before_j{}, contact_energy_after_j{}, contact_damping_loss_j{};
    double maximum_compression_m{};
    CompliantStepFailure failure{CompliantStepFailure::None};
};
// A separately selected law, never a fallback for a failed rigid contact step.
// Elastic nodes, an optional finite sphere, and a static plane share one solve.
// Interface compression stores energy; compression-only damping removes work.
// Failure leaves caller state untouched. No friction/damage or preset calibration.
[[nodiscard]] CompliantStepResult tryCompliantStep(ActiveMatter &matter, double dt_s,
    const CompliantStepSettings &settings, const Vec3 &gravity_m_s2 = {}, CoupledSphereState *sphere = nullptr);
}
