#pragma once
#include "core/Math.hpp"
#include "material/SmallStrainLaw.hpp"
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace banjo {
struct PatchMaterial {
    SmallStrainLaw law;
    double density_kg_m3{};
};
struct PatchTet {
    std::array<unsigned,4> nodes{};
    unsigned material{};
};
struct PatchDefinition {
    std::vector<Vec3> reference_positions_m;
    std::vector<PatchTet> elements;
    std::vector<PatchMaterial> materials;
    std::vector<std::array<bool,3>> fixed_components;
};
struct PatchLoad {
    std::vector<Vec3> nodal_forces_n;
    // Used only on fixed components; free entries must be zero.
    std::vector<Vec3> prescribed_displacements_m;
};
struct PatchSolveOptions {
    unsigned maximum_newton_iterations{30};
    unsigned maximum_cg_iterations{1024};
    unsigned maximum_line_search_steps{20};
    std::uint64_t maximum_element_visits{4000000};
    double relative_force_tolerance{1e-8};
    double absolute_force_tolerance_n{1e-7};
    // Bounds rotations as well as strain: small strain is not a finite-rotation law.
    double maximum_displacement_gradient_norm{.1};
};
struct PatchState {
    std::vector<Vec3> displacements_m;
    std::vector<J2State> material_points;
    std::vector<Vec3> last_nodal_forces_n;
    double accumulated_trapezoidal_external_work_j{};
    double accumulated_backward_euler_external_work_j{};
    std::uint64_t revision{};
};
struct PatchEvaluation {
    std::vector<Vec3> internal_forces_n;
    std::vector<SmallStrainResponse> responses;
    double stored_free_energy_j{};
    double plastic_dissipation_j{};
    double backward_euler_work_excess_j{};
    double maximum_displacement_gradient_norm{};
};
struct PatchSolveResult {
    bool accepted{};
    std::string error;
    unsigned newton_iterations{},cg_iterations{},line_search_trials{};
    std::uint64_t element_visits{};
    double wall_ms{},free_force_residual_n{},force_tolerance_n{};
    double stored_free_energy_j{},plastic_dissipation_j{};
    double trapezoidal_external_work_increment_j{};
    double backward_euler_external_work_increment_j{};
    double stored_free_energy_increment_j{},plastic_dissipation_increment_j{};
    double trapezoidal_work_residual_j{},backward_euler_balance_residual_j{};
    double constitutive_backward_euler_excess_j{};
    double maximum_displacement_gradient_norm{};
    Vec3 applied_force_n{},support_reaction_n{},reference_moment_residual_n_m{};
    std::vector<Vec3> reactions_n;
};

// A bounded, quasistatic, reference-configuration P1 tetrahedral patch.
// No inertia, contact, fracture, finite rotations or thermal coupling. Newton
// trials always integrate from the last accepted history; only convergence
// commits displacement and plastic state together. Failure leaves state intact.
// Imported meshes must be certified nonoverlapping by their producer. Local
// topology/orientation checks do not prove global geometric nonintersection.
// makeTetrahedralBrick provides a conforming construction for this reference.
class SmallStrainPatch {
public:
    explicit SmallStrainPatch(PatchDefinition definition);
    const PatchDefinition &definition() const { return definition_; }
    const PatchState &state() const { return state_; }
    const std::vector<double> &nodalMassesKg() const { return nodal_masses_; }
    const std::vector<std::array<unsigned,3>> &boundaryTriangles() const { return boundary_; }
    double referenceVolumeM3() const { return volume_; }
    double massKg() const { return mass_; }
    std::vector<Vec3> positionsM() const;
    PatchEvaluation evaluate(const std::vector<Vec3> &displacements_m,
        double maximum_gradient_norm=.1) const;
    PatchSolveResult solveLoad(const PatchLoad &load,const PatchSolveOptions &options={});
    // Full displacement/material/load state, not an initial package. Checks
    // geometry/strain consistency and free equilibrium before replacing state.
    void restoreState(const PatchState &candidate,double force_tolerance_n=1e-5,
        double maximum_gradient_norm=.1);
private:
    struct TetData { std::array<Vec3,4> gradients; double volume{}; };
    PatchDefinition definition_;
    PatchState state_;
    std::vector<TetData> geometry_;
    std::vector<double> nodal_masses_;
    std::vector<std::array<unsigned,3>> boundary_;
    double volume_{},mass_{};
    PatchEvaluation evaluateFrom(const PatchState &base,const std::vector<Vec3> &displacements,
        double maximum_gradient_norm) const;
};

// Structured brick split into six conforming positive-volume tetrahedra/cell.
// Resolution is cells in x,y,z. Fixed constraints default to false.
PatchDefinition makeTetrahedralBrick(Vec3 dimensions_m,std::array<unsigned,3> resolution,
    PatchMaterial material);
} // namespace banjo
