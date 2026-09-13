#pragma once

// What the ground does about the point of a tool: ground-work-v1.
//
// A DECLARED, reduced-order model, written down in docs/ground-work.md. Every
// number it gives comes from the ground's own declared materials
// (terrain/TerrainField.hpp: a density, a friction angle and a cohesion) and
// the point's own declared shape -- never from what the tool is called, and
// never from anything a player knows. Nothing here takes a player, a level or
// a technique, and nothing can.
//
// Three things are said here, each a textbook formula for dry ground, none of
// them calibrated against a measurement of any soil or any tool:
//
//   1. How hard the ground pushes back on a point driven into it: the bearing
//      capacity of a strip footing under the point's thin side (Terzaghi 1943,
//      with Prandtl's N_c and N_q and Vesic's N_gamma, no shape or depth
//      factors), times the point's cross-section at the depth it has reached.
//
//          q(d) = c N_c  +  gamma d N_q  +  1/2 gamma t(d) N_gamma
//          F(d) = q(d) w t(d)
//
//   2. How hard it resists an embedded point pushed sideways -- a pry: Rankine's
//      passive earth pressure, with Bell's term for cohesion, over the embedded
//      depth and across the point's leading width plus that depth.
//
//          P(d) = (1/2 gamma d^2 K_p  +  2 c d sqrt(K_p)) (b + d),   K_p = tan^2(45 + phi/2)
//
//   3. What comes loose when it gives. Once the point has gone a tenth of its
//      depth sideways, the wedge ahead of it has failed -- from the point's
//      depth up to the surface along Rankine's passive plane, 45 - phi/2 from
//      the horizontal -- and whatever it sweeps through after that goes too.
//
//          V = (b + d) (1/2 d L_f  +  d (s - d/10)),   L_f = d tan(45 + phi/2),   s >= d/10
//
// And one gate, the one the cutting model draws (docs/cutting-model.md): a
// point can only press as hard as its own material's indentation hardness, so
// ground at least as hard as the point stops it. Bare rock here is the
// engine's stone, the concrete preset (100 MPa); oak is 35 MPa, iron 1.5 GPa.
// A point harder than the rock is not guessed at: breaking rock out of the
// ground has no law here, and the answer says so.
//
// What it leaves out -- friction on the embedded faces, rate effects, wet
// ground, layered ground under one point, the crescents to the sides of a
// narrow point beyond the declared (b + d) -- is listed in docs/ground-work.md.
#include "terrain/TerrainField.hpp"

#include <cstdint>
#include <string>

namespace banjo::terrain {

// The model's name and version, carried with every answer it gives.
inline constexpr const char *kGroundWorkModel = "ground-work-v1";

// The working end of a tool. `width_m` runs across the edge the point comes to
// (a chisel point's edge, a round point's diameter); the point thickens from
// kTipThicknessM at its end to `thickness_m`, at the included angle
// `angle_deg`, within the last `length_m` of the tool -- which is how deep it
// can go before the rest of the tool meets the ground.
struct ToolPointShape {
    double width_m{0.04};
    double thickness_m{0.04};
    double angle_deg{30.0};
    double length_m{0.15};
};
// How thick a point is where it starts. A point made by hand is not a razor.
inline constexpr double kTipThicknessM = 0.002;
// How far sideways, as a share of its depth, a point moves before the ground
// ahead of it has failed. DECLARED: passive failure takes a wall movement of
// a few per cent of its height in dense ground and around ten in loose.
inline constexpr double kBreakoutTravelShare = 0.1;
// Water deeper than this over the ground makes it wet ground, not modelled.
inline constexpr double kWetGroundM = 0.005;

struct BearingFactors {
    double nc{}, nq{}, ngamma{};
};
// Prandtl's N_c and N_q, Vesic's N_gamma, for a friction angle in degrees.
[[nodiscard]] BearingFactors bearingFactors(double friction_angle_deg);
// Rankine's passive coefficient tan^2(45 + phi/2).
[[nodiscard]] double passiveCoefficient(double friction_angle_deg);

// The point's thickness and cross-section `depth_m` back from its end.
[[nodiscard]] double pointThicknessAt(const ToolPointShape &point, double depth_m);
[[nodiscard]] double pointAreaAt(const ToolPointShape &point, double depth_m);
// q(d), Pa, and F(d) = q(d) A(d), N.
[[nodiscard]] double bearingPressurePa(const GroundMaterial &ground, const ToolPointShape &point,
                                       double depth_m);
[[nodiscard]] double penetrationResistanceN(const GroundMaterial &ground, const ToolPointShape &point,
                                            double depth_m);
// The mean of F over a stretch of depth: what the ground takes, on average,
// from a point going from `from_m` to `to_m`.
[[nodiscard]] double meanPenetrationResistanceN(const GroundMaterial &ground, const ToolPointShape &point,
                                                double from_m, double to_m);
// The work of driving the point from the surface to `depth_m`, J.
[[nodiscard]] double penetrationWorkJ(const GroundMaterial &ground, const ToolPointShape &point,
                                      double depth_m);
// The depth that much work drives it to: the inverse of penetrationWorkJ.
[[nodiscard]] double depthForWorkM(const GroundMaterial &ground, const ToolPointShape &point,
                                   double work_j);
// The width of ground an embedded point pushes ahead of it, b + d.
[[nodiscard]] double breakoutWidthM(double leading_width_m, double depth_m);
// P(d), N: the passive resistance to the embedded point moving sideways.
[[nodiscard]] double passiveResistanceN(const GroundMaterial &ground, double depth_m,
                                        double leading_width_m);
// L_f: how far ahead of the point the failed wedge reaches the surface.
[[nodiscard]] double wedgeLengthM(const GroundMaterial &ground, double depth_m);
// How far sideways the point goes before the wedge has failed.
[[nodiscard]] double breakoutTravelM(double depth_m);
// V: what has come loose, m^3, once a point `depth_m` in has gone `sideways_m`.
[[nodiscard]] double loosenedVolumeM3(const GroundMaterial &ground, double depth_m,
                                      double leading_width_m, double sideways_m);

// What the ground at the point is to it.
enum class GroundAnswer : std::uint8_t {
    Penetrable = 0,     // soil or sand the point goes into
    TooHard = 1,        // ground at least as hard as the point: it stops it
    NotSupported = 2,   // a regime the model does not cover, said and never guessed
};
struct GroundVerdict {
    GroundAnswer answer{GroundAnswer::Penetrable};
    std::string why;
};
// The rock's indentation hardness: the engine's stone's.
[[nodiscard]] double rockHardnessPa();
// `rock`: the point meets rock (bare, or under the soil it has gone through).
[[nodiscard]] GroundVerdict judgeGround(bool rock, double water_depth_m, double tool_hardness_pa,
                                        const std::string &tool_material);

// The ground `depth_m` below the top of a column: the loose layer (sand, or
// soil that has slid and lost its cohesion), native soil, or rock -- with the
// material that layer answers with.
struct GroundAtDepth {
    GroundMaterial material;
    std::string name;   // "sand", "loose soil", "soil", "rock"
    bool rock{};
};
[[nodiscard]] GroundAtDepth groundAt(const TerrainField &field, std::size_t column, double depth_m);

} // namespace banjo::terrain
