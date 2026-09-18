#pragma once

#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <string>
#include <vector>

namespace banjo::fastlattice {
// Exact boxes are a distinct physical representation, not a compressed lattice.
// Internal failure, thermal response and attachments are deliberately absent.
struct PreciseRigidBody {
    std::string name;
    MaterialPreset material{};
    std::uint32_t color_rgba{0x9fd3ffffU};
    std::vector<RigidCompoundPart> parts;
    RigidSnapshot initial;
    double mass_kg{};
    Mat3 inertia{};
    Vec3 dimensions_m{};
    std::string definition_json;
};
std::vector<PreciseRigidBody> readPreciseRigidScene(const std::string &json_array);
} // namespace banjo::fastlattice
