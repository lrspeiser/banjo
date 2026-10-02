#pragma once
#include "fastlattice/FastLattice.hpp"
#include "rigid/JoltWorld.hpp"

namespace banjo::fastlattice {
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
}
