#pragma once

#include "fracture/ActiveMatter.hpp"

#include <cstdint>
#include <vector>

namespace banjo {

struct FragmentComponent {
    std::uint32_t id{};
    std::vector<std::uint32_t> node_indices;
};

[[nodiscard]] std::vector<FragmentComponent> findConnectedComponents(
    const ActiveMatter &matter);

} // namespace banjo
