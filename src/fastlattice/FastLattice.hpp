#pragma once

// The fast explicit lattice lane: BrittleBondSolver's physics on a
// schedule that runs every bond of a colour at once, on the GPU or on the
// CPU, with the shared failure criterion of fracture/BondFailure.hpp.
//
// A LatticeState is the canonical host copy of one ActiveMatter in schedule
// order. A LatticeBackend advances it for many substeps without returning to
// the host: the CPU backend is the fallback and the reference the CUDA backend
// is proven equal to; the CUDA backend is one persistent cooperative kernel
// per launch. Both run the code in LatticePhysics.hpp.

#include "fastlattice/LatticePhysics.hpp"
#include "fastlattice/LatticeSchedule.hpp"
#include "fastlattice/MaterialContactRegion.hpp"
#include "fracture/ActiveMatter.hpp"

#include <cstdint>
#include <functional>
#include <limits>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

namespace banjo::fastlattice {

enum class ExternalContactPhase : std::uint8_t { BeforeDrift, AfterForces };

enum class Precision : std::uint8_t { Float, Double };
[[nodiscard]] const char *precisionName(Precision precision);

// Canonical state, double precision, schedule order, positions relative to
// origin so the float backend keeps its precision near the tile.
struct LatticeState {
    Vec3 origin{};
    std::uint32_t node_count{};
    std::uint32_t bond_count{};
    std::vector<double> x0, u, u_prev, v, inv_mass, mass;
    std::vector<std::uint32_t> adj_offsets, adj_bonds;
    std::uint32_t max_degree{};
    std::vector<std::uint32_t> nbr_bond, nbr_other; // max_degree * N, k-major
    std::vector<double> nbr_rest, nbr_weight;       // 3 * max_degree * N, max_degree * N
    std::vector<std::uint8_t> nbr_alive;            // max_degree * N
    std::vector<std::uint32_t> bond_slot_a, bond_slot_b; // B
    std::vector<std::uint32_t> bond_a, bond_b;
    std::vector<double> rest_edge, rest_length, rest_length_sq_minus, weight, compliance, threshold;
    std::vector<std::uint8_t> alive, failure_mode;
    std::vector<double> damage, prev_tensile, prev_compressive, prev_shear;
    // Axial plastic state per bond, schedule order; zero everywhere unless the
    // material declares a yield strength (LatticePhysics.hpp bondPlasticReturn).
    std::vector<double> plastic_extension, plastic_strain;
};

// Elastic energy stored in the live bonds of a state, and the lattice's kinetic
// energy. Both are plain sums over the state, so they can be taken outside a
// backend; storedBondEnergy's rule holds -- the elastic extension is measured
// from the bond's plastic rest length, so plastic work is never counted here.
[[nodiscard]] double latticeStateElasticEnergy(const LatticeState &state);
[[nodiscard]] double latticeStateKineticEnergy(const LatticeState &state);

// The longest step a state can be taken at explicitly: 2 over its fastest
// node's own frequency, the square root of the stiffness of that node's live
// bonds over its mass. It is measureLatticeResolutionLimit's rule, applied to a
// state as it is now, with its masses and bonds as heat and breaking have left
// them. Zero when nothing in it is bonded.
[[nodiscard]] double latticeStateSubstepLimit(const LatticeState &state);

[[nodiscard]] LatticeState buildLatticeState(
    const ActiveMatter &matter, const LatticeSchedule &schedule, const Vec3 &origin);

// Positions, velocities, bond aliveness, damage, failure mode and the last
// strain sample back into the ActiveMatter the state was built from.
void writeBackLatticeState(
    const LatticeState &state, const LatticeSchedule &schedule, ActiveMatter &matter);

struct RunControl {
    // Substeps to attempt in this call.
    std::uint64_t max_steps{};
    // Stop once no bond has failed for this many substeps, after at least one
    // failure and min_steps in total. 0 disables.
    std::uint64_t quiet_steps{};
    std::uint64_t min_steps{};
    // Stop if nothing has failed by this many substeps in total. 0 disables.
    std::uint64_t no_failure_steps{};
    // Stop once the removed bond energy has grown by less than
    // energy_flat_fraction of its running total for this many substeps, after at
    // least one failure and min_steps in total. 0 disables. This is the cheap
    // exit: energy settles five to ten times earlier than the piece count does.
    std::uint64_t energy_flat_steps{};
    double energy_flat_fraction{1.0e-3};
    // Stop when nothing has failed, the worst bond is below calm_damage_margin
    // of the way to failing, and it has not climbed for this many substeps.
    // 0 disables. This is what saves a scene that was never going to break.
    std::uint64_t calm_steps{};
    double calm_damage_margin{0.5};
    // Stop once the bonds removed have taken this much energy out of the run.
    // 0 (the default) disables it and nothing is capped.
    //
    // A break cannot honestly take more energy out of the world than the thing
    // breaking and whatever struck it brought into the run. Measured in the
    // break room before this existed: a 0.93 kg plank piece hit the ground at
    // 10.2 m/s, carrying 48 J, and the run removed 58 J of bond energy while
    // turning it into 83 pieces (docs/what-a-break-costs.md). The ceiling is
    // the island's own kinetic and stored elastic energy, so it needs no
    // number anyone picked; the caller works it out and passes it in.
    // CPU external loads add their signed measured work to an enabled ceiling.
    // Removing all available energy stops the run rather than disabling it.
    //
    // It is checked after a substep, like every other stop, so a run can
    // overspend by at most what one substep removes. What it cannot do is go
    // on spending.
    double removable_energy_j{};
    // Capture node displacements and bond state every this many substeps
    // (state before the substep). 0 disables.
    std::uint64_t capture_stride{};
    std::uint32_t max_frames{};
    // CUDA: substeps per kernel launch (0 = whole run in one launch).
    std::uint64_t steps_per_launch{};
};

constexpr unsigned kPhaseCount = 16;
// Names of the per-substep phases the backends attribute time to.
[[nodiscard]] const char *latticePhaseName(unsigned phase, std::uint8_t integrator = kBondXpbd);

// CPU external-load phase only. World-space angular impulse is about the
// world origin. The source must receive the opposite delivered impulse;
// recording it here does not add that source to a live world.
// In the clamped Verlet reference, delivered impulses include loads on fixed
// nodes, cancelled by fixed_boundary. Their work is zero. Wrench regions and
// finite external point transfers still require movable nodes.
struct ExternalLoadLedger {
    std::uint64_t steps{};
    double elapsed_s{};
    Vec3 requested_impulse_n_s{}, impulse_n_s{};
    Vec3 requested_angular_impulse_kg_m2_s{};
    Vec3 angular_impulse_kg_m2_s{};
    double work_j{}; // exact kinetic-energy change across the external kick
};

// A wrench applied to an explicitly selected nodal load region. Point is in
// world metres, force in newtons, free couple in newton metres. This is a
// mass-weighted distributed load, not a fixing or a local hand traction law.
// Node indices are in the current schedule order, not parent cell numbering.
struct ExternalWrench {
    std::string source;
    std::vector<std::uint32_t> nodes;
    Vec3 point_world_m{}, force_n{}, torque_n_m{};
};
struct ExternalWrenchLedger {
    std::string source;
    ExternalLoadLedger load{};
};
struct ExternalPointTransferLedger {
    std::uint64_t transfers{}; // Instantaneous transfers, not elapsed substeps.
    Vec3 impulse_n_s{},angular_impulse_kg_m2_s{};
    double work_j{}; // Signed target kinetic change, not total contact loss.
};
struct ExternalPointVelocity {
    std::uint32_t node{};
    ActiveNodeState expected;
    Vec3 velocity_m_s{};
};

// Serial-double Verlet only. An explicitly clamped node keeps its physical
// mass, has zero inverse mass and zero velocity, and stays at its declared
// position. These are impulses ON the patch from the ideal stationary support;
// the support receives their negatives. Its work is exactly zero. Do not count
// these physical boundary reactions as floating-point bond error.
struct FixedBoundaryLedger {
    Vec3 impulse_n_s{}, angular_impulse_kg_m2_s{};
};

struct RunStatus {
    std::uint8_t bond_integrator{};
    // Verlet reference only: signed measured integration error, not heat or
    // corrective work. Plastic return overshoot is separately accounted.
    double integration_numerical_energy_j{}, plastic_return_numerical_loss_j{};
    ExternalLoadLedger gravity_load{};
    FixedBoundaryLedger fixed_boundary{};
    Vec3 bond_kick_roundoff_impulse_n_s{}, bond_kick_roundoff_angular_kg_m2_s{};
    ExternalLoadLedger external_load{};
    std::vector<ExternalWrenchLedger> external_sources;
    ExternalPointTransferLedger external_point_transfer{};
    std::uint64_t total_steps{};
    std::uint64_t first_failure_step{std::numeric_limits<std::uint64_t>::max()};
    std::uint64_t last_failure_step{std::numeric_limits<std::uint64_t>::max()};
    std::uint32_t failure_rounds{};   // substeps in which at least one bond failed
    std::uint32_t broken_bonds{};
    double removed_energy_j{};
    // The last substep at which removed energy grew by more than
    // RunControl::energy_flat_fraction of the running total.
    std::uint64_t last_energy_gain_step{std::numeric_limits<std::uint64_t>::max()};
    // The worst bond damage seen, 0 to 1, and the last substep it climbed at.
    // Zero rather than max() because a lattice nothing has touched has been
    // flat since the start, which is exactly the case reason 5 exists for.
    double max_damage{};
    std::uint64_t last_damage_gain_step{};
    ContactAccumulators contact{};
    NodeContactAccumulators node_contact{};
    // Only with StepSettings::audit_energy: kinetic energy the radial bond
    // damping sweep and the striker contact passes removed from the lattice,
    // measured as a difference of the lattice's total kinetic energy across each
    // phase, so they can be compared with node_contact.dissipated_kinetic_energy_j
    // on the same footing.
    double damping_dissipated_j{};
    double striker_dissipated_j{};
    bool energy_audited{};
    // 0 none/max_steps of the last call, 1 cascade quiet, 2 no failure by the
    // deadline, 3 max_steps reached, 4 removed energy flat, 5 nothing near
    // failing, 6 the energy the island had is spent.
    unsigned exit_reason{};
    unsigned launches{};
    double kernel_seconds{};   // CUDA event time over all launches
    double wall_seconds{};     // host wall time inside run()
    std::uint32_t frames_captured{};
    // Seconds per phase as seen by the leading thread, including the wait at
    // the barrier that ends the phase (CUDA: SM cycle counter; CPU: wall).
    double phase_seconds[kPhaseCount]{};
    bool shared_memory_positions{};
    // Bytes of shared memory the single-block kernel keeps state in (0: none).
    std::size_t shared_memory_bytes{};
    // Largest substep peaks seen over the run (float precision, diagnostic).
    float max_tensile_stretch{}, max_compressive_strain{}, max_shear_strain{};
    // Rest-covariance recomputations on which the CPU's absolute determinant
    // rule and the relative rule disagreed (see LatticePhysics.hpp).
    std::uint32_t rank_deficient_nodes{};
    // Plastic work dissipated by the bonds over the run, and the largest
    // permanent bond extension as a fraction of a rest length. Both are exactly
    // zero when the material declares no yield strength. The CUDA backend sums
    // the work with atomics, as it already does the removed fracture energy, so
    // its last bits depend on the order the failing threads arrive in; the
    // addends are identical.
    double plastic_work_j{};
    float max_plastic_stretch{};
};

struct FrameCapture {
    std::uint64_t step{};
    std::vector<float> u;            // 3N
    std::vector<std::uint8_t> alive; // B
    std::vector<float> damage;       // B
    SphereState<double> sphere{};
};

class LatticeBackend {
public:
    virtual ~LatticeBackend() = default;
    // Trusted host callback between run calls. Serial double CPU only. False
    // or an exception restores every working array, history/cache, load/span,
    // status/clock, frame and first-failure receipt. Upload is forbidden inside.
    // No portable snapshot; tentative outputs must not escape before acceptance.
    // Keep this backend alive/unmoved. 16 MiB copied payload; no nested trials.
    [[nodiscard]] virtual bool runReversibleTrial(const std::function<bool()> &) {
        throw std::invalid_argument("this lattice backend has no qualified reversible trial");
    }
    [[nodiscard]] virtual std::string name() const = 0;
    virtual void upload(const LatticeState &state, const StepSettings<double> &settings,
                        const SphereState<double> &sphere) = 0;
    // Finite world-space forces in schedule node order, held constant for at
    // most `substeps` actual substeps, including across successive run calls.
    // Upload clears a load. Empty + zero cancels; invalid replacement leaves
    // the old load intact. CPU reference/parallel implement this; GPU support
    // is deliberately explicit rather than silently omitting a force.
    virtual void setExternalForces(const std::vector<Vec3> &forces_world_n, std::uint64_t substeps) {
        if (!forces_world_n.empty() || substeps != 0)
            throw std::invalid_argument("this lattice backend does not implement external forces");
    }
    // Replaces the force field. Disjoint named regions allow separate source
    // reactions/work to be retained. Forces are recomputed from current node
    // positions every kick to retain the requested resultant and moment.
    // Unsampled torque, duplicate sources/nodes and overlapping regions refuse.
    // Source labels identify accounts; they do not authorize player ownership.
    // Point and wrench remain fixed in world coordinates for the finite span;
    // a live hand controller must update them on its own declared clock.
    virtual void setExternalWrenches(const std::vector<ExternalWrench> &wrenches, std::uint64_t substeps) {
        if (!wrenches.empty() || substeps != 0)
            throw std::invalid_argument("this lattice backend does not implement external wrenches");
    }
    // Serial double CPU reference only. Read a current schedule-order point,
    // then validate/commit a velocity supplied by an audited external contact.
    // Expected point must match current position/history/velocity/mass exactly.
    // No pose, bond/history, cache, load, capture or elapsed-time reset. No spin
    // DOF is introduced. Validation preflights the cumulative signed SI ledger.
    // One host thread between run calls; do not mutate either backend between
    // validation and commit. Other precision/backends explicitly refuse.
    [[nodiscard]] virtual ActiveNodeState externalContactPoint(std::uint32_t) const {
        throw std::invalid_argument("this lattice backend does not implement external point contact");
    }
    [[nodiscard]] virtual double externalContactTimestep() const {
        throw std::invalid_argument("this lattice backend does not implement external point contact");
    }
    // Accepted physical time since upload, independent of substep count. The
    // owner retains an absolute origin when transferring a constituent. Only
    // serial double Verlet implements this clock and variable contact steps.
    [[nodiscard]] virtual double externalContactElapsedTime() const {
        throw std::invalid_argument("this lattice backend does not implement a contact clock");
    }
    // Within a paired reversible source/material trial, scope the contact
    // horizon to dt, invoke contact (including the source's one native step),
    // then advance the material once. 0 < dt <= uploaded dt. No upload/history
    // reset. Contact must not run/reenter this backend or replace finite loads.
    // Queued loads count substeps; changing their timestep is refused. Callback
    // receipts are provisional until the enclosing paired trial is accepted.
    virtual RunStatus advanceExternalContactStep(double,const std::function<void()> &) {
        throw std::invalid_argument("this lattice backend does not implement variable contact steps");
    }
    // Serial-double Verlet: actual first force half-kick, BeforeDrift contact,
    // drift, final forces/damping, AfterForces contact, failure/history update.
    // One physical step and one finite-load substep. Pure contact transfers
    // inside either phase are separately accounted from integration error.
    // Paired trial, timestep and callback reentry restrictions are identical.
    virtual RunStatus advanceCoupledContactStep(double,const std::function<void(ExternalContactPhase)> &) {
        throw std::invalid_argument("this lattice backend does not implement force-boundary contact");
    }
    // Read-only actual velocity before this phase's force half-kick, at the
    // current unchanged phase geometry. Available only inside its coupled
    // callback, for finite movable nodes in serial-double CPU Verlet. This
    // snapshot does not change contact work or infer a dissipation law.
    [[nodiscard]] virtual ActiveNodeState externalContactForceStartPoint(std::uint32_t) const {
        throw std::invalid_argument("this lattice backend does not expose force-phase starting states");
    }
    [[nodiscard]] virtual std::vector<std::uint32_t> externalContactForceMovableNodes() const {
        throw std::invalid_argument("this lattice backend does not expose force-phase mobility");
    }
    [[nodiscard]] virtual ExternalPointTransferLedger validateExternalPointVelocity(
        std::uint32_t,const ActiveNodeState &,Vec3) const {
        throw std::invalid_argument("this lattice backend does not implement external point contact");
    }
    virtual ExternalPointTransferLedger applyExternalPointVelocity(std::uint32_t,const ActiveNodeState &,Vec3) {
        throw std::invalid_argument("this lattice backend does not implement external point contact");
    }
    // One atomic instantaneous contact distributed over 1..64 distinct nodes.
    // Every expected state and cumulative ledger is checked before any write.
    // One transfer is counted, regardless of stencil size. No pose/history/time
    // change; serial double CPU only, other backends explicitly refuse.
    [[nodiscard]] virtual ExternalPointTransferLedger validateExternalPointVelocities(
        std::span<const ExternalPointVelocity>) const {
        throw std::invalid_argument("this lattice backend does not implement regional contact");
    }
    virtual ExternalPointTransferLedger applyExternalPointVelocities(std::span<const ExternalPointVelocity>) {
        throw std::invalid_argument("this lattice backend does not implement regional contact");
    }
    // Select from actual current mobility, positions and surviving canonical
    // bonds. No full state download or caller-provided connectivity snapshot.
    [[nodiscard]] virtual MaterialContactRegion externalContactRegion(
        std::uint32_t,const MaterialContactRegionSettings &) const {
        throw std::invalid_argument("this lattice backend does not implement live contact regions");
    }
    // Continue from the current state; the status accumulates across calls.
    virtual RunStatus run(const RunControl &control) = 0;
    virtual void download(LatticeState &state, SphereState<double> &sphere) = 0;
    // Frames captured since the last call, oldest first.
    virtual std::vector<FrameCapture> takeFrames() = 0;
    [[nodiscard]] virtual const RunStatus &status() const = 0;
    // The bonds (schedule indices) removed in the substep of the first
    // failure since upload, for backends that record them. The CUDA backend
    // does not; it returns an empty list and the scene reports no location.
    [[nodiscard]] virtual std::vector<std::uint32_t> firstFailureBonds() const { return {}; }
};

[[nodiscard]] std::unique_ptr<LatticeBackend> makeCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision);

// The same phases on a thread pool, bit identical to the serial backend: the
// independent per-node and per-bond phases are split, the Gauss-Seidel sweep
// and the sphere contact pass stay serial because their order is physics.
// threads = 0 asks for the hardware concurrency; spins = 0 takes the default
// number of pause instructions an idle worker spins before yielding.
[[nodiscard]] std::unique_ptr<LatticeBackend> makeParallelCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision, unsigned threads, unsigned spins = 0);

// Wall seconds for `dispatches` empty pool dispatches: the floor under any
// phase the parallel backend can spread, measured on this machine.
[[nodiscard]] double measureParallelDispatchCost(unsigned threads, unsigned spins, unsigned dispatches);

// The thread count the machine would allow if it were idle.
[[nodiscard]] unsigned defaultLatticeThreadCount();

// What makeParallelCpuLatticeBackend actually uses when asked for 0: the
// default, halved until an empty dispatch is cheap on this machine as it is
// loaded right now, and 1 if even two threads are not worth it. The choice
// changes speed only; the backend is bit identical at every thread count.
[[nodiscard]] unsigned calibratedLatticeThreadCount(unsigned spins);

// Throws std::runtime_error when the build has no CUDA backend or no device.
[[nodiscard]] std::unique_ptr<LatticeBackend> makeCudaLatticeBackend(
    const LatticeSchedule &schedule, Precision precision, unsigned threads_per_block);
[[nodiscard]] bool cudaLatticeAvailable();
[[nodiscard]] std::string cudaLatticeDescription();
[[nodiscard]] unsigned cudaLatticeMultiprocessorCount();

} // namespace banjo::fastlattice
