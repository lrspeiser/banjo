#include "terrain/GroundWork.hpp"

#include "material/MaterialCatalog.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace banjo::terrain {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kGravity = 9.81;   // the terrain's own (TerrainField.cpp)

double radians(double degrees) { return degrees * kPi / 180.0; }

// Simpson's rule over [a, b] in `n` (even) intervals.
template <typename F> double integrate(F f, double a, double b, int n) {
    if (!(b > a)) return 0.0;
    const double h = (b - a) / n;
    double sum = f(a) + f(b);
    for (int i = 1; i < n; ++i) sum += (i % 2 == 1 ? 4.0 : 2.0) * f(a + i * h);
    return sum * h / 3.0;
}

} // namespace

BearingFactors bearingFactors(double friction_angle_deg) {
    // Rock's 90 degrees is a marker, not a friction angle: the gate answers for
    // rock before this is ever asked, and tan(90) is not a number.
    const double phi = radians(std::clamp(friction_angle_deg, 0.0, 60.0));
    BearingFactors f;
    if (phi < 1.0e-6) {
        // The limit as phi goes to zero: Prandtl's 2 + pi.
        f.nc = 2.0 + kPi;
        f.nq = 1.0;
        f.ngamma = 0.0;
        return f;
    }
    const double t = std::tan(kPi / 4.0 + phi / 2.0);
    f.nq = std::exp(kPi * std::tan(phi)) * t * t;
    f.nc = (f.nq - 1.0) / std::tan(phi);
    f.ngamma = 2.0 * (f.nq + 1.0) * std::tan(phi);
    return f;
}

double passiveCoefficient(double friction_angle_deg) {
    const double t = std::tan(kPi / 4.0 + radians(std::clamp(friction_angle_deg, 0.0, 60.0)) / 2.0);
    return t * t;
}

double pointThicknessAt(const ToolPointShape &point, double depth_m) {
    const double tip = std::min(kTipThicknessM, point.thickness_m);
    const double grown = tip + 2.0 * std::max(0.0, depth_m) * std::tan(radians(0.5 * point.angle_deg));
    return std::min(point.thickness_m, grown);
}

double pointAreaAt(const ToolPointShape &point, double depth_m) {
    return point.width_m * pointThicknessAt(point, depth_m);
}

double bearingPressurePa(const GroundMaterial &ground, const ToolPointShape &point, double depth_m) {
    const BearingFactors f = bearingFactors(ground.friction_angle_deg);
    const double gamma = ground.density_kg_m3 * kGravity;
    const double d = std::max(0.0, depth_m);
    return ground.cohesion_pa * f.nc + gamma * d * f.nq +
           0.5 * gamma * pointThicknessAt(point, d) * f.ngamma;
}

double penetrationResistanceN(const GroundMaterial &ground, const ToolPointShape &point, double depth_m) {
    return bearingPressurePa(ground, point, depth_m) * pointAreaAt(point, depth_m);
}

double meanPenetrationResistanceN(const GroundMaterial &ground, const ToolPointShape &point,
                                  double from_m, double to_m) {
    const double a = std::max(0.0, from_m);
    const double b = std::max(a, to_m);
    if (b - a < 1.0e-9) return penetrationResistanceN(ground, point, a);
    const auto f = [&](double d) { return penetrationResistanceN(ground, point, d); };
    return integrate(f, a, b, 32) / (b - a);
}

double penetrationWorkJ(const GroundMaterial &ground, const ToolPointShape &point, double depth_m) {
    const auto f = [&](double d) { return penetrationResistanceN(ground, point, d); };
    return integrate(f, 0.0, std::max(0.0, depth_m), 64);
}

double depthForWorkM(const GroundMaterial &ground, const ToolPointShape &point, double work_j) {
    if (!(work_j > 0.0)) return 0.0;
    double low = 0.0, high = 0.05;
    while (penetrationWorkJ(ground, point, high) < work_j && high < 20.0) high *= 2.0;
    for (int i = 0; i < 60; ++i) {
        const double mid = 0.5 * (low + high);
        (penetrationWorkJ(ground, point, mid) < work_j ? low : high) = mid;
    }
    return 0.5 * (low + high);
}

double breakoutWidthM(double leading_width_m, double depth_m) {
    return std::max(0.0, leading_width_m) + std::max(0.0, depth_m);
}

double passiveResistanceN(const GroundMaterial &ground, double depth_m, double leading_width_m) {
    const double d = std::max(0.0, depth_m);
    const double kp = passiveCoefficient(ground.friction_angle_deg);
    const double gamma = ground.density_kg_m3 * kGravity;
    const double per_metre = 0.5 * gamma * d * d * kp + 2.0 * ground.cohesion_pa * d * std::sqrt(kp);
    return per_metre * breakoutWidthM(leading_width_m, d);
}

double wedgeLengthM(const GroundMaterial &ground, double depth_m) {
    return std::max(0.0, depth_m) * std::sqrt(passiveCoefficient(ground.friction_angle_deg));
}

double breakoutTravelM(double depth_m) { return kBreakoutTravelShare * std::max(0.0, depth_m); }

double loosenedVolumeM3(const GroundMaterial &ground, double depth_m, double leading_width_m,
                        double sideways_m) {
    const double d = std::max(0.0, depth_m);
    const double onset = breakoutTravelM(d);
    if (!(d > 0.0) || sideways_m < onset) return 0.0;
    const double wedge = 0.5 * d * wedgeLengthM(ground, d);
    return breakoutWidthM(leading_width_m, d) * (wedge + d * (sideways_m - onset));
}

double rockHardnessPa() {
    // The ground's rock IS the engine's stone (TerrainField.hpp: "Rock is the
    // engine's stone -- the concrete preset"), taken from there so the two
    // cannot drift apart.
    static const double hardness = makeReferenceMaterial(MaterialPreset::Concrete, 0).hardness_pa;
    return hardness;
}

GroundVerdict judgeGround(bool rock, double water_depth_m, double tool_hardness_pa,
                          const std::string &tool_material) {
    GroundVerdict out;
    char text[400];
    if (water_depth_m > kWetGroundM) {
        std::snprintf(text, sizeof text,
                      "not supported yet: the ground here is under %.0f mm of water, and wet ground -- "
                      "pore pressure, infiltration, mud -- is not modelled",
                      1000.0 * water_depth_m);
        out.answer = GroundAnswer::NotSupported;
        out.why = text;
        return out;
    }
    if (!rock) return out;
    const double rock_h = rockHardnessPa();
    if (!(tool_hardness_pa > rock_h)) {
        std::snprintf(text, sizeof text,
                      "rock, as hard as the engine's stone (%.0f MPa): a point of %s (%.0f MPa) "
                      "cannot press into it, so the rock stops it and nothing comes loose",
                      rock_h / 1.0e6, tool_material.c_str(), tool_hardness_pa / 1.0e6);
        out.answer = GroundAnswer::TooHard;
        out.why = text;
        return out;
    }
    std::snprintf(text, sizeof text,
                  "not supported yet: %s (%.0f MPa) is harder than the rock (%.0f MPa), but breaking "
                  "rock out of the ground under a point has no law here",
                  tool_material.c_str(), tool_hardness_pa / 1.0e6, rock_h / 1.0e6);
    out.answer = GroundAnswer::NotSupported;
    out.why = text;
    return out;
}

GroundAtDepth groundAt(const TerrainField &field, std::size_t column, double depth_m) {
    const double d = std::max(0.0, depth_m);
    const double sand = field.sand(column);
    const double slid = field.looseSoil(column);
    const double loose = sand + slid;
    GroundAtDepth out;
    if (d < loose) {
        if (sand >= slid) {
            out.material = sandMaterial();
            out.name = "sand";
        } else {
            // Soil that has slid is still soil, and no longer holds together:
            // what the stability check treats it as (TerrainField::relax).
            out.material = soilMaterial();
            out.material.name = "loose soil";
            out.material.cohesion_pa = 0.0;
            out.name = "loose soil";
        }
        return out;
    }
    if (d < loose + field.soil(column)) {
        out.material = soilMaterial();
        out.name = "soil";
        return out;
    }
    out.material = rockMaterial();
    out.name = "rock";
    out.rock = true;
    return out;
}

} // namespace banjo::terrain
