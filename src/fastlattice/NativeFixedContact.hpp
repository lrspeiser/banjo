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
// SI, absolute local error bounds. These control numerical approximation, not
// material strength or contact law. Exact surviving-bond/mode agreement is also
// required. Every trial interval commits two half steps or commits nothing.
struct NativeContactAccuracySettings {
    double minimum_step_s{1e-12};
    unsigned maximum_halvings{12};
    double position_m{1e-8},velocity_m_s{1e-4};
    double orientation_rad{1e-5},angular_velocity_rad_s{1e-4};
    double damage_fraction{1e-5},history_strain{1e-5};
    double plastic_extension_m{1e-8},plastic_strain{1e-5};
    double energy_j{1e-6},impulse_n_s{1e-6},angular_impulse_kg_m2_s{1e-7};
};
// Actual receipt aggregates, not guessed work or a source of applied impulses.
// Callback returns only contact fields; the controller measures native stepping.
struct NativeContactStepAudit {
    double contact_loss_j{},reconciliation_loss_j{},source_numerical_energy_j{};
    Vec3 source_numerical_impulse_n_s{},source_numerical_angular_kg_m2_s{},geometry_couple_kg_m2_s{};
    double native_step_energy_j{};
    Vec3 native_step_impulse_n_s{},native_step_angular_kg_m2_s{};
    std::uint64_t active_manifolds{};
};
struct NativeContactAccuracyResult {
    bool accepted{},topology_agrees{};
    unsigned attempted_intervals{},rejected_intervals{};
    double accepted_interval_s{},suggested_interval_s{},normalized_error{};
    std::string error_metric;
    NativeContactStepAudit accepted_audit{};
};
// Compare a restored full-step trial with a two-half-step trial from the same
// current state. Refine on disagreement; bounds/budgets refuse without advancing.
// Trusted callback reads actual geometry, applies contact, and returns receipts.
// It must not step the native world/target, publish receipts, or mutate external
// controller histories. This function owns both clocks and steps every currently
// participating native body; geometry/configuration remain fixed during trials.
// Serial double Verlet and the paired trial's bounded state budgets apply.
[[nodiscard]] NativeContactAccuracyResult advanceNativeFixedTargetControlled(
    JoltWorld &world,LatticeBackend &target,double proposed_interval_s,
    const NativeContactAccuracySettings &settings,
    const std::function<NativeContactStepAudit(double)> &contact);
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
struct NativeSurfaceWitness {
    std::uint32_t seed{};
    Vec3 surface_world_m{},normal_world{};
    double gap_m{};
    PointRigidContactSettings settings;
};
struct NativeFixedManifoldTransfer {
    FixedSurfaceManifoldKick source;
    ExternalPointTransferLedger target;
    std::vector<MaterialContactRegion> regions;
    std::uint64_t target_step{};
    double horizon_s{};
};
// Current graph support, bounded union, coupled response and both preflights
// precede either write. One atomic target transfer counts one manifold.
[[nodiscard]] NativeFixedManifoldTransfer applyNativeFixedLocalSurfaceManifold(
    JoltWorld &world,LatticeBackend &target,std::span<const NativeSurfaceWitness> witnesses,
    const MaterialContactRegionSettings &region_settings,MatterBodyId target_proxy,
    MatterBodyId striker,const PointContactRoundoffBudget &budget);
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
