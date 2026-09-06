#pragma once
#include "physics/SmallStrainPatch.hpp"

namespace banjo {
enum class PatchPressureProfile { Uniform, Smooth };
struct PatchPressure {
    Vec3 center_m;
    Vec3 axis_u{1,0,0};
    Vec3 axis_v{0,0,-1};
    double half_width_m{.01},half_height_m{.01},peak_pressure_pa{};
    PatchPressureProfile profile{PatchPressureProfile::Uniform};
};
struct PatchPressureLoad {
    PatchLoad load;
    double loaded_area_m2{},weighted_area_m2{};
    Vec3 resultant_force_n{},reference_moment_n_m{};
    std::uint64_t quadrature_points{};
};

// Consistent nodal forces for a rectangular pressure footprint on planar
// outward boundary triangles. The axes are orthonormal; traction points along
// -cross(axis_u,axis_v). Triangles are clipped geometrically before integration,
// so a boundary through a face does not change the requested footprint.
// Smooth pressure is p_peak*(1-(u/a)^2)^2*(1-(v/b)^2)^2 inside the rectangle.
// Partial surface coverage is reported, not filled with invented matter.
// Preserves the current fixed displacement components. Does not mutate state,
// apply a load, introduce contact, or infer pressure from an impact.
PatchPressureLoad makePatchPressureLoad(const SmallStrainPatch &patch,
    const PatchPressure &pressure);
} // namespace banjo
