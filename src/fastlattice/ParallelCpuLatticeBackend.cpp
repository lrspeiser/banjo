// Exact multithreaded CPU backend for the fast explicit lattice.
//
// This is CpuLatticeBackend.cpp phase for phase, with the phases whose elements
// are independent spread over a thread pool. It is not an approximation and not
// a different schedule: every element function sees the same inputs, writes the
// same outputs and is called the same number of times, so the result is bit
// identical to the serial backend. Three things make that true and are the only
// places the parallel version differs at all:
//
//   * The Gauss-Seidel constraint sweep stays serial. A colour stage of this
//     lattice holds ~120 bonds and costs ~2 us; a barrier costs more than the
//     stage, and splitting the sweep by slabs would change the sweep order,
//     which changes the cascade. The sweep is left exactly as it is.
//   * The sphere contact pass stays serial: every node's impulse changes the
//     ball the next node sees, so node order is part of the physics.
//   * Reductions are made order-independent or replayed in index order. The
//     strain peaks combine by max, which is exact and commutative. The removed
//     energy is summed by a serial pass over the bonds that broke, in bond
//     index order, which is the order the serial backend adds them in.
//
// tests/fracture_algo3_tests.cpp asserts the bit-identity through a fracture
// cascade; docs/algo3-propagator-cones-checkpoint.md records the speedup.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

#if defined(_MSC_VER)
#include <immintrin.h>
#define BANJO_PAUSE() _mm_pause()
#elif defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
#define BANJO_PAUSE() _mm_pause()
#else
#define BANJO_PAUSE() ((void)0)
#endif

namespace banjo::fastlattice {
namespace {

// A spin pool. The phases it runs are 5-80 us of work each and there are five
// of them per substep, so parking and waking the workers would cost more than
// the work; they spin on a generation counter and yield only after a long wait.
class SpinPool {
public:
    // spins is how many pause instructions an idle worker executes before it
    // yields: too few and the OS deschedules a worker that is about to be
    // needed, too many and the idle workers compete with the serial sweep for
    // the core. Measured, not assumed (see the checkpoint).
    SpinPool(unsigned threads, unsigned spins) : count_(std::max(1U, threads)), spins_before_yield_(spins) {
        for (unsigned t = 1; t < count_; ++t) workers_.emplace_back([this, t] { loop(t); });
    }

    ~SpinPool() {
        stop_.store(true, std::memory_order_release);
        generation_.fetch_add(1, std::memory_order_release);
        for (std::thread &worker : workers_) worker.join();
    }

    SpinPool(const SpinPool &) = delete;
    SpinPool &operator=(const SpinPool &) = delete;

    [[nodiscard]] unsigned size() const { return count_; }

    // body(thread, threads) is called once per thread, including the caller.
    // Type-erased through a function pointer rather than std::function so a
    // phase dispatch never allocates: there are five per substep.
    template <typename Body>
    void run(Body &&body) {
        if (count_ == 1) {
            body(0U, 1U);
            return;
        }
        argument_ = const_cast<void *>(static_cast<const void *>(&body));
        trampoline_ = [](void *argument, unsigned thread, unsigned threads) {
            (*static_cast<std::remove_reference_t<Body> *>(argument))(thread, threads);
        };
        remaining_.store(count_ - 1, std::memory_order_release);
        generation_.fetch_add(1, std::memory_order_release);
        body(0U, count_);
        unsigned spins = 0;
        while (remaining_.load(std::memory_order_acquire) != 0) {
            BANJO_PAUSE();
            if (++spins > spins_before_yield_) {
                std::this_thread::yield();
                spins = 0;
            }
        }
        trampoline_ = nullptr;
        argument_ = nullptr;
    }

private:
    void loop(unsigned index) {
        unsigned seen = 0;
        for (;;) {
            unsigned spins = 0;
            while (generation_.load(std::memory_order_acquire) == seen) {
                BANJO_PAUSE();
                if (++spins > spins_before_yield_) {
                    std::this_thread::yield();
                    spins = 0;
                }
            }
            seen = generation_.load(std::memory_order_acquire);
            if (stop_.load(std::memory_order_acquire)) return;
            trampoline_(argument_, index, count_);
            remaining_.fetch_sub(1, std::memory_order_release);
        }
    }

    unsigned count_;
    unsigned spins_before_yield_;
    std::vector<std::thread> workers_;
    // Separate cache lines. The workers all read generation_ while one of them
    // writes remaining_; sharing a line would make every completion invalidate
    // every spinner's copy, which costs more than the phases are worth.
    alignas(64) std::atomic<unsigned> generation_{0};
    alignas(64) std::atomic<unsigned> remaining_{0};
    alignas(64) std::atomic<bool> stop_{false};
    using Trampoline = void (*)(void *, unsigned, unsigned);
    Trampoline trampoline_{nullptr};
    void *argument_{nullptr};
};

// Contiguous slice of [0, count) for one thread: contiguous so each thread
// walks memory forwards, and deterministic so the work split never changes.
struct Slice {
    std::uint32_t begin, end;
};

Slice sliceOf(std::uint32_t count, unsigned thread, unsigned threads) {
    const std::uint32_t chunk = (count + threads - 1U) / threads;
    const std::uint32_t begin = std::min(count, chunk * thread);
    return {begin, std::min(count, begin + chunk)};
}

// Below this many elements a phase runs on the calling thread: a pool dispatch
// costs about a microsecond, so a phase has to be worth more than that. The
// value is measured on the headline plate (see the checkpoint), where a colour
// stage holds about 120 bonds and the per-node phases 500 nodes.
constexpr std::uint32_t kMinParallelItems = 64;

// One bond that failed in a substep, kept so the serial replay can add its
// energy in bond index order.
struct Breakage {
    std::uint32_t bond;
    double energy_j;
};

template <typename Real>
class ParallelCpuLatticeBackend final : public LatticeBackend {
public:
    ParallelCpuLatticeBackend(LatticeSchedule schedule, unsigned threads, unsigned spins)
        : schedule_(std::move(schedule)), pool_(threads, spins) {}

    [[nodiscard]] std::string name() const override {
        return std::string("cpu-parallel-") + (sizeof(Real) == 4 ? "float" : "double") + "-x" +
               std::to_string(pool_.size());
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
        // Per-thread scratch. Each thread gets its own view of the arrays so
        // that the degenerate-disagreement counter, the only element function
        // that writes a shared scalar, is thread-local; the counts are summed
        // afterwards, which an integer sum makes order-independent.
        const unsigned threads = pool_.size();
        scratch_ = std::vector<Scratch>(threads);
        views_.assign(threads, L_);
        for (unsigned t = 0; t < threads; ++t) views_[t].degenerate_disagreements = &scratch_[t].degenerate;
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
            const bool failed = advance();
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

private:
    // One cache line per thread. The criterion phase updates the strain peaks
    // once per bond, so packing these back to back put every thread's write on
    // one shared line: with them adjacent the phase did not scale at all
    // (1.08x on sixteen threads), with them apart it does.
    struct alignas(64) Scratch {
        float tensile{}, compressive{}, shear{};
        std::uint32_t degenerate{};
        std::vector<Breakage> breakages;
        char padding[64 - ((3 * sizeof(float) + sizeof(std::uint32_t) +
                            sizeof(std::vector<Breakage>)) % 64)]{};
    };

    // One colour stage at a time. The bonds of a colour share no node, so the
    // stage may be spread across threads without changing any value: each bond
    // reads and writes only its own two nodes. The stages themselves stay in
    // order, which is what makes this the same Gauss-Seidel sweep.
    template <typename Body>
    void sweep(std::uint32_t block, std::uint32_t boundary, Body &&body) {
        for (std::uint32_t c = 0; c < L_.color_count; ++c) {
            const std::size_t key = (static_cast<std::size_t>(block) * 2U + boundary) * L_.color_count + c;
            const std::uint32_t begin = L_.range_begin[key], end = L_.range_end[key];
            forEachRange(begin, end, [&](std::uint32_t j, unsigned) { body(j); });
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

    // Run body over [0, count) split into one contiguous slice per thread.
    // Only the per-bond phases use it. A pool dispatch on this machine costs a
    // few microseconds; the per-node phases of a 500-cell plate are 1-10 us of
    // work each, so dispatching them made the substep slower (measured: 1.16x
    // with every phase spread, 1.8x with only the criterion, see the
    // checkpoint). The per-node phases therefore run on the calling thread,
    // which is also exactly what the serial backend does.
    template <typename Body>
    void forEach(std::uint32_t count, Body &&body) {
        forEachRange(0U, count, std::forward<Body>(body));
    }

    template <typename Body>
    void forEachRange(std::uint32_t begin, std::uint32_t end, Body &&body) {
        const std::uint32_t count = end > begin ? end - begin : 0U;
        if (count < kMinParallelItems || pool_.size() == 1) {
            for (std::uint32_t i = begin; i < end; ++i) body(i, 0U);
            return;
        }
        pool_.run([&](unsigned thread, unsigned threads) {
            const Slice slice = sliceOf(count, thread, threads);
            for (std::uint32_t i = begin + slice.begin; i < begin + slice.end; ++i) body(i, thread);
        });
    }

    // One substep; returns whether any bond failed. The phase order, the phase
    // numbering and every element call are CpuLatticeBackend's.
    bool advance() {
        const bool direct = S_.direct_arithmetic != 0;
        const std::uint32_t N = L_.node_count, B = L_.bond_count;
        phase_clock_ = std::chrono::steady_clock::now();
        if (dirty_start_) {
            forEach(N, [&](std::uint32_t i, unsigned thread) { nodeStrain(views_[thread], i, direct); });
            mark(1);
            forEach(B, [&](std::uint32_t j, unsigned thread) {
                if (L_.alive[j]) bondStartSample(views_[thread], j, direct);
            });
            mark(2);
            dirty_start_ = false;
        }
        // Kick and classify in parallel; the ordered candidate lists are built
        // by a serial scan of the flags, which is the order the serial backend
        // pushes them in.
        SphereState<Real> kicked = sphere_;
        kicked.velocity = kicked.velocity + S_.dt * S_.gravity;
        forEach(N, [&](std::uint32_t i, unsigned thread) {
            (void)nodeKickAndClassify(views_[thread], S_, kicked, i);
        });
        for (std::uint32_t block = 0; block < L_.block_count; ++block) {
            std::uint32_t count = 0;
            for (std::uint32_t i = L_.node_block_begin[block]; i < L_.node_block_begin[block + 1]; ++i) {
                if (!L_.candidate[i]) continue;
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
            // Serial: a colour stage is smaller than a barrier, and any other
            // split would change the sweep order.
            for (std::uint32_t block = 0; block < L_.block_count; ++block)
                sweep(block, 0U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            mark(5);
            for (std::uint32_t block = 0; block < L_.block_count; block += 2U)
                sweep(block, 1U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            for (std::uint32_t block = 1; block < L_.block_count; block += 2U)
                sweep(block, 1U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            mark(6);
            forEach(N, [&](std::uint32_t i, unsigned) { nodeSupportProject(L_, S_, i); });
            mark(7);
        }
        forEach(N, [&](std::uint32_t i, unsigned) { nodeVelocityUpdate(L_, S_, i); });
        mark(8);
        if (S_.damping_fraction > Real(0)) {
            sweepAll([&](std::uint32_t j) { bondDamp(L_, j, S_.damping_fraction, direct); });
            forEach(N, [&](std::uint32_t i, unsigned) {
                if (!L_.candidate[i]) nodeSupportVelocity(L_, S_, i);
            });
            mark(9);
        }
        if (S_.sphere_enabled) sphereContactPass(L_, S_, sphere_, 2, status_.contact);
        mark(10);
        forEach(N, [&](std::uint32_t i, unsigned thread) { nodeStrain(views_[thread], i, direct); });
        mark(11);
        for (Scratch &scratch : scratch_) {
            scratch.tensile = scratch.compressive = scratch.shear = 0.0F;
            scratch.breakages.clear();
        }
        forEach(B, [&](std::uint32_t j, unsigned thread) {
            if (!L_.alive[j]) return;
            const FailureOutcome out = bondEndSampleAndFailure(views_[thread], j, direct);
            Scratch &scratch = scratch_[thread];
            scratch.tensile = std::max(scratch.tensile, out.peak_tensile);
            scratch.compressive = std::max(scratch.compressive, out.peak_compressive);
            scratch.shear = std::max(scratch.shear, out.peak_shear);
            if (out.broke) scratch.breakages.push_back({j, out.removed_energy_j});
        });
        // Serial replay in bond index order: the slices are contiguous and
        // ascending, so concatenating them in thread order is bond index order,
        // which is the order the serial backend accumulates in.
        bool any_failed = false;
        for (const Scratch &scratch : scratch_) {
            status_.max_tensile_stretch = std::max(status_.max_tensile_stretch, scratch.tensile);
            status_.max_compressive_strain = std::max(status_.max_compressive_strain, scratch.compressive);
            status_.max_shear_strain = std::max(status_.max_shear_strain, scratch.shear);
        }
        for (const Scratch &scratch : scratch_) {
            for (const Breakage &broken : scratch.breakages) {
                any_failed = true;
                status_.removed_energy_j += broken.energy_j;
                ++status_.broken_bonds;
                L_.node_dirty[L_.bond_a[broken.bond]] = 1;
                L_.node_dirty[L_.bond_b[broken.bond]] = 1;
            }
        }
        mark(12);
        std::uint32_t disagreements = 0;
        for (const Scratch &scratch : scratch_) disagreements += scratch.degenerate;
        status_.degenerate_disagreements = disagreements;
        sphere_.center = sphere_.center + S_.dt * sphere_.velocity;
        sphereSupportContact(S_, sphere_, status_.contact);
        if (any_failed) dirty_start_ = true;
        mark(13);
        return any_failed;
    }

    std::chrono::steady_clock::time_point phase_clock_{};

    LatticeSchedule schedule_;
    SpinPool pool_;
    WorkingLattice<Real> working_;
    LatticeArrays<Real> L_{};
    std::vector<LatticeArrays<Real>> views_;
    std::vector<Scratch> scratch_;
    StepSettings<Real> S_{};
    SphereState<Real> sphere_{};
    RunStatus status_{};
    bool dirty_start_{true};
    std::vector<FrameCapture> frames_;
};

std::unique_ptr<LatticeBackend> makeParallelCpuLatticeBackendImpl(
    const LatticeSchedule &schedule, Precision precision, unsigned threads, unsigned spins) {
    if (threads == 0) threads = defaultLatticeThreadCount();
    if (spins == 0) spins = 100;
    if (precision == Precision::Float)
        return std::make_unique<ParallelCpuLatticeBackend<float>>(schedule, threads, spins);
    return std::make_unique<ParallelCpuLatticeBackend<double>>(schedule, threads, spins);
}

// Wall seconds for `dispatches` empty pool dispatches: the floor under any
// phase this backend can spread.
double measureDispatchCostImpl(unsigned threads, unsigned spins, unsigned dispatches) {
    SpinPool pool(threads, spins == 0 ? 400 : spins);
    const auto begin = std::chrono::steady_clock::now();
    for (unsigned d = 0; d < dispatches; ++d) pool.run([](unsigned, unsigned) {});
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
}

} // namespace

unsigned defaultLatticeThreadCount() {
    // Measured on the headline plate (24 logical threads): 2.38x at four,
    // 3.38x at eight, 3.68x at twelve, 3.89x at sixteen and 1.33x at
    // twenty-four, where the calling thread competes with a spinning worker for
    // its core. Sixteen is a cap, not a requirement.
    return std::min(16U, std::max(1U, std::thread::hardware_concurrency()));
}

std::unique_ptr<LatticeBackend> makeParallelCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision, unsigned threads, unsigned spins) {
    return makeParallelCpuLatticeBackendImpl(schedule, precision, threads, spins);
}

double measureParallelDispatchCost(unsigned threads, unsigned spins, unsigned dispatches) {
    return measureDispatchCostImpl(threads, spins, dispatches);
}

} // namespace banjo::fastlattice
