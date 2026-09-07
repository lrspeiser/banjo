#pragma once

#include "physics/SpherePatchWorld.hpp"

#include <cstdint>

namespace banjo {

// Complete in-memory semantic checkpoint for exact continuation of one
// SpherePatchWorld. This is not yet a stable binary or persistence schema.
struct SpherePatchSnapshot {
    std::uint32_t version{1};
    PatchDefinition definition;
    DynamicPatchOptions dynamics;
    PatchContactOptions contact;
    PatchState patch;
    DynamicPatchState dynamic;
    PatchEvaluation accepted_evaluation;
    PatchSphere sphere;
};

} // namespace banjo
