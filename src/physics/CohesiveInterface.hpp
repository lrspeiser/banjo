#pragma once

namespace banjo {
// Explicit normal-opening cohesive law with optional reversible compression.
// No shear, friction, bulk plasticity, thermal conversion or name-based rules.
struct CohesiveInterfaceLaw {
    double stiffness_pa_per_m{};
    double strength_pa{};
    double fracture_energy_j_m2{};
    double area_m2{};
    // Optional reversible compression stiffness. Zero retains tension-only law.
    double compression_stiffness_pa_per_m{};
};
struct CohesiveInterfaceState {
    double opening_m{};
    double maximum_opening_m{};
};
struct CohesiveInterfaceResponse {
    double traction_pa{},force_n{},stored_energy_j{},dissipated_energy_j{};
    double damage{};
    bool separated{};
};
struct CohesiveInterfaceIncrement {
    CohesiveInterfaceState state;
    CohesiveInterfaceResponse response;
    double opening_work_j{};
    double dissipated_increment_j{};
    double balance_residual_j{};
    // Integral of force over this monotone opening increment divided by its
    // signed displacement. It is not an instantaneous endpoint force.
    double work_conjugate_force_n{};
};
[[nodiscard]] double cohesiveDamageOpening(const CohesiveInterfaceLaw &law);
[[nodiscard]] double cohesiveSeparationOpening(const CohesiveInterfaceLaw &law);
[[nodiscard]] CohesiveInterfaceResponse evaluateCohesiveInterface(const CohesiveInterfaceLaw &law,const CohesiveInterfaceState &state);
[[nodiscard]] CohesiveInterfaceIncrement advanceCohesiveInterface(const CohesiveInterfaceLaw &law,const CohesiveInterfaceState &state,double opening_m);
}
