#pragma once
#include "physics/CohesiveInterfaceKernel.hpp"
namespace banjo {
[[nodiscard]] double cohesiveDamageOpening(const CohesiveInterfaceLaw &law);
[[nodiscard]] double cohesiveSeparationOpening(const CohesiveInterfaceLaw &law);
[[nodiscard]] CohesiveInterfaceResponse evaluateCohesiveInterface(const CohesiveInterfaceLaw &law,const CohesiveInterfaceState &state);
[[nodiscard]] CohesiveInterfaceIncrement advanceCohesiveInterface(const CohesiveInterfaceLaw &law,const CohesiveInterfaceState &state,double opening_m);
}
