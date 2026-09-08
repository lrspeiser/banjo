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
};

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

constexpr unsigned kPhaseCount = 14;
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
    std::uint32_t degenerate_disagreements{};
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
};

[[nodiscard]] std::unique_ptr<LatticeBackend> makeCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision);

// Throws std::runtime_error when the build has no CUDA backend or no device.
[[nodiscard]] std::unique_ptr<LatticeBackend> makeCudaLatticeBackend(
    const LatticeSchedule &schedule, Precision precision, unsigned threads_per_block);
[[nodiscard]] bool cudaLatticeAvailable();
[[nodiscard]] std::string cudaLatticeDescription();
[[nodiscard]] unsigned cudaLatticeMultiprocessorCount();

} // namespace banjo::fastlattice
