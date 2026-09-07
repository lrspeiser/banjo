#pragma once

#include "physics/SmallStrainPatch.hpp"

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace banjo {
class SpherePatchWorld;

enum class DynamicPatchIntegrator : std::uint8_t {
    SymplecticEuler,
    VelocityVerlet,
};

struct DynamicPatchOptions {
    // Fraction of the conservative central-difference limit. The stiffness
    // estimate is cached because reference geometry and materials are immutable.
    double stability_safety_factor{0.9};
    double maximum_displacement_gradient_norm{0.1};
    double maximum_time_step_s{1.0};
    DynamicPatchIntegrator integrator{DynamicPatchIntegrator::SymplecticEuler};
};

struct DynamicPatchLoad {
    std::vector<Vec3> nodal_forces_n;
    Vec3 gravity_m_s2{};
};

struct DynamicPatchState {
    std::vector<Vec3> velocities_m_s;
    double time_s{};
    double accumulated_external_force_work_j{};
    Vec3 accumulated_support_impulse_n_s{};
    std::uint64_t revision{};
};

struct DynamicPatchReport {
    bool accepted{};
    std::string error;
    double time_step_s{};
    double stable_time_step_limit_s{};
    double stiffness_mass_eigenvalue_bound_s2{};
    double kinetic_energy_j{};
    double stored_free_energy_j{};
    double plastic_dissipation_j{};
    double external_force_work_increment_j{};
    double accumulated_external_force_work_j{};
    Vec3 support_impulse_n_s{};
    Vec3 linear_momentum_kg_m_s{};
    // P(n+1)-P(n)-external impulse-support impulse. Internal-force
    // cancellation is left visible as a raw numerical residual.
    Vec3 linear_momentum_balance_residual_kg_m_s{};
    // Raw ledger residual for this step:
    // Delta(kinetic + stored) + Delta(plastic dissipation) - external work
    // - measured coupled velocity-stage work (zero for uncoupled steps).
    // Symplectic Euler does not make this zero and no conservation claim is made.
    double numerical_energy_balance_residual_j{};
    // Measured free-node velocity exchange in the coupled contact stage.
    double coupling_kinetic_work_j{};
    Vec3 coupling_impulse_n_s{};
    // Conservative work reservation for the candidate constitutive pass.
    // This is not an actual visit count when evaluation rejects partway.
    std::uint64_t reserved_element_visits{};
    double maximum_displacement_gradient_norm{};
};

// Bounded explicit dynamics for a reference-configuration P1 tetrahedral patch.
// It uses lumped nodal mass, stationary component supports, and symplectic Euler
// by default, with optional velocity Verlet. Both retain the same material law.
// The public step is uncoupled. SpherePatchWorld supplies private contact/drift
// stages. No fracture, damping, finite rotation, prescribed support motion,
// thermal coupling or adaptive stepping is provided. Rejected steps commit nothing.
class DynamicPatch {
  public:
    explicit DynamicPatch(PatchDefinition definition, DynamicPatchOptions options = {});

    const SmallStrainPatch &patch() const {
        return patch_;
    }
    const DynamicPatchState &state() const {
        return state_;
    }
    const std::vector<Vec3> &velocitiesMPerS() const {
        return state_.velocities_m_s;
    }
    double stableTimeStepLimitS() const {
        return stable_time_step_limit_s_;
    }
    double stiffnessMassEigenvalueBoundS2() const {
        return eigenvalue_bound_s2_;
    }
    DynamicPatchIntegrator integrator() const {
        return options_.integrator;
    }
    // Sets an initial condition before the first step. Fixed components must
    // be zero; later calls reject rather than injecting unaccounted momentum.
    void setVelocitiesMPerS(const std::vector<Vec3> &velocities_m_s);
    DynamicPatchReport report() const;
    DynamicPatchReport step(double time_step_s, const DynamicPatchLoad &load);

  private:
    friend class SpherePatchWorld;
    struct PreparedRestore {
        PatchState patch;
        DynamicPatchState dynamic;
        std::shared_ptr<const PatchEvaluation> evaluation;
    };
    struct Checkpoint {
        PatchState patch;
        DynamicPatchState dynamic;
        std::shared_ptr<const PatchEvaluation> evaluation;
    };
    Checkpoint checkpoint() const;
    void restoreCheckpoint(Checkpoint saved) noexcept;
    [[nodiscard]] PreparedRestore prepareRestore(const PatchState &patch,
                                                 const DynamicPatchState &dynamic,
                                                 const PatchEvaluation &evaluation) const;
    void commitRestore(PreparedRestore prepared) noexcept;
    DynamicPatchReport
    stepImpl(double time_step_s, const DynamicPatchLoad &load,
             const std::function<void(std::vector<Vec3> &, std::vector<Vec3> &)> &velocity_stage,
             const std::function<void(const std::vector<Vec3> &, const DynamicPatchReport &)>
                 &before_commit,
             const std::function<void(std::vector<Vec3> &, const std::vector<Vec3> &)>
                 &final_velocity_stage);
    double kineticEnergyJ(const std::vector<Vec3> &velocities) const;
    Vec3 linearMomentum(const std::vector<Vec3> &velocities) const;
    void compileStabilityBound();

    SmallStrainPatch patch_;
    DynamicPatchOptions options_;
    DynamicPatchState state_;
    std::shared_ptr<const PatchEvaluation> accepted_evaluation_;
    double eigenvalue_bound_s2_{};
    double stable_time_step_limit_s_{};
};

} // namespace banjo
