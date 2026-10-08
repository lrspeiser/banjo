#pragma once
#include "fastlattice/FastLattice.hpp"
#include "fastlattice/ContactAccuracy.hpp"
#include "physics/DoubleFixedSource.hpp"

namespace banjo::fastlattice {
struct DoubleFixedManifoldTransfer {
    FixedSurfaceManifoldResult contact;
    ExternalPointTransferLedger target;
    std::vector<MaterialContactRegion> regions;
    double source_work_j{},source_roundoff_energy_j{},work_residual_j{};
    Vec3 momentum_residual_n_s{},angular_residual_kg_m2_s{};
    std::uint64_t target_step{};
    double horizon_s{};
};
// Pure contact law shared with native coupling, actual current material graph,
// and CPU-owned double source. Geometry witnesses must come from the source's
// actual current member poses. No native body is advanced or written here.
// Both candidates are preflighted before the atomic target/source write.
[[nodiscard]] DoubleFixedManifoldTransfer applyDoubleFixedLocalSurfaceManifold(
    DoubleFixedSource &,LatticeBackend &,std::span<const MaterialSurfaceWitness>,
    const MaterialContactRegionSettings &,std::uint32_t striker);
// Trusted serial paired trial, restoring source pose/momentum/clock and target
// history/load/capture/accounts on false or exception. No nested material trial.
[[nodiscard]] bool runDoubleFixedTargetTrial(DoubleFixedSource &,LatticeBackend &,
    const std::function<bool()> &);
struct DoubleFixedStep {
    DoubleRigidTransfer free_drift;
    std::vector<DoubleFixedSourceTransfer> source_loads;
    std::vector<DoubleFixedManifoldTransfer> contacts;
    double interval_s{};
};
struct DoubleSourceWrench {
    std::uint32_t member{};
    Vec3 point_member_local_m{},force_world_n{},free_torque_world_n_m{};
};
// One shared physical interval: target/source half-forces/contact, source free
// drift, target drift/final-forces, source half-forces/contact/failure. Source
// wrenches are constant world forces/couples at current member-local points,
// limited to 256; midpoint signed work and member reactions are retained.
// Callback reads current CPU source
// geometry and returns only actual applied receipts. This is an experimental
// reference step, not automatic accuracy acceptance, collision discovery,
// finite-cell debris contact, external native-world transfer or live-world UI.
[[nodiscard]] DoubleFixedStep advanceDoubleFixedTargetStep(DoubleFixedSource &,LatticeBackend &,double dt_s,
    const std::function<DoubleFixedManifoldTransfer(double)> &contact,
    std::span<const DoubleSourceWrench> source_wrenches={});
struct DoubleContactStepAudit {
    double contact_loss_j{},reconciliation_loss_j{},source_roundoff_energy_j{},source_drift_energy_j{},source_load_work_j{};
    Vec3 contact_impulse_residual_n_s{},contact_angular_residual_kg_m2_s{},geometry_couple_kg_m2_s{};
    Vec3 drift_impulse_residual_n_s{},drift_angular_residual_kg_m2_s{},source_load_impulse_n_s{},source_load_angular_kg_m2_s{};
    std::vector<FixedVelocityImpulse> fixing_reactions;
    std::uint64_t active_manifolds{};
};
struct DoubleContactAccuracyResult : ContactAccuracyDifference {
    DoubleContactStepAudit accepted_audit;
};
// Full/two-half paired trials from the same actual state. Commits two half
// steps only on exact topology agreement and all shared SI bounds <= 1.
// Otherwise bounded refinement restores both clocks, states and ledgers.
// Callback must query current source geometry and return actual contact
// receipts only; no outside histories, publication or clock/config edits.
// CPU source and serial double Verlet target; no native dynamics or cache.
[[nodiscard]] DoubleContactAccuracyResult advanceDoubleFixedTargetControlled(
    DoubleFixedSource &,LatticeBackend &,double proposed_interval_s,const ContactAccuracySettings &,
    const std::function<DoubleFixedManifoldTransfer(double)> &contact,
    std::span<const DoubleSourceWrench> source_wrenches={});
} // namespace banjo::fastlattice
