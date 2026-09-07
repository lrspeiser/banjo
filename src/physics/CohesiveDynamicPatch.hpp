#pragma once

#include "physics/CohesiveAssembly.hpp"
#include "physics/DynamicPatch.hpp"
#include "physics/CorotatedTet.hpp"
#include "physics/CorotatedCohesiveFacet.hpp"

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace banjo {
class CohesiveSphereWorld;
class CohesiveDynamicPatchTestAccess;

enum class CohesiveKinematics { SmallDisplacement, Corotated };

struct CohesiveDynamicPatchOptions {
    // Central-difference bound includes the largest elastic, compression, and
    // descending cohesive tangent at the reference configuration. For the
    // corotated model this is only an initial trial cap, not a certified bound
    // on the evolving geometric Hessian. Both paths require work/refinement.
    double stability_safety_factor{0.9};
    double maximum_time_step_s{1.e-3};
    double maximum_displacement_gradient_norm{0.1};
    double maximum_absolute_energy_residual_j{1.e-6};
    std::uint64_t maximum_tet_evaluations{65536};
    CohesiveAssemblyLimits cohesive{};
    // Explicit alternative potential and objective facet history. The legacy
    // model and its displacement-gradient gate are unchanged by default.
    CohesiveKinematics kinematics{CohesiveKinematics::SmallDisplacement};
    double minimum_deformation_jacobian{0.1};
    double maximum_deformation_gradient_norm{4.0};
    CorotatedCohesiveFacetOptions objective_facets{};
};

struct CohesiveDynamicPatchState {
    std::vector<Vec3> displacements_m;
    std::vector<Vec3> velocities_m_s;
    std::vector<CohesiveFacetState> facet_states;
    std::vector<CorotatedCohesiveFacetState> corotated_facet_states;
    std::vector<bool> fully_separated_facets;
    FractureSeparation separation;
    double time_s{};
    double accumulated_external_work_j{};
    std::uint64_t revision{};
};

struct CohesiveContactHandoff {
    std::size_t facet_index{};
    // Energy in the rejected candidate, never committed or silently discarded.
    double retained_compression_energy_j{};
};

struct CohesiveDynamicPatchReport {
    bool accepted{};
    std::string error;
    std::optional<CohesiveContactHandoff> contact_handoff_required;
    double time_step_s{};
    double stable_time_step_limit_s{};
    double kinetic_energy_j{};
    double bulk_stored_energy_j{};
    double cohesive_stored_energy_j{};
    double plastic_dissipation_j{};
    double fracture_dissipation_j{};
    double fracture_dissipation_increment_j{};
    double external_work_increment_j{};
    double accumulated_external_work_j{};
    double numerical_energy_residual_j{};
    Vec3 linear_momentum_kg_m_s{};
    Vec3 momentum_residual_kg_m_s{};
    Vec3 support_impulse_n_s{};
    double coupling_kinetic_work_j{};
    Vec3 coupling_impulse_n_s{};
    std::uint64_t tet_evaluations{};
    std::uint64_t facet_evaluations{};
    std::uint64_t nodal_scatters{};
    std::uint64_t polar_iterations{};
    std::uint64_t facet_derivative_evaluations{};
    double maximum_elastic_stretch_norm{};
    unsigned fully_separated_facets{};
};

// Bounded transactional velocity-Verlet reference for an intrinsic cohesive
// tetrahedral patch. Bulk and facets advance on the same clock. This first
// adapter accepts isotropic/orthotropic small-displacement elastic bulk, or an
// explicitly selected isotropic corotated potential with objective facets.
// No fragment self-contact, damping, or rigid-fragment handoff is implied.
class CohesiveDynamicPatch {
  public:
    CohesiveDynamicPatch(PatchDefinition definition,
                         std::vector<CohesiveFacetLaw> facet_laws,
                         CohesiveDynamicPatchOptions options = {});

    const FractureTopology &topology() const { return topology_; }
    const CohesiveDynamicPatchState &state() const { return state_; }
    double stableTimeStepLimitS() const { return stable_time_step_limit_s_; }
    double massKg() const { return topology_.mass_kg; }
    CohesiveKinematics kinematics() const { return options_.kinematics; }
    const std::vector<double> &nodalMassesKg() const {
        return topology_.local_nodal_masses_kg;
    }
    const std::vector<std::array<bool, 3>> &fixedComponents() const {
        return topology_.duplicated_definition.fixed_components;
    }
    const std::vector<CohesiveFacetState> &acceptedFacetStates() const {
        return state_.facet_states;
    }
    [[nodiscard]] std::vector<Vec3> positionsM() const;

    void setVelocitiesMPerS(const std::vector<Vec3> &velocities_m_s);
    [[nodiscard]] CohesiveDynamicPatchReport report() const;
    [[nodiscard]] CohesiveDynamicPatchReport step(
        double dt_s, const std::vector<Vec3> &nodal_forces_n,
        Vec3 gravity_m_s2 = {});

  private:
    friend class CohesiveSphereWorld;
    friend class CohesiveDynamicPatchTestAccess;
    struct CombinedEvaluation;
    [[nodiscard]] CombinedEvaluation evaluate(
        const std::vector<Vec3> &displacements_m,
        const std::vector<CohesiveFacetState> &facet_states,
        const std::vector<CorotatedCohesiveFacetState> &objective_states) const;
    [[nodiscard]] double kineticEnergyJ(const std::vector<Vec3> &velocities) const;
    [[nodiscard]] Vec3 momentum(const std::vector<Vec3> &velocities) const;
    [[nodiscard]] CohesiveDynamicPatchReport stepImpl(
        double dt_s, const std::vector<Vec3> &nodal_forces_n, Vec3 gravity_m_s2,
        const std::function<void(std::vector<Vec3> &, std::vector<Vec3> &)> &drift_stage,
        const std::function<void(std::vector<Vec3> &, const CohesiveDynamicPatchState &)>
            &final_velocity_stage,
        const std::function<void(const CohesiveDynamicPatchState &,
                                 const CohesiveDynamicPatchReport &)> &before_commit);

    FractureTopology topology_;
    std::vector<CohesiveFacetLaw> facet_laws_;
    CohesiveDynamicPatchOptions options_;
    std::vector<std::unique_ptr<SmallStrainPatch>> tet_patches_;
    std::vector<CorotatedTetLaw> corotated_laws_;
    CohesiveDynamicPatchState state_;
    std::shared_ptr<const CombinedEvaluation> accepted_evaluation_;
    double stable_time_step_limit_s_{};
};

} // namespace banjo
