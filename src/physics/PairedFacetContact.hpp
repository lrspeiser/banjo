#pragma once

#include "core/Math.hpp"

#include <array>

namespace banjo {

struct PairedFacetContactPoint {
    bool compressed{};
    bool projections_in_footprint{};
    std::array<double, 3> projection_a_on_b_barycentric{};
    std::array<double, 3> projection_b_on_a_barycentric{};
    double minimum_barycentric_margin{};
};

struct PairedFacetContactResult {
    bool resolved{};
    Vec3 midsurface_winding_normal{};
    std::array<PairedFacetContactPoint, 3> integration_points{};
    unsigned compressed_points{};
    unsigned valid_footprint_points{};
    unsigned projection_work{};
};

// Tests whether compressive paired-facet quadrature points remain within both
// finite triangle footprints. Geometry outside either footprint is reported as
// invalid contact. This pure query applies no forces, energy, or separation.
[[nodiscard]] PairedFacetContactResult pairedFacetCompressionFootprint(
    const std::array<Vec3, 3> &current_a_m,
    const std::array<Vec3, 3> &current_b_m,
    double barycentric_tolerance = 1.e-10);

} // namespace banjo
