#pragma once
#include "fastlattice/FastLattice.hpp"
#include "rigid/JoltWorld.hpp"
#include "physics/MaterialContactStencil.hpp"

namespace banjo::fastlattice {
// Trusted serial host callback. False/exception restores native state and the
// serial-double target's histories, queued loads, captures and clocks together.
// Configuration/upload remain forbidden; no nested paired trial. Caller owns
// hand/controller state and must not publish tentative receipts from the callback.
[[nodiscard]] bool runNativeFixedTargetTrial(JoltWorld &world,LatticeBackend &target,
    const std::function<bool()> &trial);
struct NativeFixedPointTransfer {
    FixedPointContactKick source;
    ExternalPointTransferLedger target;
    std::uint32_t node{};
    std::uint64_t target_step{};
    double horizon_s{};
};
// One instantaneous owned contact between a native fixed source and the serial
// double target backend's actual node. Prepares native and target candidates
// before either write. No target upload/history reset or physical time advance.
// Host thread between steps; the caller owns all source/target witnesses, pair
// coverage, hand/joint loads and advancing both systems on one accepted clock.
// Contact horizon comes from the target backend's uploaded timestep.
[[nodiscard]] NativeFixedPointTransfer applyNativeFixedPointTransfer(
    JoltWorld &world,LatticeBackend &target,std::uint32_t node,MatterBodyId target_proxy,
    MatterBodyId striker,Vec3 normal_world,double gap_m,
    const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget);
struct NativeFixedSurfaceTransfer {
    FixedPointContactKick source;
    ExternalPointTransferLedger target;
    MaterialContactStencil stencil;
    MaterialContactRegion region; // Populated by the live local-region wrapper.
    Vec3 target_impulse_error_n_s{},target_angular_error_kg_m2_s{};
    double target_work_error_j{},horizon_s{};
    std::uint64_t target_step{};
};
// One common surface point for source and target reactions. Caller must supply
// an actual geometry witness and a current connected 3D support (4..64 unique
// movable nodes); this function does not discover topology or certify support.
// Refuses planar/singular support. Signed affine traction weights are not
// granular masses or a cell-spin law. No time, pose, strain or damage reset.
[[nodiscard]] NativeFixedSurfaceTransfer applyNativeFixedSurfaceTransfer(
    JoltWorld &world,LatticeBackend &target,std::span<const std::uint32_t> support,
    MatterBodyId target_proxy,MatterBodyId striker,Vec3 surface_world_m,
    Vec3 normal_world,double gap_m,const PointRigidContactSettings &settings,
    const PointContactRoundoffBudget &budget);
// Authoritative graph selection immediately before this contact. Does not
// accept a cached region; broken bonds and moved cells are read now. A valid
// graph region may still refuse affine contact if thin/singular/isolated.
[[nodiscard]] NativeFixedSurfaceTransfer applyNativeFixedLocalSurfaceTransfer(
    JoltWorld &world,LatticeBackend &target,std::uint32_t seed,
    const MaterialContactRegionSettings &region_settings,MatterBodyId target_proxy,
    MatterBodyId striker,Vec3 surface_world_m,Vec3 normal_world,double gap_m,
    const PointRigidContactSettings &settings,const PointContactRoundoffBudget &budget);
}
