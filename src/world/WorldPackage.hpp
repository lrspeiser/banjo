#pragma once

#include "world/SparseThermalWorld.hpp"

#include <memory>
#include <string>

namespace banjo {

// Parses and validates the closed banjo-thermal-world-1 SI schema, builds a
// private candidate, and publishes it only after every declaration succeeds.
[[nodiscard]] std::unique_ptr<SparseThermalWorld> loadWorldPackage(
    const std::string &json);

} // namespace banjo
