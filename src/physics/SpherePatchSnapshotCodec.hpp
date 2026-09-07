#pragma once

#include "physics/SpherePatchSnapshot.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

namespace banjo {

struct SpherePatchSnapshotCodecLimits {
    std::size_t maximum_bytes{64 * 1024 * 1024};
    std::size_t maximum_nodes{65536};
    std::size_t maximum_tetrahedra{16384};
    std::size_t maximum_materials{64};
};

// Lossless in-memory snapshot transport. The wire format is explicitly
// little-endian and preserves every IEEE-754 double bit pattern. Decoding only
// proves structural integrity; pass the result to SpherePatchWorld::restoreSnapshot
// for compatibility and physical-state validation.
[[nodiscard]] std::vector<std::uint8_t>
encodeSpherePatchSnapshot(const SpherePatchSnapshot &snapshot,
                          const SpherePatchSnapshotCodecLimits &limits = {});

[[nodiscard]] SpherePatchSnapshot
decodeSpherePatchSnapshot(const std::vector<std::uint8_t> &bytes,
                          const SpherePatchSnapshotCodecLimits &limits = {});

} // namespace banjo
