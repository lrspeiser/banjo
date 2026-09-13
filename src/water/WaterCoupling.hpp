#pragma once

// What the water does to bodies, and what bodies do to the water -- by one path.
//
// PRESSURE. Every body is a closed surface of small planar patches (a box's six
// faces cut into squares, a ball as a fine polyhedron of its own volume, a
// broken piece as the exposed faces of its cells). Each patch is clipped at the
// local water surface and the hydrostatic pressure rho g (eta - y) is
// integrated over what is under it -- exactly, because pressure is linear over
// a flat patch -- and pushed along the patch's inward normal. Summed over a
// closed body in still water that is Archimedes, rho g V_displaced, upward,
// through the centre of buoyancy; nothing says "this floats". An oak log
// (700 kg/m^3) comes to rest with 70% of itself under water because that is
// where the pressure on its underside balances its weight, and an iron block
// (7870) never finds such a place. And because the surface is sampled patch by
// patch, a block with water piled up on one side and little on the other is
// pushed downstream by the difference: that is a dam's load, from the same
// integral as a log's buoyancy.
//
// DRAG. Water moving past a patch presses on it: on a face the flow comes at,
// 1/2 rho Cd v_n^2 over the patch; along every wetted face, skin friction
// 1/2 rho Cf |v_t| v_t. The velocity is the water's RELATIVE to that point of
// the body, so a log carried along at the speed of the stream feels nothing,
// and one held against it feels the whole stream. The coefficients are
// DECLARED (Cd 1.0, a bluff face; Cf 0.01), not fitted to anything.
//
// ONE ACCOUNTING PATH. The drag a body receives is taken from the water that
// gave it: each patch's drag is returned, reversed, as momentum to the column
// it was sampled from. The hydrostatic part has no such reaction in a
// shallow-water model -- a floating body's weight is carried by the pressure on
// the bed under the column, which the model does not track -- and that is
// declared rather than invented.
//
// OBSTACLES. A body that rests on the bed and would not float (denser than
// water, or anchored scenery) is, to the water, part of the bed: a row of
// stone blocks across a channel raises the bed there to their tops and the
// water has to rise over them. A gap under a block smaller than the grid can
// represent is treated as sealed; a larger one lets water under.
#include "core/Math.hpp"
#include "water/ShallowWater.hpp"

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

namespace banjo::water {

// A body as the water sees it: shape, where it is, how it moves.
struct BodyInWater {
    std::size_t index{};              // the host's own index, handed back
    std::uint64_t body_id{};          // the rigid world's id for it
    std::string name;
    double volume_m3{};               // its matter, for its weight
    enum class Shape { Box, Sphere, Cells } shape{Shape::Box};
    Vec3 dimensions_m{};              // a box's extents; a ball's diameter in x
    // For Cells: the centres of its cells in the body's frame, from its centre
    // of mass, each a cube of cell_m.
    const std::vector<Vec3> *cells_local_m{};
    double cell_m{};
    Vec3 com_m{};
    Quat orientation{};
    Vec3 velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
    double mass_kg{};
    double density_kg_m3{};
    bool anchored{};
    bool held{};
    bool awake{true};
};

struct BodyForce {
    std::size_t index{};
    Vec3 force_n{};                   // everything, world frame
    Vec3 torque_n_m{};                // about the centre of mass
    Vec3 pressure_n{};                // the hydrostatic part
    Vec3 drag_n{};                    // the part from relative motion
    double submerged_m3{};            // volume under the local surface
    double wetted_m2{};
    double drag_power_w{};            // drag force . body velocity, summed by patch
};

struct CouplingSettings {
    double drag_coefficient{1.0};
    double skin_coefficient{0.01};
    double patch_m{0.125};            // no patch larger than this
    double seal_gap_m{0.1};           // a gap under a block this small is sealed
    double wet_m{1.0e-3};             // thinner than this is not water to a body
};

// Drag handed back to the water, one entry per patch that felt it.
struct Reaction {
    std::size_t cell{};
    double fx_n{};
    double fz_n{};
};

class WaterCoupling {
public:
    // The water's forces on each body, from the water as it stands now.
    // Bodies not touching water are left out. `reactions` receives the drag
    // to give back to the water, reversed, once the step that used these
    // forces has been taken.
    std::vector<BodyForce> forces(const ShallowWater &water, const std::vector<BodyInWater> &bodies,
                                  std::vector<Reaction> &reactions);
    // The solid tops that bodies resting on the bed put under the water, one
    // per cell, -infinity where there is none.
    std::vector<double> obstacleTops(const ShallowWater &water, const std::vector<BodyInWater> &bodies) const;
    [[nodiscard]] const CouplingSettings &settings() const { return settings_; }
    void setSettings(const CouplingSettings &settings) { settings_ = settings; patches_.clear(); }
    // Is this body something the water treats as part of the bed?
    [[nodiscard]] static bool isObstacle(const BodyInWater &body, double water_density);

    // One planar patch of a body's surface, in its own frame.
    struct Patch {
        Vec3 corner[4];
        Vec3 normal;
        double area{};
    };
    // A body's surface as patches: exposed for tests.
    [[nodiscard]] const std::vector<Patch> &patchesOf(const BodyInWater &body);

private:
    CouplingSettings settings_{};
    std::unordered_map<std::string, std::vector<Patch>> patches_;
};

} // namespace banjo::water
