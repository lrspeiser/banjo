#include "material/PropertyVariation.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
namespace {

std::uint64_t splitmix64(std::uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27U)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31U);
}

std::uint64_t combine(
    std::uint64_t hash,
    std::uint64_t field,
    std::uint64_t domain) {
    return splitmix64(
        hash ^ splitmix64(field + domain));
}

void validate(
    const PropertyVariationKey &key,
    const BoundedPropertyRange &range) {
    if (key.algorithm_version != kPropertyVariationAlgorithmVersion) {
        throw std::invalid_argument(
            "unsupported property-variation algorithm version");
    }
    if (key.property_law_version == 0) {
        throw std::invalid_argument(
            "property variation requires a positive law version");
    }
    if (!std::isfinite(range.minimum) ||
        !std::isfinite(range.maximum) ||
        range.maximum < range.minimum) {
        throw std::invalid_argument(
            "property variation requires finite ordered bounds");
    }
    switch (range.domain) {
    case PropertyRangeDomain::StrictlyPositive:
        if (range.minimum <= 0.0) {
            throw std::invalid_argument(
                "positive physical property requires a positive lower bound");
        }
        break;
    case PropertyRangeDomain::Nonnegative:
        if (range.minimum < 0.0) {
            throw std::invalid_argument(
                "nonnegative physical property requires a nonnegative lower bound");
        }
        break;
    default:
        throw std::invalid_argument(
            "unknown property range domain");
    }
}

} // namespace

double sampleBoundedProperty(
    const PropertyVariationKey &key,
    const BoundedPropertyRange &range) {
    validate(key, range);
    if (range.minimum == range.maximum) {
        return range.minimum;
    }

    std::uint64_t hash =
        splitmix64(
            key.material_seed ^
            0x62616e6a6f2d7076ULL);
    hash = combine(hash, key.object_id, 0x6f626a6563742d31ULL);
    hash = combine(hash, key.element_id, 0x656c656d656e7421ULL);
    hash = combine(hash, key.property_id, 0x70726f7065727479ULL);
    hash = combine(
        hash,
        static_cast<std::uint64_t>(key.property_law_version),
        0x6c61772d76657231ULL);
    hash = combine(
        hash,
        static_cast<std::uint64_t>(key.algorithm_version),
        0x616c676f2d766572ULL);

    // The conversion is exact: every integer is at most 2^53-1 and ldexp
    // scales by a power of two. It produces one of 2^53 values in [0,1).
    const double unit =
        std::ldexp(static_cast<double>(hash >> 11U), -53);
    const double sample =
        range.minimum +
        (range.maximum - range.minimum) * unit;
    if (!std::isfinite(sample)) {
        throw std::overflow_error(
            "bounded property sample is not finite");
    }
    return std::clamp(
        sample, range.minimum, range.maximum);
}

} // namespace banjo
