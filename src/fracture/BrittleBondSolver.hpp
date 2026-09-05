#pragma once

#include "core/Plane.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/ImpactEvent.hpp"
#include "physics/SphereMaterialContact.hpp"
#include <limits>

#include <cstddef>

namespace banjo {

struct BrittleSolverSettings {
    unsigned substeps{2};
    unsigned constraint_iterations{8};

    // General support surface. Legacy floor fields remain for source compatibility;
    // set use_support_plane=true for tilted worlds.
    bool use_support_plane{};
    SupportPlaneFrame support_plane{};
    double surface_dynamic_friction{0.4};
    double surface_restitution{0.05};
    double floor_height_m{0.0};
    double floor_friction{0.4};

    double surface_static_friction{0.5};
    double support_half_tangent_m{std::numeric_limits<double>::infinity()};
    double support_half_bitangent_m{std::numeric_limits<double>::infinity()};
    // Legacy experimental pulse remains opt-in for isolated calibration tests.
    // The runtime uses zero: contact, not synthetic excitation, drives fracture.
    double impact_internal_energy_fraction{0.0};
    double maximum_internal_energy_j{350.0};
    bool support_enabled{true};
};

struct MaterialStepStats {
    std::size_t broken_bonds_this_step{};
    std::size_t live_bonds{};
    std::size_t total_broken_bonds{};
    std::size_t tensile_failures{};
    std::size_t compressive_failures{};
    std::size_t shear_failures{};
    double maximum_tensile_stretch{};
    double maximum_compressive_strain{};
    double maximum_shear_strain{};
    double kinetic_energy_j{};
    double estimated_elastic_energy_j{};
    double maximum_speed_m_s{};
    double internal_damping_loss_j{};
    Vec3 constraint_angular_momentum_delta_kg_m2_s{};
    double constraint_mechanical_energy_delta_j{};
    double unassigned_bond_removal_energy_j{};
    SphereMaterialContactStats rigid_contact{};
};

class BrittleBondSolver {
public:
    explicit BrittleBondSolver(BrittleSolverSettings settings = {});

    [[nodiscard]] ActiveMatter activate(
        MatterBodyId body_id,
        const LatticeAsset &asset,
        const CompiledBrittleMaterial &material,
        const RigidSnapshot &rigid,
        const ImpactEvent &impact) const;

    [[nodiscard]] MaterialStepStats step(
        ActiveMatter &matter,
        double frame_dt_s,
        const Vec3 &gravity_m_s2,
        CoupledSphereState *sphere = nullptr,
        const SphereMaterialContactSettings &contact = {}) const;

private:
    void injectInternalImpactPulse(
        ActiveMatter &matter,
        const ImpactEvent &impact,
        const Vec3 &normal_into_target) const;

    BrittleSolverSettings settings_;
};

} // namespace banjo
