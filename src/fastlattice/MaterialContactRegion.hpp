#pragma once
#include "core/Math.hpp"
#include <cstdint>
#include <functional>
#include <span>
#include <vector>

namespace banjo::fastlattice {
struct MaterialContactRegionSettings {
    double radius_m{}; // Current physical distance from the contacted cell centre.
    std::uint32_t maximum_hops{3},maximum_nodes{64},maximum_edge_visits{4096};
};
struct MaterialContactRegion {
    std::uint32_t seed{},edge_visits{},maximum_hop{},clamped_edge_visits{};
    std::vector<std::uint32_t> nodes; // Seed first, breadth-first, node-ID tie order.
    std::uint64_t target_step{}; // Filled by the authoritative backend.
};
// Immutable canonical bond graph, schedule-order bond IDs. This is selection,
// not a constitutive law, approximation of a remote support or topology cache.
// Aliveness, current position and mobility are read afresh on every selection.
// Bounded reference: <=1024 nodes, <=65536 bonds. Overflow refuses the complete
// region; never truncate a physical support to fit a work budget silently.
class MaterialContactTopology {
public:
    MaterialContactTopology(std::uint32_t nodes,std::span<const std::uint32_t> a,
        std::span<const std::uint32_t> b);
    [[nodiscard]] MaterialContactRegion select(std::uint32_t seed,
        std::span<const std::uint8_t> alive,const MaterialContactRegionSettings &,
        const std::function<Vec3(std::uint32_t)> &position,
        const std::function<bool(std::uint32_t)> &movable) const;
private:
    std::uint32_t node_count_{};
    std::vector<std::uint32_t> a_,b_,offsets_,edges_;
};
}
