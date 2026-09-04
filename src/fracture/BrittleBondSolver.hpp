#pragma once

#include "fracture/ActiveMatter.hpp"
#include "fracture/ImpactEvent.hpp"

#include <cstddef>

namespace banjo {

struct BrittleSolverSettings {
    unsigned substeps{2};
    unsigned constraint_iterations{8};
    double floor_height_m{0.0};
    double floor_friction{0.4};
    double impact_internal_energy_fraction{0.18};
    double maximum_internal_energy_j{5000.0};
};

struct MaterialStepStats {
    std::size_t broken_bonds_this_step{};
    std::size_t live_bonds{};
    std::size_t total_broken_bonds{};
    double maximum_tensile_stretch{};
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
        const Vec3 &gravity_m_s2) const;

private:
    void injectInternalImpactPulse(
        ActiveMatter &matter,
        const ImpactEvent &impact,
        const Vec3 &normal_into_target) const;

    BrittleSolverSettings settings_;
};

} // namespace banjo
