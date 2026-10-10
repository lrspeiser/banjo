#pragma once

// Water that falls: what a spout pours before it reaches the river.
//
// The river (ShallowWater) is depth-averaged: it has no water in the air, so on
// its own nothing can be poured onto a wheel from above. This carries poured
// water as parcels, each a small fixed volume of it, from the spout until it
// reaches the river or the ground again:
//
//  - between parcels, weakly compressible SPH, the same law as the fluid
//    wheel experiment (src/platform/WaterWheelWorld.cpp): a Wendland C2
//    kernel, p = c^2 max(rho - rho0, 0), central pressure and viscous pair
//    forces, so parcels push each other apart and do not pile like beads;
//  - against bodies, contact that is frictionless and does not bounce: a
//    parcel moving into a surface loses its speed into that surface, keeps
//    its speed along it, and gives the body the equal and opposite impulse at
//    the point of contact. That is how the falling water's weight and its
//    momentum reach a paddle;
//  - where its underside reaches the river's surface (or the ground, where
//    the river is dry), a parcel joins the river: its volume into that
//    column, its horizontal momentum into that column's water.
//
// Every parcel is the same volume, so the ledger closes by counting:
//
//     poured = landed + ran off + in the air
//
// "Ran off" is water that came down outside the river's grid. Each step is
// worked out first (plan) from the bodies as they stand, its pushes applied
// to them inside the host's reversible step, and kept (accept) only if that
// step is kept: a step taken back pours nothing.
//
// Not modelled: surface tension, splashing into spray, water soaking into
// anything, a boundary density correction at solid walls, and water standing
// in a body (a bucket): water held by a body is parcels resting on it. The
// sound speed is reduced (20 m/s) as in the wheel experiment, so the water is
// slightly compressible.

#include "core/Math.hpp"

#include <cstdint>
#include <functional>
#include <limits>
#include <optional>
#include <string>
#include <vector>

namespace banjo::water {

struct Spout {
    std::string name;
    Vec3 at_m{};          // the mouth
    Vec3 direction{};     // unit, the way the water leaves
    double speed_m_s{};   // how fast it leaves
    double discharge_m3_s{};
    double from_s{0.0};
    double until_s{std::numeric_limits<double>::infinity()};
};

// What a parcel finds near it: a body's surface (from the host's own shapes).
struct NearSurface {
    bool named{};               // false for the ground
    std::uint64_t body{};
    double depth_m{};           // into it; negative is the gap
    Vec3 point_m{};
    Vec3 normal{};              // out of the body, towards the parcel
    Vec3 velocity_m_s{};        // of the body's surface at that point
};

struct Parcel {
    Vec3 x_m{};
    Vec3 v_m_s{};
    std::uint32_t spout{};
};

// The equal and opposite of what parcels did to one body, over the step: the
// impulse, and its moment about the world's origin (a host turns that into a
// torque about the body's centre: moment - centre x impulse).
struct ParcelPush {
    std::uint64_t body{};
    Vec3 impulse_n_s{};
    Vec3 moment_n_m_s{};
};

struct Landing {
    Vec3 at_m{};
    Vec3 momentum_n_s{};
    double volume_m3{};
};

struct FallingWaterLedger {
    double poured_m3{};
    double landed_m3{};
    double ran_off_m3{};
    // Kinetic energy taken out at bodies by contact that does not bounce,
    // joules: where the water's fall went that was not given to a body.
    double contact_loss_j{};
    std::uint64_t parcels_poured{};
};

class FallingWater {
public:
    // One parcel: a 4 cm cube of water, 64 g, as in the wheel experiment.
    static constexpr double kSpacing = 0.04;
    static constexpr double kVolume = kSpacing * kSpacing * kSpacing;
    static constexpr double kDensity = 1000.0;
    static constexpr double kMass = kDensity * kVolume;
    static constexpr double kRadius = 0.45 * kSpacing;
    static constexpr double kSupport = 0.10;
    static constexpr double kSoundSpeed = 20.0;
    static constexpr double kViscosity = 0.001;
    // Bounds that refuse rather than carry on: more parcels than this in the
    // air at once, or one faster than this.
    static constexpr std::size_t kMaxParcels = 2000;
    static constexpr double kMaxSpeed = 30.0;

    using SurfacesNear = std::function<std::vector<NearSurface>(const Vec3 &center, double radius, double reach)>;
    // The height a parcel's underside joins the river at under (x, z): the
    // water's surface, or the ground's where it is dry. Nothing off the grid.
    using LandingHeight = std::function<std::optional<double>(double x, double z)>;
    // The lowest the world goes: a parcel below this off the grid has left it.
    struct Plan {
        std::vector<Parcel> parcels;
        std::vector<ParcelPush> pushes;
        std::vector<Landing> landings;
        std::vector<double> owed_m3;
        FallingWaterLedger ledger;
        int substeps{};
    };

    void addSpout(const Spout &spout);
    [[nodiscard]] const std::vector<Spout> &spouts() const { return spouts_; }
    [[nodiscard]] const std::vector<Parcel> &parcels() const { return parcels_; }
    [[nodiscard]] const FallingWaterLedger &ledger() const { return ledger_; }
    // Water in the air now.
    [[nodiscard]] double inFlight() const { return static_cast<double>(parcels_.size()) * kVolume; }
    // poured - landed - ran off - in the air: zero but for rounding.
    [[nodiscard]] double residual() const;

    // Works out the next dt_s from time_s without changing anything: where
    // the parcels go, what they push, where they land.
    [[nodiscard]] Plan plan(double time_s, double dt_s, const SurfacesNear &near,
                            const LandingHeight &landing, double floor_y_m) const;
    // Keeps a plan's outcome. Its landings are the host's to put in the river.
    void accept(Plan &&plan);

private:
    std::vector<Spout> spouts_;
    std::vector<double> owed_m3_;
    std::vector<Parcel> parcels_;
    FallingWaterLedger ledger_;
};

}  // namespace banjo::water
