#pragma once
#include "physics/CohesiveInterface.hpp"
#include <cstddef>

namespace banjo {
// Collinear finite-mass reference. Masses must come from the caller's matter.
// Opening is a relative coordinate; COM translation is independent of it.
// No rotation, compression contact, gravity or other external force is modeled.
struct CohesivePairState {
    double center_position_m{};
    double velocity_a_m_s{},velocity_b_m_s{};
    CohesiveInterfaceState interface;
};
struct CohesivePairResult {
    CohesivePairState state;
    double impulse_on_a_n_s{},impulse_on_b_n_s{};
    double energy_residual_j{},momentum_residual_kg_m_s{};
    double dissipated_increment_j{};
    std::size_t substeps{};
};
[[nodiscard]] CohesivePairResult advanceCohesivePair(const CohesiveInterfaceLaw &law,
    double mass_a_kg,double mass_b_kg,const CohesivePairState &state,double dt_s,std::size_t max_substeps=4096);
}
