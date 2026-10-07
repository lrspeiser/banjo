#pragma once
#include "core/Math.hpp"
#include "core/Types.hpp"
#include <span>

namespace banjo { class JoltWorld; }
namespace banjo::fastlattice {

// Static entry-pose observation against the actual native collision shapes.
// Not a swept-path certificate, material-contact solve or promised removal.
struct NativeToolEntryClearance {
    bool checked{}, clear{}, ground{};
    unsigned parts_checked{};
    MatterBodyId tool_part{}, blocking_body{};
    Vec3 witness_m{};
    double overlap_m{};
};

// Keep the current fixed assembly's relative transforms, align its held grip
// to the declared entry pose and query without writing poses/velocities/shapes.
// Internal assembly pairs are ignored, while actors/other products/terrain stay.
[[nodiscard]] NativeToolEntryClearance inspectToolEntry(
    const JoltWorld &world, std::span<const MatterBodyId> assembly,
    MatterBodyId held, Vec3 grip_local_m, Vec3 desired_grip_m, Quat desired_facing,
    double tolerance_m = .003);
}
