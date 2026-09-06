#pragma once

#include <compare>
#include <cstdint>

namespace banjo {

inline constexpr std::uint32_t kPropertyVariationAlgorithmVersion = 1;

enum class PropertyRangeDomain : std::uint8_t {
    StrictlyPositive,
    Nonnegative,
};

struct BoundedPropertyRange {
    double minimum{};
    double maximum{};
    PropertyRangeDomain domain{PropertyRangeDomain::StrictlyPositive};
};

// Compact reconstruction key. Persist this key and the declared range, rather
// than a generator cursor or a per-tick random stream. The numeric IDs must be
// stable physical identities; display/material names are deliberately absent.
struct PropertyVariationKey {
    std::uint32_t algorithm_version{kPropertyVariationAlgorithmVersion};
    std::uint32_t property_law_version{};
    std::uint64_t material_seed{};
    std::uint64_t object_id{};
    std::uint64_t element_id{};
    std::uint64_t property_id{};

    auto operator<=>(const PropertyVariationKey &) const = default;
};

// Returns one deterministic uniform variate in the closed declared bounds.
// Algorithm v1 uses domain-separated SplitMix64 and the upper 53 hash bits.
// The sample represents fixed intrinsic spatial heterogeneity. Evolving
// stochastic physical state (such as damage) must be persisted separately;
// calibration uncertainty requires separate parameter sets; numerical error
// requires convergence analysis. This function changes no force, mass, energy,
// contact state, or material history.
[[nodiscard]] double sampleBoundedProperty(
    const PropertyVariationKey &key,
    const BoundedPropertyRange &range);

} // namespace banjo
