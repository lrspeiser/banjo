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
#include "fracture/ActiveMatter.hpp"

#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace banjo::fastlattice {

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
    // Capture node displacements and bond state every this many substeps
    // (state before the substep). 0 disables.
    std::uint64_t capture_stride{};
    std::uint32_t max_frames{};
    // CUDA: substeps per kernel launch (0 = whole run in one launch).
    std::uint64_t steps_per_launch{};
};

constexpr unsigned kPhaseCount = 16;
// Names of the per-substep phases the backends attribute time to.
[[nodiscard]] const char *latticePhaseName(unsigned phase);

struct RunStatus {
    std::uint64_t total_steps{};
    std::uint64_t first_failure_step{std::numeric_limits<std::uint64_t>::max()};
    std::uint64_t last_failure_step{std::numeric_limits<std::uint64_t>::max()};
    std::uint32_t failure_rounds{};   // substeps in which at least one bond failed
    std::uint32_t broken_bonds{};
    double removed_energy_j{};
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
    // deadline, 3 max_steps reached.
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
    [[nodiscard]] virtual std::string name() const = 0;
    virtual void upload(const LatticeState &state, const StepSettings<double> &settings,
                        const SphereState<double> &sphere) = 0;
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
