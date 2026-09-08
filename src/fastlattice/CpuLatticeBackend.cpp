// CPU backend of the fast explicit lattice lane: the same phases, in the same
// order and with the same element functions as the CUDA kernel, executed by
// one thread. It is the fallback when the build has no CUDA and the reference
// the kernel is proven equal to.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace banjo::fastlattice {
namespace {

template <typename Real>
class CpuLatticeBackend final : public LatticeBackend {
public:
    explicit CpuLatticeBackend(LatticeSchedule schedule) : schedule_(std::move(schedule)) {}

    [[nodiscard]] std::string name() const override {
        return std::string("cpu-") + (sizeof(Real) == 4 ? "float" : "double");
    }

    void upload(const LatticeState &state, const StepSettings<double> &settings,
                const SphereState<double> &sphere) override {
        working_ = WorkingLattice<Real>::fromState(state, schedule_);
        L_ = working_.arrays();
        S_ = convertSettings<Real>(settings);
        sphere_ = convertSphere<Real>(sphere);
        status_ = {};
        dirty_start_ = true;
        frames_.clear();
        first_failure_bonds_.clear();
    }

    RunStatus run(const RunControl &control) override {
        const auto start = std::chrono::steady_clock::now();
        status_.exit_reason = 0;
        std::uint64_t done = 0;
        while (done < control.max_steps) {
            const std::uint64_t step = status_.total_steps;
            if (control.capture_stride != 0 && step % control.capture_stride == 0 &&
                status_.frames_captured < control.max_frames) {
                frames_.push_back(captureFrame(working_, step, sphere_));
                ++status_.frames_captured;
            }
            const bool failed = advance(step);
            status_.total_steps = step + 1;
            ++done;
            if (failed) {
                if (status_.first_failure_step == std::numeric_limits<std::uint64_t>::max())
                    status_.first_failure_step = step;
                status_.last_failure_step = step;
                ++status_.failure_rounds;
            }
            status_.exit_reason = latticeExitReason(status_.total_steps, status_.broken_bonds,
                status_.last_failure_step, control.quiet_steps, control.min_steps,
                control.no_failure_steps);
            if (status_.exit_reason != 0) break;
        }
        if (status_.exit_reason == 0 && done >= control.max_steps) status_.exit_reason = 3;
        ++status_.launches;
        status_.wall_seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        return status_;
    }

    void download(LatticeState &state, SphereState<double> &sphere) override {
        working_.toState(state);
        sphere = widenSphere(sphere_);
    }

    std::vector<FrameCapture> takeFrames() override {
        std::vector<FrameCapture> out;
        out.swap(frames_);
        status_.frames_captured = 0;
        return out;
    }

    [[nodiscard]] const RunStatus &status() const override { return status_; }
    [[nodiscard]] std::vector<std::uint32_t> firstFailureBonds() const override { return first_failure_bonds_; }

private:
    template <typename Body>
    void sweep(std::uint32_t block, std::uint32_t boundary, Body &&body) {
        for (std::uint32_t c = 0; c < L_.color_count; ++c) {
            const std::size_t key = (static_cast<std::size_t>(block) * 2U + boundary) * L_.color_count + c;
            for (std::uint32_t j = L_.range_begin[key]; j < L_.range_end[key]; ++j) body(j);
        }
    }

    template <typename Body>
    void sweepAll(Body &&body) {
        for (std::uint32_t block = 0; block < L_.block_count; ++block) sweep(block, 0U, body);
        for (std::uint32_t block = 0; block < L_.block_count; block += 2U) sweep(block, 1U, body);
        for (std::uint32_t block = 1; block < L_.block_count; block += 2U) sweep(block, 1U, body);
    }

    void mark(unsigned phase) {
        const auto now = std::chrono::steady_clock::now();
        status_.phase_seconds[phase] += std::chrono::duration<double>(now - phase_clock_).count();
        phase_clock_ = now;
    }

    // One substep; returns whether any bond failed.
    bool advance(std::uint64_t step) {
        const bool direct = S_.direct_arithmetic != 0;
        const std::uint32_t N = L_.node_count, B = L_.bond_count;
        (void)step;
        phase_clock_ = std::chrono::steady_clock::now();
        if (dirty_start_) {
            for (std::uint32_t i = 0; i < N; ++i) nodeStrain(L_, i, direct);
            mark(1);
            for (std::uint32_t j = 0; j < B; ++j)
                if (L_.alive[j]) bondStartSample(L_, j, direct);
            mark(2);
            dirty_start_ = false;
        }
        // Kick, classify, ordered candidate lists per block.
        SphereState<Real> kicked = sphere_;
        kicked.velocity = kicked.velocity + S_.dt * S_.gravity;
        for (std::uint32_t block = 0; block < L_.block_count; ++block) {
            std::uint32_t count = 0;
            for (std::uint32_t i = L_.node_block_begin[block]; i < L_.node_block_begin[block + 1]; ++i) {
                if (!nodeKickAndClassify(L_, S_, kicked, i)) continue;
                if (count < kMaxCandidatesPerBlock)
                    L_.candidate_list[block * kMaxCandidatesPerBlock + count] = i;
                else
                    ++status_.contact.candidate_overflow;
                ++count;
            }
            L_.candidate_count[block] = count < kMaxCandidatesPerBlock ? count : kMaxCandidatesPerBlock;
        }
        sphere_ = kicked;
        mark(3);
        if (S_.sphere_enabled) sphereContactPass(L_, S_, sphere_, 1, status_.contact);
        mark(4);
        for (std::uint32_t iteration = 0; iteration < S_.constraint_iterations; ++iteration) {
            const bool first = iteration == 0;
            for (std::uint32_t block = 0; block < L_.block_count; ++block)
                sweep(block, 0U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            mark(5);
            for (std::uint32_t block = 0; block < L_.block_count; block += 2U)
                sweep(block, 1U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            for (std::uint32_t block = 1; block < L_.block_count; block += 2U)
                sweep(block, 1U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            mark(6);
            for (std::uint32_t i = 0; i < N; ++i) nodeSupportProject(L_, S_, i);
            mark(7);
        }
        for (std::uint32_t i = 0; i < N; ++i) nodeVelocityUpdate(L_, S_, i);
        mark(8);
        if (S_.damping_fraction > Real(0)) {
            sweepAll([&](std::uint32_t j) { bondDamp(L_, j, S_.damping_fraction, direct); });
            for (std::uint32_t i = 0; i < N; ++i)
                if (!L_.candidate[i]) nodeSupportVelocity(L_, S_, i);
            mark(9);
        }
        if (S_.sphere_enabled) sphereContactPass(L_, S_, sphere_, 2, status_.contact);
        mark(10);
        for (std::uint32_t i = 0; i < N; ++i) nodeStrain(L_, i, direct);
        mark(11);
        bool any_failed = false;
        const bool first_failure_round = status_.broken_bonds == 0;
        for (std::uint32_t j = 0; j < B; ++j) {
            if (!L_.alive[j]) continue;
            const FailureOutcome out = bondEndSampleAndFailure(L_, j, direct);
            status_.max_tensile_stretch = std::max(status_.max_tensile_stretch, out.peak_tensile);
            status_.max_compressive_strain = std::max(status_.max_compressive_strain, out.peak_compressive);
            status_.max_shear_strain = std::max(status_.max_shear_strain, out.peak_shear);
            if (!out.broke) continue;
            any_failed = true;
            if (first_failure_round) first_failure_bonds_.push_back(j);
            status_.removed_energy_j += out.removed_energy_j;
            ++status_.broken_bonds;
            L_.node_dirty[L_.bond_a[j]] = 1;
            L_.node_dirty[L_.bond_b[j]] = 1;
        }
        mark(12);
        status_.degenerate_disagreements = working_.degenerate_disagreements.front();
        sphere_.center = sphere_.center + S_.dt * sphere_.velocity;
        sphereSupportContact(S_, sphere_, status_.contact);
        if (any_failed) dirty_start_ = true;
        mark(13);
        return any_failed;
    }

    std::chrono::steady_clock::time_point phase_clock_{};

    LatticeSchedule schedule_;
    WorkingLattice<Real> working_;
    LatticeArrays<Real> L_{};
    StepSettings<Real> S_{};
    SphereState<Real> sphere_{};
    RunStatus status_{};
    bool dirty_start_{true};
    std::vector<FrameCapture> frames_;
    std::vector<std::uint32_t> first_failure_bonds_;
};

} // namespace

std::unique_ptr<LatticeBackend> makeCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision) {
    if (precision == Precision::Float) return std::make_unique<CpuLatticeBackend<float>>(schedule);
    return std::make_unique<CpuLatticeBackend<double>>(schedule);
}

} // namespace banjo::fastlattice
