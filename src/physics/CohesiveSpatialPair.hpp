#pragma once
#include "physics/CohesiveInterface.hpp"
#include "core/Math.hpp"
#include <cstddef>
namespace banjo {
// Two material points with a central cohesive interaction. Orbital rotation is
// represented; rigid-part intrinsic rotation/off-center attachment is not.
struct CohesiveSpatialPairState {
    Vec3 center_position_m{},separation_m{},velocity_a_m_s{},velocity_b_m_s{};
    CohesiveInterfaceState interface;
};
struct CohesiveSpatialPairResult {
    CohesiveSpatialPairState state;
    Vec3 impulse_on_a_n_s{},momentum_residual_kg_m_s{},angular_momentum_residual_kg_m2_s{};
    double energy_residual_j{};
    std::size_t substeps{};
};
[[nodiscard]] CohesiveSpatialPairResult advanceCohesiveSpatialPair(const CohesiveInterfaceLaw &law,
    double mass_a_kg,double mass_b_kg,double rest_distance_m,const CohesiveSpatialPairState &state,double dt_s,std::size_t max_substeps=4096);
}
