// Exact multithreaded CPU backend for the fast explicit lattice.
//
// This is CpuLatticeBackend.cpp phase for phase. It is not an approximation and
// not a different schedule: every element sees the same inputs and writes the
// same outputs, so the result is bit identical to the serial backend at every
// thread count, with and without the eight-wide kernels. These are the only
// places it differs at all, and why each changes no number:
//
//   * Independent elements are spread over a thread pool. The Gauss-Seidel
//     constraint sweep keeps its order: a colour stage is a set of bonds that
//     share no node, so a stage may be split, and the stages run one after
//     another. The sphere contact pass and the node-node narrow phase stay
//     serial, because every response changes what the next one sees.
//   * Reductions are order-independent or replayed in index order. The strain
//     peaks combine by max. The removed energy and the plastic work are summed
//     by a serial pass, in bond index order, over the bonds that broke or
//     flowed -- the serial backend's order, and its other addends are zeros.
//   * Some element results are kept instead of being worked out again: values
//     that are a fixed function of data that does not change during a run (a
//     bond's rest direction, its compliance over dt^2, whether its thresholds
//     are finite), computed once with exactly the expression the serial
//     element function evaluates. After a failure the start-of-substep sample
//     is redone only where a bond broke; everywhere else it reads the same
//     inputs as the end-of-substep sample it would repeat. Loops skip the
//     neighbour slots the serial functions visit only to add an exact zero
//     (padding past a node's degree, bonds already broken): those sums start
//     at +0 and adding +-0 leaves them unchanged. All of this is the same
//     number for every finite state; a state already at infinity or NaN can
//     differ only in how its NaN spreads.
//   * On x86-64 with AVX2, in single precision (the live world's lane), the
//     sweep, the end-of-substep strain and the bond failure test run eight
//     elements per instruction. Vector add, multiply, divide and square root
//     round each lane as the scalar instructions do, and the kernels write the
//     scalar expression trees out operation for operation with no fused
//     multiply-add (see "Eight at a time" below).
//
// The pool hands work out in chunks that the calling thread and any free
// worker claim from one counter, so a run never waits for a worker to turn up,
// and it holds back on a machine whose cores are already busy (WorkPool,
// PoolRegistry). Pools are shared by every backend in the process and their
// workers park when idle, so making a backend costs neither a thread start nor
// a probe.
//
// tests/fast_lattice_tests.cpp, tests/fracture_algo3_tests.cpp and
// tests/lattice_plasticity_tests.cpp assert the bit identity against the
// serial backend through fracture cascades, node contact and plastic flow, in
// both precisions.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"
#include "fastlattice/ExternalLoads.hpp"

#include <algorithm>
#include <atomic>
#include <cstdlib>
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#elif defined(__linux__)
#include <sched.h>
#endif
#include <cstdio>
#include <cstring>
#include <chrono>
#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

#if defined(_MSC_VER) && (defined(_M_X64) || defined(_M_IX86))
#include <immintrin.h>
#define BANJO_PAUSE() _mm_pause()
#elif defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>
#define BANJO_PAUSE() _mm_pause()
#else
#define BANJO_PAUSE() ((void)0)
#endif

// The eight-wide kernels (below) on x86-64. MSVC compiles AVX2 intrinsics in
// any function; GCC and Clang need the functions marked. Whether the
// processor running the code has AVX2 is asked at run time (avx2Available).
#if defined(__x86_64__) || defined(_M_X64)
#define BANJO_LATTICE_AVX2 1
#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#define BANJO_AVX2_TARGET
#else
#include <cpuid.h>
#define BANJO_AVX2_TARGET __attribute__((target("avx2")))
#endif
#else
#define BANJO_LATTICE_AVX2 0
#endif

namespace banjo::fastlattice {
namespace {

// ---------------------------------------------------------------------------
// The pool.
// ---------------------------------------------------------------------------
// A job is `chunks` independent pieces of work. The caller publishes it, then
// claims chunks from one counter alongside whichever workers are awake; when
// the counter runs out it waits only for chunks other threads are still
// working on. A chunk is claimed by one atomic increment, and a worker that
// arrives late -- even one that slept through several jobs -- can only ever
// claim a chunk of the job that is current when its increment lands, because
// the counter and the chunk count are one word.
//
// What a busy machine does to this. A worker the operating system takes off
// its core while it holds a chunk holds up the caller until it is put back --
// a scheduling quantum, 15 to 30 ms on Windows -- and on a machine with more
// runnable threads than cores that happens often enough to swamp the run:
// measured, an island that takes 0.9 s on one thread took 20 to 50 s on four
// or eight while other programs kept the cores busy, every second of the
// difference spent in a few thousand such waits. So each run is allowed only
// as many threads as the machine left idle before it (PoolRegistry), and the
// pool watches its own waits. A wait far longer than any chunk takes (kStall)
// can only be a preempted worker: it halves the threads allowed, and a wait
// of a whole quantum leaves the run to the caller alone. A long run of
// dispatches without one lets one more back in, and each cut makes the next
// return take twice as long. The count only ever decides who does the work,
// never what it comes to.
class WorkPool {
public:
    WorkPool(unsigned participants, unsigned spins)
        : count_(std::max(1U, participants)), spins_before_yield_(std::max(1U, spins)) {
        limit_.store(count_, std::memory_order_relaxed);
        for (unsigned t = 1; t < count_; ++t) workers_.emplace_back([this, t] { loop(t); });
    }

    ~WorkPool() {
        stop_.store(true, std::memory_order_seq_cst);
        seq_.fetch_add(1U, std::memory_order_seq_cst);
        seq_.notify_all();
        limit_.fetch_add(1U, std::memory_order_seq_cst);
        limit_.notify_all();
        for (std::thread &worker : workers_) worker.join();
    }

    WorkPool(const WorkPool &) = delete;
    WorkPool &operator=(const WorkPool &) = delete;

    [[nodiscard]] unsigned size() const { return count_; }

    // How many threads may take part in a dispatch, for a run about to start,
    // from what the machine has free.
    void allow(unsigned participants) {
        const unsigned limit = std::clamp(participants, 1U, count_);
        quiet_ = 0;
        if (limit_.exchange(limit, std::memory_order_seq_cst) < limit) limit_.notify_all();
    }

    // body(chunk, participant) once for every chunk in [0, chunks); the caller
    // is participant 0. Type-erased through a function pointer so a dispatch
    // never allocates.
    template <typename Body>
    void run(std::uint32_t chunks, Body &body) {
        if (chunks == 0U) return;
        if (count_ == 1U || chunks == 1U || limit_.load(std::memory_order_relaxed) <= 1U) {
            for (std::uint32_t c = 0; c < chunks; ++c) body(c, 0U);
            if (count_ != 1U) quiet();
            return;
        }
        argument_ = static_cast<void *>(&body);
        trampoline_ = [](void *argument, std::uint32_t chunk, unsigned participant) {
            (*static_cast<Body *>(argument))(chunk, participant);
        };
        finished_.store(0U, std::memory_order_relaxed);
        claim_.store(pack(chunks, 0U), std::memory_order_release);
        seq_.fetch_add(1U, std::memory_order_seq_cst);
        if (sleepers_.load(std::memory_order_seq_cst) != 0U) seq_.notify_all();
        std::uint32_t mine = 0;
        for (;;) {
            const std::uint64_t word = claim_.fetch_add(1U, std::memory_order_acq_rel);
            const std::uint32_t chunk = static_cast<std::uint32_t>(word);
            if (chunk >= chunks) break;
            body(chunk, 0U);
            ++mine;
        }
        const std::uint32_t others = chunks - mine;
        if (finished_.load(std::memory_order_acquire) == others) {
            quiet();
            return;
        }
        const auto waiting_since = std::chrono::steady_clock::now();
        unsigned spins = 0;
        while (finished_.load(std::memory_order_acquire) != others) {
            BANJO_PAUSE();
            if (++spins > spins_before_yield_) {
                std::this_thread::yield();
                spins = 0;
            }
        }
        const auto waited = std::chrono::steady_clock::now() - waiting_since;
        if (waited > kStall) stalled(waited);
        else quiet();
    }

private:
    static std::uint64_t pack(std::uint32_t chunks, std::uint32_t next) {
        return (static_cast<std::uint64_t>(chunks) << 32U) | next;
    }

    // Caller only: a dispatch that did not wait on a preempted worker.
    void quiet() {
        const unsigned limit = limit_.load(std::memory_order_relaxed);
        if (limit >= count_ || ++quiet_ < grow_after_) return;
        quiet_ = 0;
        grow_after_ = std::max(kGrowAfter, grow_after_ / 2U);
        limit_.store(limit + 1U, std::memory_order_seq_cst);
        limit_.notify_all();
    }

    // Caller only: a dispatch that did. A wait of a whole quantum or more
    // means the machine has no core to spare at all, and the rest of the run
    // goes on alone.
    void stalled(std::chrono::steady_clock::duration waited) {
        const unsigned limit = limit_.load(std::memory_order_relaxed);
        quiet_ = 0;
        if (waited > kQuantum) {
            grow_after_ = kGrowMost;
            limit_.store(1U, std::memory_order_seq_cst);
            return;
        }
        grow_after_ = std::min(kGrowMost, grow_after_ * 2U);
        limit_.store(std::max(1U, limit / 2U), std::memory_order_seq_cst);
    }

    void loop(unsigned index) {
        std::uint32_t seen = seq_.load(std::memory_order_acquire);
        for (;;) {
            // Not wanted at the moment: sleep until the allowance changes.
            for (unsigned limit = limit_.load(std::memory_order_seq_cst); index >= limit && !stop_.load();
                 limit = limit_.load(std::memory_order_seq_cst))
                limit_.wait(limit, std::memory_order_seq_cst);
            if (stop_.load(std::memory_order_acquire)) return;
            // Wait for a job: spin while jobs are coming thick and fast, as they
            // do inside a run, and park once none has come for a while, so a
            // pool between runs costs nothing.
            std::uint32_t now = seq_.load(std::memory_order_acquire);
            unsigned spins = 0, rounds = 0;
            auto idle_since = std::chrono::steady_clock::now();
            while (now == seen) {
                BANJO_PAUSE();
                if (++spins > spins_before_yield_) {
                    spins = 0;
                    std::this_thread::yield();
                    if ((++rounds & 15U) == 0U &&
                        std::chrono::steady_clock::now() - idle_since > kParkAfter) {
                        sleepers_.fetch_add(1U, std::memory_order_seq_cst);
                        if (seq_.load(std::memory_order_seq_cst) == seen && !stop_.load())
                            seq_.wait(seen, std::memory_order_seq_cst);
                        sleepers_.fetch_sub(1U, std::memory_order_seq_cst);
                        idle_since = std::chrono::steady_clock::now();
                    }
                }
                now = seq_.load(std::memory_order_acquire);
            }
            seen = now;
            if (stop_.load(std::memory_order_acquire)) return;
            if (index >= limit_.load(std::memory_order_relaxed)) continue;
            std::uint32_t done = 0;
            for (;;) {
                const std::uint64_t word = claim_.fetch_add(1U, std::memory_order_acq_rel);
                const std::uint32_t chunk = static_cast<std::uint32_t>(word);
                const std::uint32_t chunks = static_cast<std::uint32_t>(word >> 32U);
                if (chunk >= chunks) break;
                // The chunk is this job's and unfinished, so the job and its
                // body are still the ones published with it.
                trampoline_(argument_, chunk, index);
                ++done;
            }
            if (done != 0U) finished_.fetch_add(done, std::memory_order_release);
        }
    }

    // An idle worker parks after this long without a job.
    static constexpr std::chrono::microseconds kParkAfter{200};
    // Longer than any chunk takes on any core, by tens of times: only a
    // preempted worker makes the caller wait this long.
    static constexpr std::chrono::microseconds kStall{1000};
    // A wait this long is a whole scheduling quantum or more.
    static constexpr std::chrono::milliseconds kQuantum{5};
    // Dispatches without a stall before one more thread is let back in, at
    // first and at most (the most is longer than a large run).
    static constexpr unsigned kGrowAfter = 256;
    static constexpr unsigned kGrowMost = 1U << 16U;

    unsigned count_;
    unsigned spins_before_yield_;
    std::vector<std::thread> workers_;
    unsigned quiet_{0};
    unsigned grow_after_{kGrowAfter};
    // Separate cache lines: the workers spin on seq_ while the claims and the
    // completions hammer the other two.
    alignas(64) std::atomic<std::uint32_t> seq_{0};
    alignas(64) std::atomic<std::uint64_t> claim_{0};
    alignas(64) std::atomic<std::uint32_t> finished_{0};
    alignas(64) std::atomic<std::uint32_t> sleepers_{0};
    alignas(64) std::atomic<unsigned> limit_{1};
    std::atomic<bool> stop_{false};
    using Trampoline = void (*)(void *, std::uint32_t, unsigned);
    Trampoline trampoline_{nullptr};
    void *argument_{nullptr};
};

// The machine's processor time so far, all cores together: how much of it
// was idle, out of how much. Two readings give the cores that stood idle in
// between.
struct CpuClock {
    std::uint64_t idle{}, total{};
    bool ok{};
};

CpuClock readCpuClock() {
    CpuClock out;
#if defined(_WIN32)
    FILETIME idle, kernel, user;
    if (GetSystemTimes(&idle, &kernel, &user)) {
        const auto ticks = [](const FILETIME &t) {
            return (static_cast<std::uint64_t>(t.dwHighDateTime) << 32U) | t.dwLowDateTime;
        };
        // Kernel time includes the idle time.
        out.idle = ticks(idle);
        out.total = ticks(kernel) + ticks(user);
        out.ok = true;
    }
#elif defined(__linux__)
    if (std::FILE *f = std::fopen("/proc/stat", "r")) {
        unsigned long long v[8] = {};
        if (std::fscanf(f, "cpu %llu %llu %llu %llu %llu %llu %llu %llu", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5],
                        &v[6], &v[7]) >= 5) {
            out.idle = v[3] + v[4];
            for (unsigned long long x : v) out.total += x;
            out.ok = true;
        }
        std::fclose(f);
    }
#endif
    return out;
}

// The cores this process can actually run on. hardware_concurrency() counts
// the machine's, and that is not what a process gets: on Windows its affinity
// can be a subset, and in a Linux container (Render's, for one) the CPU quota
// is the limit while every core of the host is still listed. A pool sized from
// the host on a two-core quota is eight threads fighting over two cores, and
// the world's own thread with them.
unsigned usableCores() {
    unsigned cores = std::max(1U, std::thread::hardware_concurrency());
#if defined(_WIN32)
    DWORD_PTR process = 0, system = 0;
    if (GetProcessAffinityMask(GetCurrentProcess(), &process, &system) && process != 0) {
        unsigned count = 0;
        for (DWORD_PTR mask = process; mask != 0; mask &= mask - 1) ++count;
        cores = std::min(cores, count);
    }
#elif defined(__linux__)
    cpu_set_t set;
    CPU_ZERO(&set);
    if (sched_getaffinity(0, sizeof set, &set) == 0) {
        const int count = CPU_COUNT(&set);
        if (count > 0) cores = std::min(cores, static_cast<unsigned>(count));
    }
    // The quota: cgroup v2's cpu.max ("max 100000" when there is none), or
    // cgroup v1's quota and period.
    double quota = 0.0;
    if (std::FILE *f = std::fopen("/sys/fs/cgroup/cpu.max", "r")) {
        char limit[32] = {};
        double period = 0.0;
        if (std::fscanf(f, "%31s %lf", limit, &period) == 2 && std::strcmp(limit, "max") != 0 && period > 0.0)
            quota = std::strtod(limit, nullptr) / period;
        std::fclose(f);
    } else if (std::FILE *q = std::fopen("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r")) {
        double limit = -1.0, period = 0.0;
        if (std::fscanf(q, "%lf", &limit) != 1) limit = -1.0;
        std::fclose(q);
        if (std::FILE *r = std::fopen("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r")) {
            if (std::fscanf(r, "%lf", &period) != 1) period = 0.0;
            std::fclose(r);
        }
        if (limit > 0.0 && period > 0.0) quota = limit / period;
    }
    if (quota > 0.0) cores = std::min(cores, std::max(1U, static_cast<unsigned>(quota)));
#endif
    return cores;
}

// Read when the program starts, so the first run is sized from how busy the
// machine has been since then.
const CpuClock g_clock_at_start = readCpuClock();
const std::chrono::steady_clock::time_point g_time_at_start = std::chrono::steady_clock::now();

// Pools live for the process and are handed to one run at a time. A run that
// finds every pool of its size busy (two runs at once on different threads)
// gets a new one; the results do not depend on which pool, or how many of its
// threads, did the work.
class PoolRegistry {
public:
    struct Lease {
        WorkPool *pool{};
        std::atomic<bool> *busy{};
        Lease() = default;
        Lease(WorkPool *p, std::atomic<bool> *b) : pool(p), busy(b) {}
        Lease(const Lease &) = delete;
        Lease &operator=(const Lease &) = delete;
        Lease(Lease &&other) noexcept : pool(other.pool), busy(other.busy) { other.pool = nullptr; other.busy = nullptr; }
        Lease &operator=(Lease &&other) noexcept {
            if (this != &other) {
                if (busy) {
                    PoolRegistry::instance().released();
                    busy->store(false, std::memory_order_release);
                }
                pool = other.pool;
                busy = other.busy;
                other.pool = nullptr;
                other.busy = nullptr;
            }
            return *this;
        }
        ~Lease() {
            if (!busy) return;
            PoolRegistry::instance().released();
            busy->store(false, std::memory_order_release);
        }
    };

    static PoolRegistry &instance() {
        // Deliberately never destroyed: parked workers are reclaimed with the
        // process, and joining them from a static destructor can deadlock.
        static PoolRegistry *registry = new PoolRegistry();
        return *registry;
    }

    // A pool of `participants`, allowed as many of them as the machine had
    // cores standing idle since the last run ended -- three quarters of them,
    // plus the calling thread -- so a run on a machine that something else
    // already has busy does not start by fighting it for cores. The pool then
    // adjusts itself as the run goes (WorkPool).
    Lease acquire(unsigned participants, unsigned spins) {
        std::lock_guard<std::mutex> lock(mutex_);
        const CpuClock now = readCpuClock();
        if (now.ok && quiet_since_.ok && now.total > quiet_since_.total &&
            std::chrono::steady_clock::now() - quiet_since_at_ > kShortestWindow) {
            const double idle_share = static_cast<double>(now.idle - quiet_since_.idle) /
                                      static_cast<double>(now.total - quiet_since_.total);
            free_cores_ = std::clamp(idle_share, 0.0, 1.0) * static_cast<double>(hardwareThreads());
        }
        const unsigned allowed = 1U + static_cast<unsigned>(0.75 * free_cores_);
        for (Entry &entry : entries_) {
            if (entry.pool->size() != participants || entry.spins != spins) continue;
            bool expected = false;
            if (entry.busy->compare_exchange_strong(expected, true)) {
                entry.pool->allow(allowed);
                return Lease(entry.pool.get(), entry.busy.get());
            }
        }
        entries_.push_back({std::make_unique<WorkPool>(participants, spins), std::make_unique<std::atomic<bool>>(true), spins});
        entries_.back().pool->allow(allowed);
        return Lease(entries_.back().pool.get(), entries_.back().busy.get());
    }

    // A run has ended: the idle time from here to the next run's start is
    // what the machine has to spare, untouched by this process's own workers.
    void released() {
        std::lock_guard<std::mutex> lock(mutex_);
        quiet_since_ = readCpuClock();
        quiet_since_at_ = std::chrono::steady_clock::now();
    }

private:
    PoolRegistry() : quiet_since_(g_clock_at_start), quiet_since_at_(g_time_at_start) {}

    static unsigned hardwareThreads() { return std::max(1U, std::thread::hardware_concurrency()); }

    // Shorter than this between runs and the reading is mostly noise; the
    // last estimate stands.
    static constexpr std::chrono::milliseconds kShortestWindow{20};

    struct Entry {
        std::unique_ptr<WorkPool> pool;
        std::unique_ptr<std::atomic<bool>> busy;
        unsigned spins;
    };
    std::mutex mutex_;
    std::vector<Entry> entries_;
    CpuClock quiet_since_;
    std::chrono::steady_clock::time_point quiet_since_at_;
    // Until the machine has been watched for long enough, half of it.
    double free_cores_{0.5 * static_cast<double>(hardwareThreads())};
};

// ---------------------------------------------------------------------------
// Element functions with results kept.
// ---------------------------------------------------------------------------
// Each is the LatticePhysics.hpp function of the same name, with the same
// expressions in the same order; see the header comment for what is kept and
// why the answer is the same number.
template <typename Real>
struct ElementCache {
    // Per bond, fixed for the run.
    Real *direction{};            // 3B  rest_edge * (1 / |rest_edge|)
    std::uint8_t *has_direction{}; // B  |rest_edge| > 1e-9
    Real *alpha{};                // B   compliance / (dt * dt)
    Real *denominator{};          // B   inv_mass[a] + inv_mass[b] + alpha
    std::uint8_t *finite{};       // B   bit k: threshold k is finite
    // The same numbers again, one array per component, for the eight-wide
    // kernels: eight neighbouring bonds or slots are then one load instead of
    // a gather. Copies, so the values are the values.
    const Real *rest_edge[3]{};   // B each: rest_edge x, y, z
    const Real *direction_of[3]{}; // B each: direction x, y, z
    const Real *inv_mass_a{};     // B   inv_mass[bond_a]
    const Real *inv_mass_b{};     // B   inv_mass[bond_b]
    const Real *threshold_of[6]{}; // B each: threshold k
    const Real *nbr_rest_of[3]{}; // max_degree * N each: nbr_rest x, y, z
};

// nodeStrain's first half: the inverse rest covariance of the live
// neighbourhood, redone only when a bond at the node has broken.
template <typename Real>
void nodeRestCovariance(const LatticeArrays<Real> &L, std::uint32_t i) {
    const std::uint32_t N = L.node_count, D = L.max_degree;
    {
        Real rest_cov[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
        std::uint32_t live = 0;
        for (std::uint32_t k = 0; k < D; ++k) {
            const std::uint32_t slot = k * N + i;
            const std::uint32_t j = L.nbr_bond[slot];
            if (j == kNoBond) break;
            if (!L.nbr_alive[slot]) continue;
            const Real w = L.nbr_weight[slot];
            if (w <= Real(0)) continue;
            const V3<Real> r = load3(L.nbr_rest, slot);
            const Real rr[3] = {r.x, r.y, r.z};
            for (int row = 0; row < 3; ++row)
                for (int col = 0; col < 3; ++col)
                    rest_cov[row * 3 + col] += w * rr[row] * rr[col];
            ++live;
        }
        std::uint8_t valid = 0;
        if (live >= 1U) {
            Real inv[9], unmeasured[3];
            const int rank = symmetricPseudoInverse3(rest_cov, inv, unmeasured);
            if (rank >= 2) {
                for (int k = 0; k < 9; ++k) L.rinv[9 * i + k] = inv[k];
                for (int k = 0; k < 3; ++k) L.node_unmeasured[3 * i + k] = unmeasured[k];
                valid = 1;
            }
            if (rank < 3 && L.rank_deficient_nodes != nullptr) *L.rank_deficient_nodes += 1U;
        }
        L.node_valid[i] = valid;
        L.node_dirty[i] = 0;
    }
}

template <typename Real>
void nodeStrainKept(const LatticeArrays<Real> &L, std::uint32_t i, bool direct, Real plate_half_thickness,
                    Real plate_yield_stretch) {
    const std::uint32_t N = L.node_count, D = L.max_degree;
    if (L.node_dirty[i]) nodeRestCovariance(L, i);
    if (!L.node_valid[i]) return;

    Real acc[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
    const V3<Real> xi = direct ? position(L, i) : load3(L.u, i);
    for (std::uint32_t k = 0; k < D; ++k) {
        const std::uint32_t slot = k * N + i;
        if (L.nbr_bond[slot] == kNoBond) break;
        if (!L.nbr_alive[slot]) continue;
        const std::uint32_t other = L.nbr_other[slot];
        const Real w = L.nbr_weight[slot];
        const V3<Real> rest = load3(L.nbr_rest, slot);
        const V3<Real> xo = direct ? position(L, other) : load3(L.u, other);
        const V3<Real> cur = direct ? (xo - xi) - rest : xo - xi;
        const Real cc[3] = {cur.x, cur.y, cur.z};
        const Real rr[3] = {rest.x, rest.y, rest.z};
        for (int row = 0; row < 3; ++row)
            for (int col = 0; col < 3; ++col)
                acc[row * 3 + col] += w * cc[row] * rr[col];
    }
    const Real *inv = L.rinv + 9 * i;
    Real f[9];
    for (int row = 0; row < 3; ++row)
        for (int col = 0; col < 3; ++col) {
            Real s = Real(0);
            for (int k = 0; k < 3; ++k) s += acc[row * 3 + k] * inv[k * 3 + col];
            f[row * 3 + col] = s;
        }
    Real e[6];
    {
        const int rows[6] = {0, 1, 2, 0, 0, 1};
        const int cols[6] = {0, 1, 2, 1, 2, 2};
        for (int q = 0; q < 6; ++q) {
            Real c = Real(0);
            for (int k = 0; k < 3; ++k) c += f[k * 3 + rows[q]] * f[k * 3 + cols[q]];
            e[q] = Real(0.5) * (f[rows[q] * 3 + cols[q]] + f[cols[q] * 3 + rows[q]] + c);
        }
    }
    const Real un[3] = {L.node_unmeasured[3 * i], L.node_unmeasured[3 * i + 1],
                        L.node_unmeasured[3 * i + 2]};
    if (un[0] * un[0] + un[1] * un[1] + un[2] * un[2] > Real(0)) {
        const Real a[3] = {e[0] * un[0] + e[3] * un[1] + e[4] * un[2],
                           e[3] * un[0] + e[1] * un[1] + e[5] * un[2],
                           e[4] * un[0] + e[5] * un[1] + e[2] * un[2]};
        const Real s = a[0] * un[0] + a[1] * un[1] + a[2] * un[2];
        const int rows[6] = {0, 1, 2, 0, 0, 1};
        const int cols[6] = {0, 1, 2, 1, 2, 2};
        for (int q = 0; q < 6; ++q)
            e[q] += -un[rows[q]] * a[cols[q]] - a[rows[q]] * un[cols[q]] +
                    s * un[rows[q]] * un[cols[q]];
        if (plate_half_thickness > Real(0))
            plateBendingStrain(L, i, direct, plate_half_thickness, plate_yield_stretch, xi, e);
    }
    for (int q = 0; q < 6; ++q) L.strain[6 * i + q] = e[q];
}

// damageProgress with the finiteness of its two thresholds read from the
// bond's kept flags. isfinite is a library call on MSVC, made up to six times
// a bond a substep, on thresholds that never change during a run.
template <typename Real>
Real damageProgressKept(Real value, Real start, Real end, bool start_finite, bool end_finite) {
    if (!start_finite || value <= start) return Real(0);
    if (!end_finite || end <= start) return value > start ? Real(1) : Real(0);
    const Real p = (value - start) / (end - start);
    return p < Real(0) ? Real(0) : (p > Real(1) ? Real(1) : p);
}

template <typename Real>
void bondStrainSampleKept(const LatticeArrays<Real> &L, const ElementCache<Real> &C, std::uint32_t j,
                          bool direct, Real &tensile, Real &compressive, Real &shear) {
    const Real stretch = bondStretch(L, j, direct);
    tensile = stretch;
    compressive = -stretch;
    shear = Real(0);
    if (C.has_direction[j]) {
        const V3<Real> direction = load3(C.direction, j);
        const std::uint32_t ends[2] = {L.bond_a[j], L.bond_b[j]};
        for (int q = 0; q < 2; ++q) {
            const std::uint32_t n = ends[q];
            if (!L.node_valid[n]) continue;
            Real normal, sh;
            resolveAlongBond(L.strain + 6 * n, direction, normal, sh);
            tensile = maxR(tensile, normal);
            compressive = maxR(compressive, -normal);
            shear = maxR(shear, sh);
        }
    }
}

template <typename Real>
FailureOutcome bondEndSampleAndFailureKept(const LatticeArrays<Real> &L, const ElementCache<Real> &C,
                                           const StepSettings<Real> &S, std::uint32_t j, bool direct) {
    FailureOutcome out{false, 0.0, 0, 0.0F, 0.0F, 0.0F, 0.0, 0.0F, 0.0F};
    if (S.plastic_yield_stretch > Real(0)) {
        out.plastic_increment_j = static_cast<double>(bondPlasticReturn(L, S, j, direct));
        out.plastic_stretch = static_cast<float>(absR(L.plastic_extension[j]) / L.rest_length[j]);
    }
    Real tensile, compressive, shear;
    bondStrainSampleKept(L, C, j, direct, tensile, compressive, shear);
    const Real peak_t = maxR(Real(0), maxR(L.prev_tensile[j], tensile));
    const Real peak_c = maxR(Real(0), maxR(L.prev_compressive[j], compressive));
    const Real peak_s = maxR(Real(0), maxR(L.prev_shear[j], shear));
    out.peak_tensile = static_cast<float>(peak_t);
    out.peak_compressive = static_cast<float>(peak_c);
    out.peak_shear = static_cast<float>(peak_s);
    L.prev_tensile[j] = maxR(Real(0), tensile);
    L.prev_compressive[j] = maxR(Real(0), compressive);
    L.prev_shear[j] = maxR(Real(0), shear);

    const Real *t = L.threshold + 6 * j;
    const unsigned finite = C.finite[j];
    const Real tensile_damage = damageProgressKept(peak_t, t[0], t[1], (finite & 1U) != 0U, (finite & 2U) != 0U);
    const Real compressive_damage =
        damageProgressKept(peak_c, t[2], t[3], (finite & 4U) != 0U, (finite & 8U) != 0U);
    const Real shear_damage = damageProgressKept(peak_s, t[4], t[5], (finite & 16U) != 0U, (finite & 32U) != 0U);
    Real damage = tensile_damage;
    std::uint8_t mode = 1;
    if (compressive_damage > damage) { damage = compressive_damage; mode = 2; }
    if (shear_damage > damage) { damage = shear_damage; mode = 3; }
    if (damage > L.damage[j]) {
        L.damage[j] = damage;
        L.failure_mode[j] = mode;
    }
    out.damage = static_cast<float>(L.damage[j]);
    if (L.damage[j] >= Real(1)) {
        out.removed_energy_j = static_cast<double>(storedBondEnergy(L, j, direct));
        out.broke = true;
        out.mode = L.failure_mode[j];
        L.alive[j] = 0;
        L.nbr_alive[L.bond_slot_a[j]] = 0;
        L.nbr_alive[L.bond_slot_b[j]] = 0;
    }
    return out;
}

template <typename Real>
void bondStartSampleKept(const LatticeArrays<Real> &L, const ElementCache<Real> &C, std::uint32_t j, bool direct) {
    Real tensile, compressive, shear;
    bondStrainSampleKept(L, C, j, direct, tensile, compressive, shear);
    L.prev_tensile[j] = maxR(Real(0), tensile);
    L.prev_compressive[j] = maxR(Real(0), compressive);
    L.prev_shear[j] = maxR(Real(0), shear);
}

template <typename Real>
void bondSolveKept(const LatticeArrays<Real> &L, const ElementCache<Real> &C, std::uint32_t j, bool direct,
                   bool first_iteration) {
    if (!L.alive[j]) return;
    const std::uint32_t a = L.bond_a[j], b = L.bond_b[j];
    const V3<Real> delta = bondVector(L, j, direct);
    const Real current_length = length(delta);
    if (current_length <= Real(1.0e-12)) return;
    const Real original_rest = L.rest_length[j];
    const Real plastic = L.plastic_extension[j];
    const Real rest = original_rest + plastic;
    Real constraint;
    if (direct) {
        constraint = current_length - rest;
    } else {
        const V3<Real> du = load3(L.u, b) - load3(L.u, a);
        const V3<Real> r = load3(L.rest_edge, j);
        constraint = (L.rest_length_sq_minus[j] + Real(2) * dot(r, du) + dot(du, du) -
                      plastic * (rest + original_rest)) /
                     (current_length + rest);
    }
    const V3<Real> direction = delta / current_length;
    const Real wa = L.inv_mass[a], wb = L.inv_mass[b];
    const Real alpha = C.alpha[j];
    const Real lambda = first_iteration ? Real(0) : L.accumulated_lambda[j];
    const Real delta_lambda = (-constraint - alpha * lambda) / C.denominator[j];
    L.accumulated_lambda[j] = lambda + delta_lambda;
    store3(L.u, a, load3(L.u, a) - wa * delta_lambda * direction);
    store3(L.u, b, load3(L.u, b) + wb * delta_lambda * direction);
}

// One bond that failed, or flowed, in a substep, kept so the serial replay can
// add its energy in bond index order.
struct Breakage {
    std::uint32_t bond;
    double energy_j;
};

// ---------------------------------------------------------------------------
// Eight at a time (x86-64 with AVX2, single precision, displacement
// arithmetic -- the live world's lane).
// ---------------------------------------------------------------------------
// The same element functions again, eight bonds or eight nodes per step. A
// vector add, multiply, divide or square root rounds each lane exactly as the
// scalar instruction does, so writing the scalar expression tree out operation
// for operation -- same operands, same association, no fused multiply-add --
// gives every lane the scalar answer bit for bit. Lanes the scalar code would
// leave alone (a dead bond, a node with no strain) are masked and written
// back unchanged. Anything rare or awkward -- a bond that breaks, the last
// few elements of a range, plasticity, plate bending -- goes through the
// scalar function itself.
#if BANJO_LATTICE_AVX2

bool cpuHasAvx2() {
#if defined(_MSC_VER) && !defined(__clang__)
    int info[4];
    __cpuid(info, 0);
    if (info[0] < 7) return false;
    __cpuid(info, 1);
    const bool osxsave = (info[2] & (1 << 27)) != 0, avx = (info[2] & (1 << 28)) != 0;
    if (!osxsave || !avx) return false;
    if ((_xgetbv(0) & 6U) != 6U) return false;
    __cpuidex(info, 7, 0);
    return (info[1] & (1 << 5)) != 0;
#else
    __builtin_cpu_init();
    return __builtin_cpu_supports("avx2");
#endif
}

bool avx2Available() {
    static const bool available = [] {
        const char *switch_off = std::getenv("BANJO_LATTICE_SIMD");
        if (switch_off != nullptr && switch_off[0] == '0') return false;
        return cpuHasAvx2();
    }();
    return available;
}

namespace v8 {
BANJO_AVX2_TARGET inline __m256 add(__m256 a, __m256 b) { return _mm256_add_ps(a, b); }
BANJO_AVX2_TARGET inline __m256 sub(__m256 a, __m256 b) { return _mm256_sub_ps(a, b); }
BANJO_AVX2_TARGET inline __m256 mul(__m256 a, __m256 b) { return _mm256_mul_ps(a, b); }
BANJO_AVX2_TARGET inline __m256 div(__m256 a, __m256 b) { return _mm256_div_ps(a, b); }
BANJO_AVX2_TARGET inline __m256 neg(__m256 a) { return _mm256_xor_ps(a, _mm256_set1_ps(-0.0f)); }
// maxR(a, b) = (a < b) ? b : a, lane by lane.
BANJO_AVX2_TARGET inline __m256 maxR8(__m256 a, __m256 b) {
    return _mm256_blendv_ps(a, b, _mm256_cmp_ps(a, b, _CMP_LT_OQ));
}
BANJO_AVX2_TARGET inline __m256 gather(const float *base, __m256i index) {
    return _mm256_i32gather_ps(base, index, 4);
}
// Lanes whose byte flag is nonzero, as an all-ones mask.
BANJO_AVX2_TARGET inline __m256 byteMask(const std::uint8_t *flags) {
    const __m128i bytes = _mm_loadl_epi64(reinterpret_cast<const __m128i *>(flags));
    const __m256i wide = _mm256_cvtepu8_epi32(bytes);
    return _mm256_castsi256_ps(_mm256_cmpgt_epi32(wide, _mm256_setzero_si256()));
}
// dot(a, b) = a.x * b.x + a.y * b.y + a.z * b.z
BANJO_AVX2_TARGET inline __m256 dot3(__m256 ax, __m256 ay, __m256 az, __m256 bx, __m256 by, __m256 bz) {
    return add(add(mul(ax, bx), mul(ay, by)), mul(az, bz));
}
} // namespace v8

// bondSolveKept over one colour stage [begin, end).
BANJO_AVX2_TARGET void bondSolveRange8(const LatticeArrays<float> &L, const ElementCache<float> &C,
                                       std::uint32_t begin, std::uint32_t end, bool first_iteration) {
    using namespace v8;
    const __m256 tiny = _mm256_set1_ps(1.0e-12f), two = _mm256_set1_ps(2.0f);
    const __m256i three = _mm256_set1_epi32(3);
    alignas(32) float ax[8], ay[8], az[8], bx[8], by[8], bz[8];
    alignas(32) std::uint32_t ia[8], ib[8];
    std::uint32_t j = begin;
    for (; j + 8U <= end; j += 8U) {
        const __m256 alive = byteMask(L.alive + j);
        if (_mm256_movemask_ps(alive) == 0) continue;
        const __m256i a = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(L.bond_a + j));
        const __m256i b = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(L.bond_b + j));
        const __m256i a3 = _mm256_mullo_epi32(a, three), b3 = _mm256_mullo_epi32(b, three);
        const __m256 uax = gather(L.u, a3), uay = gather(L.u + 1, a3), uaz = gather(L.u + 2, a3);
        const __m256 ubx = gather(L.u, b3), uby = gather(L.u + 1, b3), ubz = gather(L.u + 2, b3);
        const __m256 rx = _mm256_loadu_ps(C.rest_edge[0] + j), ry = _mm256_loadu_ps(C.rest_edge[1] + j),
                     rz = _mm256_loadu_ps(C.rest_edge[2] + j);
        // bondVector: rest_edge + (u[b] - u[a])
        const __m256 dux = sub(ubx, uax), duy = sub(uby, uay), duz = sub(ubz, uaz);
        const __m256 dx = add(rx, dux), dy = add(ry, duy), dz = add(rz, duz);
        const __m256 length = _mm256_sqrt_ps(dot3(dx, dy, dz, dx, dy, dz));
        // if (current_length <= 1e-12) return;
        const __m256 active = _mm256_and_ps(alive, _mm256_cmp_ps(length, tiny, _CMP_NLE_UQ));
        const int act = _mm256_movemask_ps(active);
        if (act == 0) continue;
        const __m256 original_rest = _mm256_loadu_ps(L.rest_length + j);
        const __m256 plastic = _mm256_loadu_ps(L.plastic_extension + j);
        const __m256 rest = add(original_rest, plastic);
        const __m256 numerator =
            sub(add(add(_mm256_loadu_ps(L.rest_length_sq_minus + j), mul(two, dot3(rx, ry, rz, dux, duy, duz))),
                    dot3(dux, duy, duz, dux, duy, duz)),
                mul(plastic, add(rest, original_rest)));
        const __m256 constraint = div(numerator, add(length, rest));
        const __m256 nx = div(dx, length), ny = div(dy, length), nz = div(dz, length);
        const __m256 alpha = _mm256_loadu_ps(C.alpha + j);
        const __m256 lambda = first_iteration ? _mm256_setzero_ps() : _mm256_loadu_ps(L.accumulated_lambda + j);
        const __m256 delta_lambda =
            div(sub(neg(constraint), mul(alpha, lambda)), _mm256_loadu_ps(C.denominator + j));
        const __m256 kept = _mm256_loadu_ps(L.accumulated_lambda + j);
        _mm256_storeu_ps(L.accumulated_lambda + j, _mm256_blendv_ps(kept, add(lambda, delta_lambda), active));
        const __m256 wa = _mm256_loadu_ps(C.inv_mass_a + j), wb = _mm256_loadu_ps(C.inv_mass_b + j);
        // u[a] - (wa * delta_lambda) * direction, u[b] + (wb * delta_lambda) * direction
        const __m256 sa = mul(wa, delta_lambda), sb = mul(wb, delta_lambda);
        _mm256_store_ps(ax, sub(uax, mul(nx, sa)));
        _mm256_store_ps(ay, sub(uay, mul(ny, sa)));
        _mm256_store_ps(az, sub(uaz, mul(nz, sa)));
        _mm256_store_ps(bx, add(ubx, mul(nx, sb)));
        _mm256_store_ps(by, add(uby, mul(ny, sb)));
        _mm256_store_ps(bz, add(ubz, mul(nz, sb)));
        _mm256_store_si256(reinterpret_cast<__m256i *>(ia), a);
        _mm256_store_si256(reinterpret_cast<__m256i *>(ib), b);
        for (int k = 0; k < 8; ++k) {
            if (!(act & (1 << k))) continue;
            float *pa = L.u + 3U * ia[k];
            pa[0] = ax[k]; pa[1] = ay[k]; pa[2] = az[k];
            float *pb = L.u + 3U * ib[k];
            pb[0] = bx[k]; pb[1] = by[k]; pb[2] = bz[k];
        }
    }
    _mm256_zeroupper();
    for (; j < end; ++j) bondSolveKept(L, C, j, false, first_iteration);
}

// bondEndSampleAndFailureKept over the live bonds of [begin, end). The peaks,
// the damage and the plastic stretch of every live bond go into the running
// maxima; a bond that breaks is finished by the scalar code and listed, and so
// is the plastic work of every bond that flowed.
struct BondEndTally {
    float tensile{}, compressive{}, shear{}, damage{}, plastic{};
};

// damageProgressKept for mode `mode` (0 tension, 1 compression, 2 shear) of
// eight bonds whose threshold rows start at index `row6`.
BANJO_AVX2_TARGET inline __m256 damageProgress8(const ElementCache<float> &C, std::uint32_t j, __m256i finite_bits,
                                                __m256 value, int mode) {
    using namespace v8;
    const __m256 zero = _mm256_setzero_ps(), one = _mm256_set1_ps(1.0f);
    const __m256 all = _mm256_castsi256_ps(_mm256_set1_epi32(-1));
    const __m256 start = _mm256_loadu_ps(C.threshold_of[2 * mode] + j);
    const __m256 stop = _mm256_loadu_ps(C.threshold_of[2 * mode + 1] + j);
    const __m256i bit_start = _mm256_set1_epi32(1 << (2 * mode)), bit_stop = _mm256_set1_epi32(2 << (2 * mode));
    const __m256 start_finite =
        _mm256_castsi256_ps(_mm256_cmpeq_epi32(_mm256_and_si256(finite_bits, bit_start), bit_start));
    const __m256 stop_finite =
        _mm256_castsi256_ps(_mm256_cmpeq_epi32(_mm256_and_si256(finite_bits, bit_stop), bit_stop));
    // !start_finite || value <= start: 0
    const __m256 none = _mm256_or_ps(_mm256_andnot_ps(start_finite, all), _mm256_cmp_ps(value, start, _CMP_LE_OQ));
    // !end_finite || end <= start: value > start ? 1 : 0
    const __m256 step = _mm256_or_ps(_mm256_andnot_ps(stop_finite, all), _mm256_cmp_ps(stop, start, _CMP_LE_OQ));
    const __m256 stepped = _mm256_and_ps(_mm256_cmp_ps(value, start, _CMP_GT_OQ), one);
    // Most bonds are undamaged in most modes; the division is only needed
    // where a lane is neither.
    if (_mm256_movemask_ps(_mm256_andnot_ps(_mm256_or_ps(none, step), all)) == 0)
        return _mm256_blendv_ps(stepped, zero, none);
    // p < 0 ? 0 : (p > 1 ? 1 : p)
    const __m256 p = div(sub(value, start), sub(stop, start));
    __m256 clamped = _mm256_blendv_ps(p, one, _mm256_cmp_ps(p, one, _CMP_GT_OQ));
    clamped = _mm256_blendv_ps(clamped, zero, _mm256_cmp_ps(p, zero, _CMP_LT_OQ));
    const __m256 out = _mm256_blendv_ps(clamped, stepped, step);
    return _mm256_blendv_ps(out, zero, none);
}

BANJO_AVX2_TARGET void bondEndRange8(const LatticeArrays<float> &L, const ElementCache<float> &C,
                                     const StepSettings<float> &S, std::uint32_t begin, std::uint32_t end,
                                     BondEndTally &tally, std::vector<Breakage> &breakages,
                                     std::vector<Breakage> &flows) {
    using namespace v8;
    const __m256 zero = _mm256_setzero_ps(), one = _mm256_set1_ps(1.0f), two = _mm256_set1_ps(2.0f);
    const __m256 half = _mm256_set1_ps(0.5f);
    const __m256i three = _mm256_set1_epi32(3), six = _mm256_set1_epi32(6);
    const bool plastic = S.plastic_yield_stretch > 0.0f;
    const __m256 yield_stretch = _mm256_set1_ps(S.plastic_yield_stretch);
    const __m256 hardening = _mm256_set1_ps(S.plastic_hardening);
    const __m256 one_plus_hardening = _mm256_set1_ps(1.0f + S.plastic_hardening);
    __m256 most_t = zero, most_c = zero, most_s = zero, most_d = zero, most_p = zero;
    alignas(32) float work_of[8];
    alignas(32) std::uint32_t ia[8], ib[8];
    alignas(32) float mode_of[8], broke_of[8];
    alignas(32) std::int32_t valid_a[8], valid_b[8], finite[8];
    std::uint32_t j = begin;
    for (; j + 8U <= end; j += 8U) {
        const __m256 alive = byteMask(L.alive + j);
        const int live = _mm256_movemask_ps(alive);
        if (live == 0) continue;
        const __m256i a = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(L.bond_a + j));
        const __m256i b = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(L.bond_b + j));
        _mm256_store_si256(reinterpret_cast<__m256i *>(ia), a);
        _mm256_store_si256(reinterpret_cast<__m256i *>(ib), b);
        const __m256i a3 = _mm256_mullo_epi32(a, three), b3 = _mm256_mullo_epi32(b, three);

        // bondStretch, displacement form.
        const __m256 dux = sub(gather(L.u, b3), gather(L.u, a3));
        const __m256 duy = sub(gather(L.u + 1, b3), gather(L.u + 1, a3));
        const __m256 duz = sub(gather(L.u + 2, b3), gather(L.u + 2, a3));
        const __m256 rx = _mm256_loadu_ps(C.rest_edge[0] + j), ry = _mm256_loadu_ps(C.rest_edge[1] + j),
                     rz = _mm256_loadu_ps(C.rest_edge[2] + j);
        const __m256 dx = add(rx, dux), dy = add(ry, duy), dz = add(rz, duz);
        const __m256 len = _mm256_sqrt_ps(dot3(dx, dy, dz, dx, dy, dz));
        const __m256 rest = _mm256_loadu_ps(L.rest_length + j);
        const __m256 len2_minus_rest2 =
            add(add(_mm256_loadu_ps(L.rest_length_sq_minus + j), mul(two, dot3(rx, ry, rz, dux, duy, duz))),
                dot3(dux, duy, duz, dux, duy, duz));
        // bondPlasticReturn, before the sample as the scalar code has it. Its
        // elastic extension is length(bondVector) - rest_length -
        // plastic_extension, and that length is `len`.
        if (plastic) {
            const __m256 plastic_extension = _mm256_loadu_ps(L.plastic_extension + j);
            const __m256 plastic_strain = _mm256_loadu_ps(L.plastic_strain + j);
            const __m256 elastic = sub(sub(len, rest), plastic_extension);
            const __m256 shortened = _mm256_cmp_ps(elastic, zero, _CMP_LT_OQ);
            const __m256 magnitude = _mm256_blendv_ps(elastic, neg(elastic), shortened);
            const __m256 yield_extension = add(mul(yield_stretch, rest), mul(hardening, plastic_strain));
            const __m256 flowing = _mm256_and_ps(alive, _mm256_cmp_ps(magnitude, yield_extension, _CMP_GT_OQ));
            __m256 extension_now = plastic_extension;
            const int flowed = _mm256_movemask_ps(flowing);
            if (flowed != 0) {
                const __m256 increment = div(sub(magnitude, yield_extension), one_plus_hardening);
                extension_now = _mm256_blendv_ps(
                    plastic_extension,
                    add(plastic_extension, _mm256_blendv_ps(increment, neg(increment), shortened)), flowing);
                _mm256_storeu_ps(L.plastic_extension + j, extension_now);
                _mm256_storeu_ps(L.plastic_strain + j,
                                 _mm256_blendv_ps(plastic_strain, add(plastic_strain, increment), flowing));
                // 0.5 * (yield + yield_end) * increment / c, for c > 0.
                const __m256 compliance = _mm256_loadu_ps(L.compliance + j);
                const __m256 yield_end = add(yield_extension, mul(hardening, increment));
                const __m256 work = div(mul(mul(half, add(yield_extension, yield_end)), increment), compliance);
                const int paid = flowed & _mm256_movemask_ps(_mm256_cmp_ps(compliance, zero, _CMP_GT_OQ));
                if (paid != 0) {
                    _mm256_store_ps(work_of, work);
                    for (int k = 0; k < 8; ++k)
                        if ((paid & (1 << k)) && work_of[k] != 0.0f)
                            flows.push_back({j + static_cast<std::uint32_t>(k), static_cast<double>(work_of[k])});
                }
            }
            // absR(plastic_extension) / rest_length
            const __m256 stretch_now =
                div(_mm256_blendv_ps(extension_now, neg(extension_now), _mm256_cmp_ps(extension_now, zero, _CMP_LT_OQ)),
                    rest);
            most_p = _mm256_blendv_ps(most_p, maxR8(most_p, stretch_now), alive);
        }
        const __m256 stretch = div(len2_minus_rest2, mul(add(len, rest), rest));
        __m256 tensile = stretch, compressive = neg(stretch), shear = zero;
        // The strain at either end, resolved along the rest direction.
        const __m256 has_direction = byteMask(C.has_direction + j);
        if (_mm256_movemask_ps(has_direction) != 0) {
            const __m256 ex = _mm256_loadu_ps(C.direction_of[0] + j), ey = _mm256_loadu_ps(C.direction_of[1] + j),
                         ez = _mm256_loadu_ps(C.direction_of[2] + j);
            for (int k = 0; k < 8; ++k) {
                valid_a[k] = L.node_valid[ia[k]] ? -1 : 0;
                valid_b[k] = L.node_valid[ib[k]] ? -1 : 0;
            }
            for (int q = 0; q < 2; ++q) {
                const __m256 valid = _mm256_and_ps(
                    has_direction,
                    _mm256_castsi256_ps(_mm256_load_si256(reinterpret_cast<const __m256i *>(q == 0 ? valid_a : valid_b))));
                if (_mm256_movemask_ps(valid) == 0) continue;
                const __m256i n6 = _mm256_mullo_epi32(q == 0 ? a : b, six);
                const __m256 e0 = gather(L.strain, n6), e1 = gather(L.strain + 1, n6), e2 = gather(L.strain + 2, n6);
                const __m256 e3 = gather(L.strain + 3, n6), e4 = gather(L.strain + 4, n6), e5 = gather(L.strain + 5, n6);
                // resolveAlongBond
                const __m256 tx = add(add(mul(e0, ex), mul(e3, ey)), mul(e4, ez));
                const __m256 ty = add(add(mul(e3, ex), mul(e1, ey)), mul(e5, ez));
                const __m256 tz = add(add(mul(e4, ex), mul(e5, ey)), mul(e2, ez));
                const __m256 normal = dot3(ex, ey, ez, tx, ty, tz);
                const __m256 sx = sub(tx, mul(ex, normal)), sy = sub(ty, mul(ey, normal)), sz = sub(tz, mul(ez, normal));
                const __m256 sh = _mm256_sqrt_ps(dot3(sx, sy, sz, sx, sy, sz));
                tensile = _mm256_blendv_ps(tensile, maxR8(tensile, normal), valid);
                compressive = _mm256_blendv_ps(compressive, maxR8(compressive, neg(normal)), valid);
                shear = _mm256_blendv_ps(shear, maxR8(shear, sh), valid);
            }
        }
        const __m256 prev_t = _mm256_loadu_ps(L.prev_tensile + j);
        const __m256 prev_c = _mm256_loadu_ps(L.prev_compressive + j);
        const __m256 prev_s = _mm256_loadu_ps(L.prev_shear + j);
        const __m256 peak_t = maxR8(zero, maxR8(prev_t, tensile));
        const __m256 peak_c = maxR8(zero, maxR8(prev_c, compressive));
        const __m256 peak_s = maxR8(zero, maxR8(prev_s, shear));
        _mm256_storeu_ps(L.prev_tensile + j, _mm256_blendv_ps(prev_t, maxR8(zero, tensile), alive));
        _mm256_storeu_ps(L.prev_compressive + j, _mm256_blendv_ps(prev_c, maxR8(zero, compressive), alive));
        _mm256_storeu_ps(L.prev_shear + j, _mm256_blendv_ps(prev_s, maxR8(zero, shear), alive));
        // damageProgressKept for the three modes.
        for (int k = 0; k < 8; ++k) finite[k] = C.finite[j + static_cast<std::uint32_t>(k)];
        const __m256i finite_bits = _mm256_load_si256(reinterpret_cast<const __m256i *>(finite));
        const __m256 tensile_damage = damageProgress8(C, j, finite_bits, peak_t, 0);
        const __m256 compressive_damage = damageProgress8(C, j, finite_bits, peak_c, 1);
        const __m256 shear_damage = damageProgress8(C, j, finite_bits, peak_s, 2);
        __m256 damage = tensile_damage, mode = one;
        const __m256 c_wins = _mm256_cmp_ps(compressive_damage, damage, _CMP_GT_OQ);
        damage = _mm256_blendv_ps(damage, compressive_damage, c_wins);
        mode = _mm256_blendv_ps(mode, _mm256_set1_ps(2.0f), c_wins);
        const __m256 s_wins = _mm256_cmp_ps(shear_damage, damage, _CMP_GT_OQ);
        damage = _mm256_blendv_ps(damage, shear_damage, s_wins);
        mode = _mm256_blendv_ps(mode, _mm256_set1_ps(3.0f), s_wins);
        const __m256 old_damage = _mm256_loadu_ps(L.damage + j);
        const __m256 rises = _mm256_and_ps(alive, _mm256_cmp_ps(damage, old_damage, _CMP_GT_OQ));
        const __m256 now_damage = _mm256_blendv_ps(old_damage, damage, rises);
        _mm256_storeu_ps(L.damage + j, now_damage);
        const int rose = _mm256_movemask_ps(rises);
        if (rose != 0) {
            _mm256_store_ps(mode_of, mode);
            for (int k = 0; k < 8; ++k)
                if (rose & (1 << k)) L.failure_mode[j + static_cast<std::uint32_t>(k)] = static_cast<std::uint8_t>(mode_of[k]);
        }
        // The running maxima, over the live lanes only.
        most_t = _mm256_blendv_ps(most_t, maxR8(most_t, peak_t), alive);
        most_c = _mm256_blendv_ps(most_c, maxR8(most_c, peak_c), alive);
        most_s = _mm256_blendv_ps(most_s, maxR8(most_s, peak_s), alive);
        most_d = _mm256_blendv_ps(most_d, maxR8(most_d, now_damage), alive);
        const int broke = _mm256_movemask_ps(_mm256_and_ps(alive, _mm256_cmp_ps(now_damage, one, _CMP_GE_OQ)));
        if (broke != 0) {
            _mm256_store_ps(broke_of, now_damage);
            for (int k = 0; k < 8; ++k) {
                if (!(broke & (1 << k))) continue;
                const std::uint32_t bond = j + static_cast<std::uint32_t>(k);
                breakages.push_back({bond, static_cast<double>(storedBondEnergy(L, bond, false))});
                L.alive[bond] = 0;
                L.nbr_alive[L.bond_slot_a[bond]] = 0;
                L.nbr_alive[L.bond_slot_b[bond]] = 0;
            }
        }
    }
    alignas(32) float lane_t[8], lane_c[8], lane_s[8], lane_d[8], lane_p[8];
    _mm256_store_ps(lane_t, most_t);
    _mm256_store_ps(lane_c, most_c);
    _mm256_store_ps(lane_s, most_s);
    _mm256_store_ps(lane_d, most_d);
    _mm256_store_ps(lane_p, most_p);
    _mm256_zeroupper();
    for (int k = 0; k < 8; ++k) {
        tally.tensile = std::max(tally.tensile, lane_t[k]);
        tally.compressive = std::max(tally.compressive, lane_c[k]);
        tally.shear = std::max(tally.shear, lane_s[k]);
        tally.damage = std::max(tally.damage, lane_d[k]);
        tally.plastic = std::max(tally.plastic, lane_p[k]);
    }
    for (; j < end; ++j) {
        if (!L.alive[j]) continue;
        const FailureOutcome out = bondEndSampleAndFailureKept(L, C, S, j, false);
        tally.tensile = std::max(tally.tensile, out.peak_tensile);
        tally.compressive = std::max(tally.compressive, out.peak_compressive);
        tally.shear = std::max(tally.shear, out.peak_shear);
        tally.damage = std::max(tally.damage, out.damage);
        tally.plastic = std::max(tally.plastic, out.plastic_stretch);
        if (plastic && out.plastic_increment_j != 0.0) flows.push_back({j, out.plastic_increment_j});
        if (out.broke) breakages.push_back({j, out.removed_energy_j});
    }
}

// nodeStrainKept for the nodes [begin, end), eight neighbouring nodes at a
// time: slot k of eight consecutive nodes is eight consecutive entries of the
// k-major neighbour lists. No plate bending (the caller sends those to the
// scalar code).
BANJO_AVX2_TARGET void nodeStrainRange8(const LatticeArrays<float> &L, const ElementCache<float> &C,
                                        std::uint32_t begin, std::uint32_t end) {
    using namespace v8;
    const std::uint32_t N = L.node_count, D = L.max_degree;
    const __m256 zero = _mm256_setzero_ps(), half = _mm256_set1_ps(0.5f);
    const __m256i three = _mm256_set1_epi32(3), nine = _mm256_set1_epi32(9);
    const __m256i lanes = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
    const __m256i no_bond = _mm256_set1_epi32(static_cast<int>(kNoBond));
    alignas(32) float out[6][8];
    std::uint32_t i = begin;
    for (; i + 8U <= end; i += 8U) {
        for (std::uint32_t k = 0; k < 8U; ++k)
            if (L.node_dirty[i + k]) nodeRestCovariance(L, i + k);
        const __m256 valid = byteMask(L.node_valid + i);
        const int any_valid = _mm256_movemask_ps(valid);
        if (any_valid == 0) continue;
        const __m256i ii = _mm256_add_epi32(_mm256_set1_epi32(static_cast<int>(i)), lanes);
        const __m256i i3 = _mm256_mullo_epi32(ii, three);
        const __m256 xix = gather(L.u, i3), xiy = gather(L.u + 1, i3), xiz = gather(L.u + 2, i3);
        __m256 acc[9] = {zero, zero, zero, zero, zero, zero, zero, zero, zero};
        for (std::uint32_t k = 0; k < D; ++k) {
            const std::uint32_t base = k * N + i;
            const __m256i bond = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(L.nbr_bond + base));
            const __m256 present = _mm256_castsi256_ps(
                _mm256_xor_si256(_mm256_cmpeq_epi32(bond, no_bond), _mm256_set1_epi32(-1)));
            if (_mm256_movemask_ps(present) == 0) break;
            const __m256 use = _mm256_and_ps(present, byteMask(L.nbr_alive + base));
            if (_mm256_movemask_ps(use) == 0) continue;
            const __m256i other3 =
                _mm256_mullo_epi32(_mm256_loadu_si256(reinterpret_cast<const __m256i *>(L.nbr_other + base)), three);
            const __m256 w = _mm256_loadu_ps(L.nbr_weight + base);
            const __m256 rest[3] = {_mm256_loadu_ps(C.nbr_rest_of[0] + base), _mm256_loadu_ps(C.nbr_rest_of[1] + base),
                                    _mm256_loadu_ps(C.nbr_rest_of[2] + base)};
            const __m256 cur[3] = {sub(gather(L.u, other3), xix), sub(gather(L.u + 1, other3), xiy),
                                   sub(gather(L.u + 2, other3), xiz)};
            // A lane this slot does not count in gets weight zero, so it adds
            // an exact zero: the same as the scalar code's skip, because the
            // sums start at +0 and adding +-0 leaves any of them unchanged.
            const __m256 counted = _mm256_and_ps(w, use);
            for (int row = 0; row < 3; ++row) {
                const __m256 wc = mul(counted, cur[row]);
                for (int col = 0; col < 3; ++col) acc[row * 3 + col] = add(acc[row * 3 + col], mul(wc, rest[col]));
            }
        }
        const __m256i i9 = _mm256_mullo_epi32(ii, nine);
        __m256 inv[9];
        for (int k = 0; k < 9; ++k) inv[k] = gather(L.rinv + k, i9);
        __m256 f[9];
        for (int row = 0; row < 3; ++row)
            for (int col = 0; col < 3; ++col) {
                __m256 s = zero;
                for (int k = 0; k < 3; ++k) s = add(s, mul(acc[row * 3 + k], inv[k * 3 + col]));
                f[row * 3 + col] = s;
            }
        static constexpr int rows[6] = {0, 1, 2, 0, 0, 1};
        static constexpr int cols[6] = {0, 1, 2, 1, 2, 2};
        __m256 e[6];
        for (int q = 0; q < 6; ++q) {
            __m256 c = zero;
            for (int k = 0; k < 3; ++k) c = add(c, mul(f[k * 3 + rows[q]], f[k * 3 + cols[q]]));
            e[q] = mul(half, add(add(f[rows[q] * 3 + cols[q]], f[cols[q] * 3 + rows[q]]), c));
        }
        const __m256 un[3] = {gather(L.node_unmeasured, i3), gather(L.node_unmeasured + 1, i3),
                              gather(L.node_unmeasured + 2, i3)};
        const __m256 planar = _mm256_cmp_ps(dot3(un[0], un[1], un[2], un[0], un[1], un[2]), zero, _CMP_GT_OQ);
        if (_mm256_movemask_ps(planar) != 0) {
            const __m256 av[3] = {add(add(mul(e[0], un[0]), mul(e[3], un[1])), mul(e[4], un[2])),
                                  add(add(mul(e[3], un[0]), mul(e[1], un[1])), mul(e[5], un[2])),
                                  add(add(mul(e[4], un[0]), mul(e[5], un[1])), mul(e[2], un[2]))};
            const __m256 s = dot3(av[0], av[1], av[2], un[0], un[1], un[2]);
            for (int q = 0; q < 6; ++q) {
                const __m256 projected =
                    add(e[q], add(sub(mul(neg(un[rows[q]]), av[cols[q]]), mul(av[rows[q]], un[cols[q]])),
                                  mul(mul(s, un[rows[q]]), un[cols[q]])));
                e[q] = _mm256_blendv_ps(e[q], projected, planar);
            }
        }
        for (int q = 0; q < 6; ++q) _mm256_store_ps(out[q], e[q]);
        for (std::uint32_t k = 0; k < 8U; ++k) {
            if (!(any_valid & (1 << k))) continue;
            float *strain = L.strain + 6U * (i + k);
            for (int q = 0; q < 6; ++q) strain[q] = out[q][k];
        }
    }
    _mm256_zeroupper();
    for (; i < end; ++i) nodeStrainKept(L, i, false, 0.0f, 0.0f);
}

// nodeKickAndClassify for the nodes [begin, end), with no sphere in the scene
// so that no node is a candidate. Positions, velocities and their previous
// values are three floats a node, so eight nodes are 24 consecutive floats:
// the per-component updates run straight down them, with the gravity kick laid
// out x, y, z, x, ... to match.
BANJO_AVX2_TARGET void kickRange8(const LatticeArrays<float> &L, const StepSettings<float> &S,
                                  const SphereState<float> &sphere, std::uint32_t begin, std::uint32_t end) {
    using namespace v8;
    const std::uint32_t N = L.node_count;
    // S.dt * S.gravity, which the scalar code forms for every node.
    const float gx = S.gravity.x * S.dt, gy = S.gravity.y * S.dt, gz = S.gravity.z * S.dt;
    const __m256 kick[3] = {_mm256_setr_ps(gx, gy, gz, gx, gy, gz, gx, gy),
                            _mm256_setr_ps(gz, gx, gy, gz, gx, gy, gz, gx),
                            _mm256_setr_ps(gy, gz, gx, gy, gz, gx, gy, gz)};
    const __m256 dt = _mm256_set1_ps(S.dt);
    const __m256i three = _mm256_set1_epi32(3), lanes = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
    std::uint32_t i = begin;
    for (; i + 8U <= end; i += 8U) {
        float *v = L.v + 3U * i, *u = L.u + 3U * i, *u_prev = L.u_prev + 3U * i;
        for (int q = 0; q < 3; ++q) {
            // vel = v + dt * gravity; u_prev = u; u = u + dt * vel
            const __m256 vel = add(_mm256_loadu_ps(v + 8 * q), kick[q]);
            _mm256_storeu_ps(v + 8 * q, vel);
            const __m256 position = _mm256_loadu_ps(u + 8 * q);
            _mm256_storeu_ps(u_prev + 8 * q, position);
            _mm256_storeu_ps(u + 8 * q, add(position, mul(vel, dt)));
        }
        for (unsigned p = 0; p < kMaxSupportPlanes; ++p) std::memset(L.engaged + p * N + i, 0, 8);
        std::memset(L.candidate + i, 0, 8);
        // nodeRecordApproach
        const __m256i i3 = _mm256_mullo_epi32(_mm256_add_epi32(_mm256_set1_epi32(static_cast<int>(i)), lanes), three);
        const __m256 vx = gather(L.v, i3), vy = gather(L.v + 1, i3), vz = gather(L.v + 2, i3);
        for (std::uint32_t p = 0; p < S.support.plane_count; ++p) {
            const V3<float> &n = S.support.planes[p].normal;
            _mm256_storeu_ps(L.approach + p * N + i,
                             dot3(vx, vy, vz, _mm256_set1_ps(n.x), _mm256_set1_ps(n.y), _mm256_set1_ps(n.z)));
        }
    }
    _mm256_zeroupper();
    for (; i < end; ++i) (void)nodeKickAndClassify(L, S, sphere, i);
}

// nodeSupportProject then nodeVelocityUpdate, node by node, for the nodes
// [begin, end): the last constraint iteration's projection and the velocity
// update, with no sphere in the scene. A node a plane engaged then takes its
// support velocity response from the scalar code, as nodeVelocityUpdate does.
BANJO_AVX2_TARGET void projectAndVelocityRange8(const LatticeArrays<float> &L, const StepSettings<float> &S,
                                                std::uint32_t begin, std::uint32_t end) {
    using namespace v8;
    const std::uint32_t N = L.node_count;
    const __m256 zero = _mm256_setzero_ps(), dt = _mm256_set1_ps(S.dt);
    const __m256 eight = _mm256_set1_ps(8.0f), floor_reach = _mm256_set1_ps(1.0e-5f);
    const __m256 touching = _mm256_set1_ps(1.0e-8f);
    const __m256 magnitude = _mm256_castsi256_ps(_mm256_set1_epi32(0x7fffffff));
    const __m256i three = _mm256_set1_epi32(3), lanes = _mm256_setr_epi32(0, 1, 2, 3, 4, 5, 6, 7);
    const bool support_velocity = S.damping_fraction <= 0.0f;
    alignas(32) float ox[8], oy[8], oz[8];
    std::uint32_t i = begin;
    for (; i + 8U <= end; i += 8U) {
        const __m256i i3 = _mm256_mullo_epi32(_mm256_add_epi32(_mm256_set1_epi32(static_cast<int>(i)), lanes), three);
        __m256 ux = gather(L.u, i3), uy = gather(L.u + 1, i3), uz = gather(L.u + 2, i3);
        const __m256 x0x = gather(L.x0, i3), x0y = gather(L.x0 + 1, i3), x0z = gather(L.x0 + 2, i3);
        int moved = 0;
        for (std::uint32_t p = 0; p < S.support.plane_count; ++p) {
            const SupportPlane<float> &plane = S.support.planes[p];
            // position(L, i) - plane.point
            const __m256 rx = sub(add(x0x, ux), _mm256_set1_ps(plane.point.x));
            const __m256 ry = sub(add(x0y, uy), _mm256_set1_ps(plane.point.y));
            const __m256 rz = sub(add(x0z, uz), _mm256_set1_ps(plane.point.z));
            // insideFootprints
            const __m256 t = dot3(rx, ry, rz, _mm256_set1_ps(plane.tangent.x), _mm256_set1_ps(plane.tangent.y),
                                  _mm256_set1_ps(plane.tangent.z));
            const __m256 b = dot3(rx, ry, rz, _mm256_set1_ps(plane.bitangent.x), _mm256_set1_ps(plane.bitangent.y),
                                  _mm256_set1_ps(plane.bitangent.z));
            __m256 inside = zero;
            for (std::uint32_t k = 0; k < plane.footprint_count; ++k) {
                const Footprint<float> &f = plane.footprints[k];
                const __m256 along_t = _mm256_cmp_ps(_mm256_and_ps(sub(t, _mm256_set1_ps(f.center_t)), magnitude),
                                                     _mm256_set1_ps(f.half_t), _CMP_LE_OQ);
                const __m256 along_b = _mm256_cmp_ps(_mm256_and_ps(sub(b, _mm256_set1_ps(f.center_b)), magnitude),
                                                     _mm256_set1_ps(f.half_b), _CMP_LE_OQ);
                inside = _mm256_or_ps(inside, _mm256_and_ps(along_t, along_b));
            }
            if (_mm256_movemask_ps(inside) == 0) continue;
            const __m256 distance =
                sub(dot3(rx, ry, rz, _mm256_set1_ps(plane.normal.x), _mm256_set1_ps(plane.normal.y),
                         _mm256_set1_ps(plane.normal.z)),
                    _mm256_set1_ps(plane.node_radius));
            // if (distance > 1e-8) return 0
            __m256 apply = _mm256_and_ps(inside, _mm256_cmp_ps(distance, touching, _CMP_NGT_UQ));
            if (plane.reach_capped) {
                // reach = 8 * max(0, -approach) * dt + 1e-5; if (-distance > reach) return 0
                const __m256 approach = _mm256_loadu_ps(L.approach + p * N + i);
                const __m256 reach = add(mul(mul(eight, maxR8(zero, neg(approach))), dt), floor_reach);
                apply = _mm256_and_ps(apply, _mm256_cmp_ps(neg(distance), reach, _CMP_NGT_UQ));
            }
            const int applied = _mm256_movemask_ps(apply);
            if (applied == 0) continue;
            moved |= applied;
            // u - distance * normal
            ux = _mm256_blendv_ps(ux, sub(ux, mul(_mm256_set1_ps(plane.normal.x), distance)), apply);
            uy = _mm256_blendv_ps(uy, sub(uy, mul(_mm256_set1_ps(plane.normal.y), distance)), apply);
            uz = _mm256_blendv_ps(uz, sub(uz, mul(_mm256_set1_ps(plane.normal.z), distance)), apply);
            const int engaged = _mm256_movemask_ps(_mm256_and_ps(apply, _mm256_cmp_ps(neg(distance), zero, _CMP_GT_OQ)));
            for (int k = 0; k < 8; ++k)
                if (engaged & (1 << k)) L.engaged[p * N + i + static_cast<std::uint32_t>(k)] = 1;
        }
        if (moved != 0) {
            _mm256_store_ps(ox, ux);
            _mm256_store_ps(oy, uy);
            _mm256_store_ps(oz, uz);
            for (int k = 0; k < 8; ++k) {
                if (!(moved & (1 << k))) continue;
                float *position = L.u + 3U * (i + static_cast<std::uint32_t>(k));
                position[0] = ox[k];
                position[1] = oy[k];
                position[2] = oz[k];
            }
        }
        // nodeVelocityUpdate: v = (u - u_prev) / dt
        float *v = L.v + 3U * i;
        const float *u = L.u + 3U * i, *u_prev = L.u_prev + 3U * i;
        for (int q = 0; q < 3; ++q)
            _mm256_storeu_ps(v + 8 * q, div(sub(_mm256_loadu_ps(u + 8 * q), _mm256_loadu_ps(u_prev + 8 * q)), dt));
        // nodeSupportVelocity does nothing for a node no plane engaged, in
        // this iteration or an earlier one, so only those are sent to it.
        if (support_velocity) {
            for (std::uint32_t k = 0; k < 8U; ++k) {
                bool engaged = false;
                for (std::uint32_t p = 0; p < S.support.plane_count; ++p) engaged = engaged || L.engaged[p * N + i + k] != 0;
                if (engaged) nodeSupportVelocity(L, S, i + k);
            }
        }
    }
    _mm256_zeroupper();
    for (; i < end; ++i) {
        nodeSupportProject(L, S, i);
        nodeVelocityUpdate(L, S, i);
    }
}
#endif

// How many elements one claim covers, by phase. A claim is one atomic
// increment on a shared line, a few tens of nanoseconds, so a chunk should be
// worth a microsecond or so; below two chunks a phase runs on the caller.
constexpr std::uint32_t kNodeGrain = 128;     // the cheap per-node phases
constexpr std::uint32_t kStrainGrain = 16;    // nodeStrain, ~0.1-1 us a node
constexpr std::uint32_t kBondGrain = 64;      // the per-bond samples
constexpr std::uint32_t kSolveGrain = 48;     // one colour stage of the sweep
// The same for the eight-wide kernels, which do several times the work per
// element in the same time.
// Every dispatch is also a chance to wait on a worker the operating system has
// just taken off its core (see WorkPool), so with the kernels only the two
// heavy phases are spread; a colour stage of a few hundred bonds and the cheap
// per-node phases are done where they are, until a lattice is large enough
// for spreading them to pay.
constexpr std::uint32_t kStrainGrain8 = 64;
constexpr std::uint32_t kBondGrain8 = 512;
constexpr std::uint32_t kSolveGrain8 = 1024;
constexpr std::uint32_t kNodeGrain8 = 1024;

template <typename Real>
class ParallelCpuLatticeBackend final : public LatticeBackend {
public:
    ParallelCpuLatticeBackend(LatticeSchedule schedule, unsigned threads, unsigned spins)
        : schedule_(std::move(schedule)), threads_(std::max(1U, threads)), spins_(spins) {}

    [[nodiscard]] std::string name() const override {
        return std::string("cpu-parallel-") + (sizeof(Real) == 4 ? "float" : "double") + "-x" +
               std::to_string(threads_);
    }

    void upload(const LatticeState &state, const StepSettings<double> &settings,
                const SphereState<double> &sphere) override {
        if (settings.bond_integrator!=kBondXpbd)
            throw std::invalid_argument("parallel CPU has no qualified alternative bond integrator");
        working_ = WorkingLattice<Real>::fromState(state, schedule_);
        L_ = working_.arrays();
        S_ = convertSettings<Real>(settings);
        sphere_ = convertSphere<Real>(sphere);
        status_ = {};
        external_.reset(state.origin);
        dirty_start_ = true;
        contact_rebuild_ = true;
        status_.energy_audited = S_.audit_energy != 0;
        frames_.clear();
        // Per-participant scratch. Each participant gets its own view of the
        // arrays so that the rank-deficiency counter, the only element
        // function that writes a shared scalar, is its own; the counts are
        // summed afterwards, which an integer sum makes order-independent.
        scratch_ = std::vector<Scratch>(threads_);
        views_.assign(threads_, L_);
        for (unsigned t = 0; t < threads_; ++t) views_[t].rank_deficient_nodes = &scratch_[t].degenerate;
        buildCache();
        bond_mark_.assign(L_.bond_count, 0U);
        dirty_nodes_.clear();
        touched_bonds_.clear();
    }

    void setExternalForces(const std::vector<Vec3> &forces, std::uint64_t substeps) override {
        external_.set(forces,substeps,L_);
    }
    void setExternalWrenches(const std::vector<ExternalWrench> &wrenches, std::uint64_t substeps) override {
        external_.setWrenches(wrenches,substeps,L_);
    }

    RunStatus run(const RunControl &control) override {
        energy_flat_fraction_ = control.energy_flat_fraction;
        const auto start = std::chrono::steady_clock::now();
        PoolRegistry::Lease lease;
        if (threads_ > 1U) lease = PoolRegistry::instance().acquire(threads_, spins_);
        pool_ = lease.pool;
        status_.exit_reason = 0;
        std::uint64_t done = 0;
        while (done < control.max_steps) {
            if (control.abandon != nullptr && control.abandon->load(std::memory_order_relaxed)) {
                status_.exit_reason = 7;
                break;
            }
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
            const double available = control.removable_energy_j + status_.external_load.work_j;
            status_.exit_reason = control.removable_energy_j > 0 && available <= 0 ? 6 :
                latticeExitReason(status_.total_steps, status_.broken_bonds,
                status_.last_failure_step, control.quiet_steps, control.min_steps,
                control.no_failure_steps, control.energy_flat_steps,
                status_.last_energy_gain_step, control.calm_steps,
                status_.last_damage_gain_step, status_.max_damage,
                control.calm_damage_margin, status_.removed_energy_j,
                control.removable_energy_j > 0 ? available : 0.0);
            if (status_.exit_reason != 0) break;
        }
        pool_ = nullptr;
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
    // One cache line per participant: the per-bond phase updates the strain
    // peaks once per bond, and packed back to back every participant's writes
    // would land on one shared line.
    struct alignas(64) Scratch {
        float tensile{}, compressive{}, shear{}, plastic{}, damage{};
        std::uint32_t degenerate{};
        // Pairs the broad phase could not store, summed as integers, which is
        // order independent.
        std::uint32_t pair_overflow{};
        std::vector<Breakage> breakages;
        std::vector<Breakage> flows;
    };

    void buildCache() {
        const std::uint32_t B = L_.bond_count;
        direction_.assign(3U * static_cast<std::size_t>(B), Real(0));
        has_direction_.assign(B, 0U);
        alpha_.assign(B, Real(0));
        denominator_.assign(B, Real(0));
        finite_.assign(B, 0U);
        C_.direction = direction_.data();
        C_.has_direction = has_direction_.data();
        C_.alpha = alpha_.data();
        C_.denominator = denominator_.data();
        C_.finite = finite_.data();
        // bondStrainSample's direction and bondSolve's alpha and denominator,
        // with the expressions those functions evaluate.
        const Real dt = S_.dt;
        for (std::uint32_t j = 0; j < B; ++j) {
            const V3<Real> rest_edge = load3(L_.rest_edge, j);
            const Real rest_len = length(rest_edge);
            if (rest_len > Real(1.0e-9)) {
                store3(direction_.data(), j, rest_edge * (Real(1) / rest_len));
                has_direction_[j] = 1U;
            }
            const Real alpha = L_.compliance[j] / (dt * dt);
            alpha_[j] = alpha;
            const Real wa = L_.inv_mass[L_.bond_a[j]], wb = L_.inv_mass[L_.bond_b[j]];
            denominator_[j] = wa + wb + alpha;
            std::uint8_t finite = 0;
            for (unsigned k = 0; k < 6U; ++k)
                if (finiteR(L_.threshold[6U * j + k])) finite = static_cast<std::uint8_t>(finite | (1U << k));
            finite_[j] = finite;
        }
        if (!vector_) return;
        const std::size_t slots = static_cast<std::size_t>(L_.max_degree) * L_.node_count;
        columns_.assign(14U * static_cast<std::size_t>(B) + 3U * slots, Real(0));
        Real *column = columns_.data();
        const auto take = [&](std::size_t count) {
            Real *out = column;
            column += count;
            return out;
        };
        Real *rest[3] = {take(B), take(B), take(B)};
        Real *direction[3] = {take(B), take(B), take(B)};
        Real *inv_a = take(B), *inv_b = take(B);
        Real *threshold[6] = {take(B), take(B), take(B), take(B), take(B), take(B)};
        Real *nbr_rest[3] = {take(slots), take(slots), take(slots)};
        for (std::uint32_t j = 0; j < B; ++j) {
            for (unsigned c = 0; c < 3U; ++c) {
                rest[c][j] = L_.rest_edge[3U * j + c];
                direction[c][j] = direction_[3U * j + c];
            }
            inv_a[j] = L_.inv_mass[L_.bond_a[j]];
            inv_b[j] = L_.inv_mass[L_.bond_b[j]];
            for (unsigned k = 0; k < 6U; ++k) threshold[k][j] = L_.threshold[6U * j + k];
        }
        for (std::size_t slot = 0; slot < slots; ++slot)
            for (unsigned c = 0; c < 3U; ++c) nbr_rest[c][slot] = L_.nbr_rest[3U * slot + c];
        for (unsigned c = 0; c < 3U; ++c) {
            C_.rest_edge[c] = rest[c];
            C_.direction_of[c] = direction[c];
            C_.nbr_rest_of[c] = nbr_rest[c];
        }
        C_.inv_mass_a = inv_a;
        C_.inv_mass_b = inv_b;
        for (unsigned k = 0; k < 6U; ++k) C_.threshold_of[k] = threshold[k];
    }

    // Run body(i, participant) over [begin, end) in chunks of `grain`.
    template <typename Body>
    void forEachRange(std::uint32_t begin, std::uint32_t end, std::uint32_t grain, Body &&body) {
        const std::uint32_t count = end > begin ? end - begin : 0U;
        if (pool_ == nullptr || count < 2U * grain) {
            for (std::uint32_t i = begin; i < end; ++i) body(i, 0U);
            return;
        }
        const std::uint32_t chunks = (count + grain - 1U) / grain;
        auto chunk_body = [&](std::uint32_t chunk, unsigned participant) {
            const std::uint32_t first = begin + chunk * grain;
            const std::uint32_t last = std::min(end, first + grain);
            for (std::uint32_t i = first; i < last; ++i) body(i, participant);
        };
        pool_->run(chunks, chunk_body);
    }

    // Run body(first, last, participant) over [begin, end) in chunks of
    // `grain`: for the kernels that take a range.
    template <typename Body>
    void forEachChunk(std::uint32_t begin, std::uint32_t end, std::uint32_t grain, Body &&body) {
        const std::uint32_t count = end > begin ? end - begin : 0U;
        if (pool_ == nullptr || count < 2U * grain) {
            if (count != 0U) body(begin, end, 0U);
            return;
        }
        const std::uint32_t chunks = (count + grain - 1U) / grain;
        auto chunk_body = [&](std::uint32_t chunk, unsigned participant) {
            const std::uint32_t first = begin + chunk * grain;
            body(first, std::min(end, first + grain), participant);
        };
        pool_->run(chunks, chunk_body);
    }

    template <typename Body>
    void forEach(std::uint32_t count, std::uint32_t grain, Body &&body) {
        forEachRange(0U, count, grain, std::forward<Body>(body));
    }

    // One colour stage at a time. The bonds of a colour share no node, so the
    // stage may be split without changing any value: each bond reads and writes
    // only its own two nodes. The stages stay in order, which is what makes
    // this the same Gauss-Seidel sweep.
    template <typename Body>
    void sweep(std::uint32_t block, std::uint32_t boundary, Body &&body) {
        for (std::uint32_t c = 0; c < L_.color_count; ++c) {
            const std::size_t key = (static_cast<std::size_t>(block) * 2U + boundary) * L_.color_count + c;
            const std::uint32_t begin = L_.range_begin[key], end = L_.range_end[key];
            forEachRange(begin, end, kSolveGrain, [&](std::uint32_t j, unsigned) { body(j); });
        }
    }

    // The constraint sweep's colour stages, eight bonds at a time where the
    // kernel applies.
    void solveSweep(std::uint32_t block, std::uint32_t boundary, bool direct, bool first) {
#if BANJO_LATTICE_AVX2
        if constexpr (std::is_same_v<Real, float>) {
            if (vector_ && !direct) {
                for (std::uint32_t c = 0; c < L_.color_count; ++c) {
                    const std::size_t key = (static_cast<std::size_t>(block) * 2U + boundary) * L_.color_count + c;
                    forEachChunk(L_.range_begin[key], L_.range_end[key], kSolveGrain8,
                                 [&](std::uint32_t first_bond, std::uint32_t last_bond, unsigned) {
                                     bondSolveRange8(L_, C_, first_bond, last_bond, first);
                                 });
                }
                return;
            }
        }
#endif
        sweep(block, boundary, [&](std::uint32_t j) { bondSolveKept(L_, C_, j, direct, first); });
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

    // Every node's gravity kick and classification.
    void kickAll(const SphereState<Real> &kicked) {
        const std::uint32_t N = L_.node_count;
#if BANJO_LATTICE_AVX2
        if constexpr (std::is_same_v<Real, float>) {
            if (vector_ && !S_.sphere_enabled) {
                forEachChunk(0U, N, node_grain_, [&](std::uint32_t first, std::uint32_t last, unsigned) {
                    kickRange8(L_, S_, kicked, first, last);
                });
                return;
            }
        }
#endif
        forEach(N, node_grain_, [&](std::uint32_t i, unsigned thread) {
            (void)nodeKickAndClassify(views_[thread], S_, kicked, i);
        });
    }

    // The last constraint iteration's support projection, then the velocity
    // update, node by node.
    void projectAndVelocityAll() {
        const std::uint32_t N = L_.node_count;
#if BANJO_LATTICE_AVX2
        if constexpr (std::is_same_v<Real, float>) {
            if (vector_ && !S_.sphere_enabled) {
                forEachChunk(0U, N, node_grain_, [&](std::uint32_t first, std::uint32_t last, unsigned) {
                    projectAndVelocityRange8(L_, S_, first, last);
                });
                return;
            }
        }
#endif
        forEach(N, node_grain_, [&](std::uint32_t i, unsigned) {
            nodeSupportProject(L_, S_, i);
            nodeVelocityUpdate(L_, S_, i);
        });
    }

    // Every node's strain at the end of the substep.
    void endStrain(bool direct) {
        const std::uint32_t N = L_.node_count;
#if BANJO_LATTICE_AVX2
        if constexpr (std::is_same_v<Real, float>) {
            if (vector_ && !direct && !(S_.plate_half_thickness > Real(0))) {
                forEachChunk(0U, N, kStrainGrain8, [&](std::uint32_t first, std::uint32_t last, unsigned thread) {
                    nodeStrainRange8(views_[thread], C_, first, last);
                });
                return;
            }
        }
#endif
        forEach(N, kStrainGrain, [&](std::uint32_t i, unsigned thread) {
            nodeStrainKept(views_[thread], i, direct, S_.plate_half_thickness, S_.plastic_yield_stretch);
        });
    }

    // The end-of-substep sample and failure test of every live bond, eight at
    // a time; false when the kernel does not apply and the caller must do it.
    bool endSample8(bool direct) {
#if BANJO_LATTICE_AVX2
        if constexpr (std::is_same_v<Real, float>) {
            if (vector_ && !direct) {
                forEachChunk(0U, L_.bond_count, kBondGrain8, [&](std::uint32_t first, std::uint32_t last, unsigned thread) {
                    Scratch &scratch = scratch_[thread];
                    BondEndTally tally{scratch.tensile, scratch.compressive, scratch.shear, scratch.damage,
                                       scratch.plastic};
                    bondEndRange8(L_, C_, S_, first, last, tally, scratch.breakages, scratch.flows);
                    scratch.tensile = tally.tensile;
                    scratch.compressive = tally.compressive;
                    scratch.shear = tally.shear;
                    scratch.damage = tally.damage;
                    scratch.plastic = tally.plastic;
                });
                return true;
            }
        }
#endif
        (void)direct;
        return false;
    }

    // The start-of-substep sample after a failure. The serial backend redoes
    // the strain of every node and the start sample of every live bond; only
    // the nodes that lost a bond (node_dirty) can come out different, because
    // every other node's strain reads the same positions and the same live set
    // it was read from at the end of the last substep, and a bond's start
    // sample is the same function its end sample was, of the strain at its two
    // ends. So those nodes, and the live bonds that touch them, are redone and
    // the rest are already what a full pass would write.
    void startSample(bool direct) {
        const std::uint32_t N = L_.node_count;
        dirty_nodes_.clear();
        for (std::uint32_t i = 0; i < N; ++i)
            if (L_.node_dirty[i]) dirty_nodes_.push_back(i);
        forEach(static_cast<std::uint32_t>(dirty_nodes_.size()), kStrainGrain,
                [&](std::uint32_t k, unsigned thread) {
                    nodeStrainKept(views_[thread], dirty_nodes_[k], direct, S_.plate_half_thickness,
                                   S_.plastic_yield_stretch);
                });
        mark(1);
        ++bond_stamp_;
        if (bond_stamp_ == 0U) {
            std::fill(bond_mark_.begin(), bond_mark_.end(), 0U);
            bond_stamp_ = 1U;
        }
        touched_bonds_.clear();
        const std::uint32_t D = L_.max_degree;
        for (const std::uint32_t i : dirty_nodes_)
            for (std::uint32_t k = 0; k < D; ++k) {
                const std::uint32_t j = L_.nbr_bond[k * N + i];
                if (j == kNoBond) break;
                if (!L_.alive[j] || bond_mark_[j] == bond_stamp_) continue;
                bond_mark_[j] = bond_stamp_;
                touched_bonds_.push_back(j);
            }
        forEach(static_cast<std::uint32_t>(touched_bonds_.size()), kBondGrain,
                [&](std::uint32_t k, unsigned) { bondStartSampleKept(L_, C_, touched_bonds_[k], direct); });
        mark(2);
    }

    // One substep; returns whether any bond failed. The phase order, the phase
    // numbering and every element call are CpuLatticeBackend's.
    bool advance() {
        const bool direct = S_.direct_arithmetic != 0;
        const std::uint32_t N = L_.node_count, B = L_.bond_count;
        phase_clock_ = std::chrono::steady_clock::now();
        if (dirty_start_) {
            startSample(direct);
            dirty_start_ = false;
        }
        // Kick and classify in parallel; the ordered candidate lists are built
        // by a serial scan of the flags, which is the order the serial backend
        // pushes them in.
        external_.kick(L_,S_.dt,status_.external_load,&status_.external_sources);
        SphereState<Real> kicked = sphere_;
        kicked.velocity = kicked.velocity + S_.dt * S_.gravity;
        kickAll(kicked);
        if (S_.sphere_enabled) {
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
        } else {
            // No sphere, so no node is a candidate: the scan would find none.
            for (std::uint32_t block = 0; block < L_.block_count; ++block) L_.candidate_count[block] = 0U;
        }
        sphere_ = kicked;
        mark(3);
        if (S_.sphere_enabled) {
            const double before = S_.audit_energy ? latticeKineticEnergy(L_) : 0.0;
            sphereContactPass(L_, S_, sphere_, 1, status_.contact);
            if (S_.audit_energy) status_.striker_dissipated_j += before - latticeKineticEnergy(L_);
        }
        mark(4);
        for (std::uint32_t iteration = 0; iteration < S_.constraint_iterations; ++iteration) {
            const bool first = iteration == 0;
            for (std::uint32_t block = 0; block < L_.block_count; ++block) solveSweep(block, 0U, direct, first);
            mark(5);
            for (std::uint32_t block = 0; block < L_.block_count; block += 2U) solveSweep(block, 1U, direct, first);
            for (std::uint32_t block = 1; block < L_.block_count; block += 2U) solveSweep(block, 1U, direct, first);
            mark(6);
            if (iteration + 1U < S_.constraint_iterations) {
                forEach(N, node_grain_, [&](std::uint32_t i, unsigned) { nodeSupportProject(L_, S_, i); });
            } else {
                // The last projection and the velocity update read and write
                // only node i, so one pass does both, node by node.
                projectAndVelocityAll();
            }
            mark(7);
        }
        if (S_.constraint_iterations == 0U)
            forEach(N, node_grain_, [&](std::uint32_t i, unsigned) { nodeVelocityUpdate(L_, S_, i); });
        mark(8);
        if (S_.damping_fraction > Real(0)) {
            const double before = S_.audit_energy ? latticeKineticEnergy(L_) : 0.0;
            sweepAll([&](std::uint32_t j) { bondDamp(L_, j, S_.damping_fraction, direct); });
            if (S_.audit_energy) status_.damping_dissipated_j += before - latticeKineticEnergy(L_);
            forEach(N, node_grain_, [&](std::uint32_t i, unsigned) {
                if (!L_.candidate[i]) nodeSupportVelocity(L_, S_, i);
            });
            mark(9);
        }
        if (S_.sphere_enabled) {
            const double before = S_.audit_energy ? latticeKineticEnergy(L_) : 0.0;
            sphereContactPass(L_, S_, sphere_, 2, status_.contact);
            if (S_.audit_energy) status_.striker_dissipated_j += before - latticeKineticEnergy(L_);
        }
        mark(10);
        // Node-node contact. Steps 1 and 3 of the broad phase are per node and
        // write only that node's own slots, so spreading them changes nothing;
        // the hash build, the active list, the staleness scan and the whole
        // narrow phase are the serial backend's code, called here unchanged.
        if (S_.node_contact.mode != kNodeContactOff) {
            if (contact_rebuild_ || nodeContactStale(L_, S_)) {
                forEach(N, node_grain_, [&](std::uint32_t i, unsigned) { nodeContactStoreCell(L_, S_, i); });
                nodeContactHashBuild(L_, S_);
                for (Scratch &scratch : scratch_) scratch.pair_overflow = 0U;
                forEach(N, kStrainGrain, [&](std::uint32_t i, unsigned thread) {
                    scratch_[thread].pair_overflow += nodeContactGather(L_, S_, i);
                });
                for (const Scratch &scratch : scratch_)
                    status_.node_contact.pair_overflow += scratch.pair_overflow;
                status_.node_contact.pairs_listed += nodeContactActiveList(L_);
                ++status_.node_contact.rebuilds;
                contact_rebuild_ = false;
            }
            mark(14);
            nodeContactPass(L_, S_, status_.node_contact);
            mark(15);
        }
        endStrain(direct);
        mark(11);
        const bool plastic = S_.plastic_yield_stretch > Real(0);
        for (Scratch &scratch : scratch_) {
            scratch.tensile = scratch.compressive = scratch.shear = scratch.plastic = 0.0F;
            scratch.damage = 0.0F;
            scratch.breakages.clear();
            scratch.flows.clear();
        }
        if (!endSample8(direct))
            forEach(B, kBondGrain, [&](std::uint32_t j, unsigned thread) {
                if (!L_.alive[j]) return;
                const FailureOutcome out = bondEndSampleAndFailureKept(views_[thread], C_, S_, j, direct);
                Scratch &scratch = scratch_[thread];
                scratch.tensile = std::max(scratch.tensile, out.peak_tensile);
                scratch.compressive = std::max(scratch.compressive, out.peak_compressive);
                scratch.shear = std::max(scratch.shear, out.peak_shear);
                scratch.plastic = std::max(scratch.plastic, out.plastic_stretch);
                scratch.damage = std::max(scratch.damage, out.damage);
                if (plastic && out.plastic_increment_j != 0.0) scratch.flows.push_back({j, out.plastic_increment_j});
                if (out.broke) scratch.breakages.push_back({j, out.removed_energy_j});
            });
        // The peaks combine by max, which is the same whoever took which bond.
        float worst_damage = 0.0F;
        for (const Scratch &scratch : scratch_) {
            worst_damage = std::max(worst_damage, scratch.damage);
            status_.max_tensile_stretch = std::max(status_.max_tensile_stretch, scratch.tensile);
            status_.max_compressive_strain = std::max(status_.max_compressive_strain, scratch.compressive);
            status_.max_shear_strain = std::max(status_.max_shear_strain, scratch.shear);
            status_.max_plastic_stretch = std::max(status_.max_plastic_stretch, scratch.plastic);
        }
        if (worst_damage > status_.max_damage + calm_damage_epsilon_) {
            status_.max_damage = worst_damage;
            status_.last_damage_gain_step = status_.total_steps;
        }
        // Sums replayed in bond index order, the order the serial backend adds
        // in. Only bonds that flowed or broke are listed, and the serial
        // backend's other addends are exact zeros.
        if (plastic) {
            gathered_.clear();
            for (const Scratch &scratch : scratch_) gathered_.insert(gathered_.end(), scratch.flows.begin(), scratch.flows.end());
            std::sort(gathered_.begin(), gathered_.end(),
                      [](const Breakage &x, const Breakage &y) { return x.bond < y.bond; });
            for (const Breakage &flow : gathered_) status_.plastic_work_j += flow.energy_j;
        }
        gathered_.clear();
        for (const Scratch &scratch : scratch_)
            gathered_.insert(gathered_.end(), scratch.breakages.begin(), scratch.breakages.end());
        std::sort(gathered_.begin(), gathered_.end(),
                  [](const Breakage &x, const Breakage &y) { return x.bond < y.bond; });
        const bool any_failed = !gathered_.empty();
        const double energy_before_round = status_.removed_energy_j;
        for (const Breakage &broken : gathered_) {
            status_.removed_energy_j += broken.energy_j;
            ++status_.broken_bonds;
            L_.node_dirty[L_.bond_a[broken.bond]] = 1;
            L_.node_dirty[L_.bond_b[broken.bond]] = 1;
        }
        // The substep at which the removed energy last grew by more than a
        // stated fraction of its running total. A cascade that is still
        // producing pieces but no longer removing energy is past the point
        // where anything measurable is still being decided.
        if (status_.removed_energy_j - energy_before_round >
            energy_flat_fraction_ * std::max(status_.removed_energy_j, 1.0e-12))
            status_.last_energy_gain_step = status_.total_steps;
        mark(12);
        std::uint32_t disagreements = 0;
        for (const Scratch &scratch : scratch_) disagreements += scratch.degenerate;
        status_.rank_deficient_nodes = disagreements;
        sphere_.center = sphere_.center + S_.dt * sphere_.velocity;
        sphereSupportContact(S_, sphere_, status_.contact);
        // A failure changes which pairs no live bond holds.
        if (any_failed) dirty_start_ = contact_rebuild_ = true;
        mark(13);
        return any_failed;
    }

    std::chrono::steady_clock::time_point phase_clock_{};

    LatticeSchedule schedule_;
    unsigned threads_;
    unsigned spins_;
    WorkPool *pool_{nullptr};
    // Whether the eight-wide kernels may run on this machine.
#if BANJO_LATTICE_AVX2
    bool vector_{std::is_same_v<Real, float> && avx2Available()};
#else
    bool vector_{false};
#endif
    std::uint32_t node_grain_{vector_ ? kNodeGrain8 : kNodeGrain};
    WorkingLattice<Real> working_;
    LatticeArrays<Real> L_{};
    std::vector<LatticeArrays<Real>> views_;
    std::vector<Scratch> scratch_;
    std::vector<Breakage> gathered_;
    StepSettings<Real> S_{};
    SphereState<Real> sphere_{};
    RunStatus status_{};
    CpuExternalLoads<Real> external_;
    // The kept element results (ElementCache) and the arrays behind them.
    ElementCache<Real> C_{};
    std::vector<Real> direction_, alpha_, denominator_, columns_;
    std::vector<std::uint8_t> has_direction_, finite_;
    // Start-sample bookkeeping: the dirty nodes, and the bonds touching them,
    // each listed once (bond_mark_ holds the pass it was last listed in).
    std::vector<std::uint32_t> dirty_nodes_, touched_bonds_, bond_mark_;
    std::uint32_t bond_stamp_{0};
    // RunControl::energy_flat_fraction, held here because the substep that
    // accumulates removed energy does not see the control.
    double energy_flat_fraction_{1.0e-3};
    // What counts as a rise in the worst bond's damage. Float noise on a
    // quantity that is stored as a float and only ever compared against a
    // margin; without it a lattice at rest never looks flat.
    static constexpr double calm_damage_epsilon_ = 1.0e-6;
    bool dirty_start_{true};
    bool contact_rebuild_{true};
    std::vector<FrameCapture> frames_;
};

} // namespace

unsigned defaultLatticeThreadCount() {
    // One core is left to the rest of the program -- the world goes on
    // stepping on its own thread while a break is worked out on another -- and
    // eight is a cap, not a requirement: with chunks claimed from one counter
    // a slow or busy core costs only the chunk it holds. Two cores or fewer is
    // one thread, the caller's, and no pool at all.
    static const unsigned count = std::clamp(usableCores(), 2U, 9U) - 1U;
    return count;
}

double measureParallelDispatchCost(unsigned threads, unsigned spins, unsigned dispatches) {
    PoolRegistry::Lease lease = PoolRegistry::instance().acquire(std::max(1U, threads), spins == 0 ? 100U : spins);
    const unsigned participants = std::max(1U, threads);
    auto empty = [](std::uint32_t, unsigned) {};
    const auto run = [&] { lease.pool->run(participants, empty); };
    for (unsigned d = 0; d < std::max(64U, dispatches / 4U); ++d) run();
    const auto begin = std::chrono::steady_clock::now();
    for (unsigned d = 0; d < dispatches; ++d) run();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
}

unsigned calibratedLatticeThreadCount(unsigned spins) {
    // Kept for the tools that report it. The backend no longer needs it: a
    // dispatch never waits for a worker that is not running, so a loaded
    // machine slows a run down instead of stalling it, and probing the pool
    // before every run cost more than most runs (measured: 34 to 690 ms per
    // fracture on a busy machine, against 1 ms to build the island).
    constexpr double kAcceptableDispatchMicroseconds = 6.0;
    constexpr unsigned kProbeDispatches = 300;
    for (unsigned threads = defaultLatticeThreadCount(); threads >= 2U; threads /= 2U) {
        const double seconds = measureParallelDispatchCost(threads, spins, kProbeDispatches);
        if (seconds * 1.0e6 / kProbeDispatches <= kAcceptableDispatchMicroseconds) return threads;
    }
    return 1U;
}

std::unique_ptr<LatticeBackend> makeParallelCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision, unsigned threads, unsigned spins) {
    if (spins == 0) spins = 100;
    if (threads == 0) threads = defaultLatticeThreadCount();
    if (precision == Precision::Float)
        return std::make_unique<ParallelCpuLatticeBackend<float>>(schedule, threads, spins);
    return std::make_unique<ParallelCpuLatticeBackend<double>>(schedule, threads, spins);
}

} // namespace banjo::fastlattice
