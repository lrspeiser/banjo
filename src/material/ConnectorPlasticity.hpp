#pragma once
#include <array>
#include <cstdint>
#include "material/Material.hpp"
namespace banjo {
// Reduced six-mode perfect plasticity, not continuum J2. Coordinates 0..2 are
// displacement [m], 3..5 log rotation [rad]; conjugate loads are N and N m.
// Independent first-yield bounds do not reproduce a coupled yield surface.
struct ConnectorPlasticParameters {
    std::array<double,6> stiffness{},yield_load{};
};
struct ConnectorPlasticState {
    std::array<double,6> plastic_rest{},accumulated_flow{};
    double plastic_dissipation_j{},return_excess_j{};
    std::uint64_t yielded_updates{};
};
struct ConnectorPlasticUpdate {
    ConnectorPlasticState state;
    double stored_energy_j{},plastic_increment_j{},return_excess_increment_j{};
    bool yielded{};
};
ConnectorPlasticParameters compileConnectorPlasticity(const MaterialDefinition &,
    double length_m,double width_m,double height_m);
ConnectorPlasticUpdate advanceConnectorPlasticity(const ConnectorPlasticParameters &,
    const ConnectorPlasticState &,const std::array<double,6> &total_coordinates);
}
