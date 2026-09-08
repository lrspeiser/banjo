// CUDA backend of the fast explicit lattice lane.
//
// One persistent cooperative kernel advances many substeps per launch; the
// host is consulted only between launches. Within a substep the phases are
// separated by __syncthreads() when the grid is one block and by
// cooperative-groups grid.sync() otherwise. The constraint sweep runs the
// schedule's colours as stages: node-disjoint bonds of one colour in parallel,
// a block barrier between colours, interior bonds of every slab first, then
// the boundary bonds of even and of odd slabs (LatticeSchedule.hpp). Sphere
// contact, which the CPU lane resolves sequentially in node order because each
// impulse changes the sphere the next node sees, is run by one thread over
// per-block candidate lists that the parallel prefilter compacted in node
// order. The element functions are those of LatticePhysics.hpp.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"

#include <cooperative_groups.h>
#include <cuda_runtime.h>

#include <chrono>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace banjo::fastlattice {
namespace {

namespace cg = cooperative_groups;

void check(cudaError_t error, const char *what) {
    if (error != cudaSuccess)
        throw std::runtime_error(std::string("CUDA ") + what + ": " + cudaGetErrorString(error));
}

template <typename T>
class DeviceVector {
public:
    DeviceVector() = default;
    ~DeviceVector() { release(); }
    DeviceVector(const DeviceVector &) = delete;
    DeviceVector &operator=(const DeviceVector &) = delete;

    void upload(const std::vector<T> &host) {
        allocate(host.size());
        if (!host.empty())
            check(cudaMemcpy(ptr_, host.data(), host.size() * sizeof(T), cudaMemcpyHostToDevice), "memcpy to device");
    }
    void allocate(std::size_t count) {
        if (count != count_) {
            release();
            if (count > 0) check(cudaMalloc(&ptr_, count * sizeof(T)), "malloc");
            count_ = count;
        }
    }
    void zero() {
        if (count_ > 0) check(cudaMemset(ptr_, 0, count_ * sizeof(T)), "memset");
    }
    void download(std::vector<T> &host, std::size_t count) const {
        host.resize(count);
        if (count > 0)
            check(cudaMemcpy(host.data(), ptr_, count * sizeof(T), cudaMemcpyDeviceToHost), "memcpy to host");
    }
    void download(std::vector<T> &host) const { download(host, count_); }
    [[nodiscard]] T *data() { return ptr_; }
    [[nodiscard]] const T *data() const { return ptr_; }
    [[nodiscard]] std::size_t size() const { return count_; }

private:
    void release() {
        if (ptr_) cudaFree(ptr_);
        ptr_ = nullptr;
        count_ = 0;
    }
    T *ptr_{};
    std::size_t count_{};
};

// What a single-block run keeps in dynamic shared memory, as byte offsets.
// Real arrays first (8-byte aligned for double), then 32-bit, then bytes.
struct SharedLayout {
    unsigned total_bytes;
    unsigned has_positions, has_strain, has_bonds;
    unsigned u, strain, rest_edge, rest_length, rest_length_sq_minus, compliance, inv_mass;
    unsigned bond_a, bond_b;
    unsigned node_valid;
};

struct DeviceControl {
    unsigned long long step_begin, step_end;
    unsigned long long quiet_steps, min_steps, no_failure_steps;
    unsigned long long capture_stride;
    unsigned capture_max;
    SharedLayout layout;
};

template <typename Real>
SharedLayout planSharedLayout(unsigned node_count, unsigned bond_count, std::size_t limit) {
    SharedLayout l{};
    unsigned cursor = 0;
    const auto take = [&](std::size_t bytes) {
        const unsigned offset = cursor;
        cursor += static_cast<unsigned>((bytes + 15U) & ~std::size_t(15));
        return offset;
    };
    // Positions are the most valuable (every colour stage), then the strain
    // and validity the resolve phase gathers, then the bond constants.
    const std::size_t position_bytes = std::size_t(3) * node_count * sizeof(Real);
    if (position_bytes + 16U > limit) return l;
    l.u = take(position_bytes);
    l.has_positions = 1;
    const std::size_t strain_bytes = std::size_t(6) * node_count * sizeof(Real) + node_count + 32U;
    if (cursor + strain_bytes <= limit) {
        l.strain = take(std::size_t(6) * node_count * sizeof(Real));
        l.has_strain = 1;
    }
    const std::size_t bond_bytes = std::size_t(bond_count) * (3 + 1 + 1 + 1) * sizeof(Real) +
                                   std::size_t(node_count) * sizeof(Real) +
                                   std::size_t(bond_count) * 2 * sizeof(std::uint32_t) + 8 * 16U;
    if (cursor + bond_bytes + (l.has_strain ? node_count + 16U : 0U) <= limit) {
        l.rest_edge = take(std::size_t(3) * bond_count * sizeof(Real));
        l.rest_length = take(std::size_t(bond_count) * sizeof(Real));
        l.rest_length_sq_minus = take(std::size_t(bond_count) * sizeof(Real));
        l.compliance = take(std::size_t(bond_count) * sizeof(Real));
        l.inv_mass = take(std::size_t(node_count) * sizeof(Real));
        l.bond_a = take(std::size_t(bond_count) * sizeof(std::uint32_t));
        l.bond_b = take(std::size_t(bond_count) * sizeof(std::uint32_t));
        l.has_bonds = 1;
    }
    if (l.has_strain) l.node_valid = take(node_count);
    l.total_bytes = cursor;
    return l;
}

struct DeviceStatus {
    unsigned long long steps_completed;
    unsigned long long first_failure_step;
    unsigned long long last_failure_step;
    unsigned failure_rounds;
    unsigned broken_bonds;
    unsigned any_failed;
    unsigned dirty_start;
    unsigned exit_reason;
    unsigned frames_captured;
    unsigned candidate_overflow;
    unsigned padding;
    double removed_energy_j;
    ContactAccumulators contact;
    long long phase_cycles[kPhaseCount];
    // Peak substep strains over the run, as non-negative float bit patterns
    // so atomicMax on int orders them correctly.
    int max_tensile_bits, max_compressive_bits, max_shear_bits;
};

template <typename Real>
struct FrameBuffers {
    Real *u;
    std::uint8_t *alive;
    Real *damage;
    unsigned long long *step;
    SphereState<Real> *sphere;
};

// 512 threads leave 128 registers per thread; the strain sample carries
// several 3x3 matrices and spills under the 64-register cap of 1024 threads.
constexpr unsigned kMaxThreads = 512;

template <typename Real>
__global__ void __launch_bounds__(kMaxThreads, 1)
latticeKernel(LatticeArrays<Real> L, StepSettings<Real> S, DeviceControl C, DeviceStatus *st,
              SphereState<Real> *sphere_ptr, FrameBuffers<Real> F) {
    cg::grid_group grid = cg::this_grid();
    const bool single = gridDim.x == 1U;
    const unsigned block = blockIdx.x, tid = threadIdx.x, nthreads = blockDim.x;
    const bool leader = block == 0U && tid == 0U;
    const unsigned nb = L.node_block_begin[block], ne = L.node_block_begin[block + 1U];
    const unsigned bb = L.bond_block_begin[block], be = L.bond_block_begin[block + 1U];
    const bool direct = S.direct_arithmetic != 0U;
    const unsigned colors = L.color_count;
    const unsigned warps = nthreads >> 5U;
    __shared__ unsigned warp_counts[kMaxThreads / 32U];
    __shared__ unsigned pass_base;
    volatile unsigned *exit_flag = &st->exit_reason;
    volatile unsigned *dirty_flag = &st->dirty_start;
    volatile unsigned *frames_flag = &st->frames_captured;
    // Single-block runs keep the hot state in shared memory: positions (every
    // colour stage), node strain and validity (the resolve phase gathers
    // them) and, when they fit, the bond constants. Copied in here; the
    // mutable parts are copied back before the launch returns.
    extern __shared__ unsigned char shared_raw[];
    __shared__ unsigned s_range_begin[2U * 64U];
    __shared__ unsigned s_range_end[2U * 64U];
    for (unsigned k = tid; k < 2U * colors; k += nthreads) {
        s_range_begin[k] = L.range_begin[block * 2U * colors + k];
        s_range_end[k] = L.range_end[block * 2U * colors + k];
    }
    Real *global_u = L.u;
    Real *global_strain = L.strain;
    std::uint8_t *global_valid = L.node_valid;
    const SharedLayout &lay = C.layout;
    const bool shared_u = single && lay.has_positions != 0U;
    const bool shared_strain = single && lay.has_strain != 0U;
    const bool shared_bonds = single && lay.has_bonds != 0U;
    const auto copyReal = [&](Real *dst, const Real *src, unsigned count) {
        for (unsigned k = tid; k < count; k += nthreads) dst[k] = src[k];
    };
    if (shared_u) copyReal(reinterpret_cast<Real *>(shared_raw + lay.u), global_u, 3U * L.node_count);
    if (shared_strain) {
        copyReal(reinterpret_cast<Real *>(shared_raw + lay.strain), global_strain, 6U * L.node_count);
        for (unsigned k = tid; k < L.node_count; k += nthreads) shared_raw[lay.node_valid + k] = global_valid[k];
    }
    if (shared_bonds) {
        copyReal(reinterpret_cast<Real *>(shared_raw + lay.rest_edge), L.rest_edge, 3U * L.bond_count);
        copyReal(reinterpret_cast<Real *>(shared_raw + lay.rest_length), L.rest_length, L.bond_count);
        copyReal(reinterpret_cast<Real *>(shared_raw + lay.rest_length_sq_minus), L.rest_length_sq_minus, L.bond_count);
        copyReal(reinterpret_cast<Real *>(shared_raw + lay.compliance), L.compliance, L.bond_count);
        copyReal(reinterpret_cast<Real *>(shared_raw + lay.inv_mass), L.inv_mass, L.node_count);
        std::uint32_t *sa = reinterpret_cast<std::uint32_t *>(shared_raw + lay.bond_a);
        std::uint32_t *sb = reinterpret_cast<std::uint32_t *>(shared_raw + lay.bond_b);
        for (unsigned k = tid; k < L.bond_count; k += nthreads) { sa[k] = L.bond_a[k]; sb[k] = L.bond_b[k]; }
    }
    __syncthreads();
    if (shared_u) L.u = reinterpret_cast<Real *>(shared_raw + lay.u);
    if (shared_strain) {
        L.strain = reinterpret_cast<Real *>(shared_raw + lay.strain);
        L.node_valid = shared_raw + lay.node_valid;
    }
    if (shared_bonds) {
        L.rest_edge = reinterpret_cast<const Real *>(shared_raw + lay.rest_edge);
        L.rest_length = reinterpret_cast<const Real *>(shared_raw + lay.rest_length);
        L.rest_length_sq_minus = reinterpret_cast<const Real *>(shared_raw + lay.rest_length_sq_minus);
        L.compliance = reinterpret_cast<const Real *>(shared_raw + lay.compliance);
        L.inv_mass = reinterpret_cast<const Real *>(shared_raw + lay.inv_mass);
        L.bond_a = reinterpret_cast<const std::uint32_t *>(shared_raw + lay.bond_a);
        L.bond_b = reinterpret_cast<const std::uint32_t *>(shared_raw + lay.bond_b);
    }
    float max_tensile = 0.0F, max_compressive = 0.0F, max_shear = 0.0F;
    long long phase_clock = clock64();
    auto mark = [&](unsigned phase) {
        if (leader) {
            const long long now = clock64();
            st->phase_cycles[phase] += now - phase_clock;
            phase_clock = now;
        }
    };

    auto sync = [&]() {
        if (single) __syncthreads();
        else grid.sync();
    };
    auto sweep = [&](unsigned boundary, auto &&body) {
        for (unsigned c = 0; c < colors; ++c) {
            const unsigned rb = s_range_begin[boundary * colors + c], re = s_range_end[boundary * colors + c];
            for (unsigned j = rb + tid; j < re; j += nthreads) body(j);
            __syncthreads();
        }
    };

    for (unsigned long long step = C.step_begin; step < C.step_end; ++step) {
        const unsigned frames_done = *frames_flag;
        const bool capture = C.capture_stride != 0ULL && (step % C.capture_stride) == 0ULL &&
                             frames_done < C.capture_max;
        if (capture) {
            const std::size_t slot = frames_done;
            for (unsigned i = nb + tid; i < ne; i += nthreads) {
                F.u[slot * 3U * L.node_count + 3U * i] = L.u[3U * i];
                F.u[slot * 3U * L.node_count + 3U * i + 1U] = L.u[3U * i + 1U];
                F.u[slot * 3U * L.node_count + 3U * i + 2U] = L.u[3U * i + 2U];
            }
            for (unsigned j = bb + tid; j < be; j += nthreads) {
                F.alive[slot * L.bond_count + j] = L.alive[j];
                F.damage[slot * L.bond_count + j] = L.damage[j];
            }
            if (leader) {
                F.step[slot] = step;
                F.sphere[slot] = *sphere_ptr;
            }
        }
        mark(0); // capture and loop overhead since the previous substep's end
        if (*dirty_flag) {
            for (unsigned i = nb + tid; i < ne; i += nthreads) nodeStrain(L, i, direct);
            sync();
            mark(1);
            for (unsigned j = bb + tid; j < be; j += nthreads)
                if (L.alive[j]) bondStartSample(L, j, direct);
            sync();
            mark(2);
        }

        // Gravity kick, candidate classification, block-ordered compaction.
        {
            SphereState<Real> kicked = *sphere_ptr;
            kicked.velocity = kicked.velocity + S.dt * S.gravity;
            if (tid == 0U) pass_base = 0U;
            __syncthreads();
            for (unsigned base = nb; base < ne; base += nthreads) {
                const unsigned i = base + tid;
                const bool cand = i < ne ? nodeKickAndClassify(L, S, kicked, i) : false;
                const unsigned mask = __ballot_sync(0xffffffffU, cand);
                const unsigned lane = tid & 31U, warp = tid >> 5U;
                if (lane == 0U) warp_counts[warp] = __popc(mask);
                __syncthreads();
                unsigned prefix = 0U, total = 0U;
                for (unsigned w = 0; w < warps; ++w) {
                    if (w < warp) prefix += warp_counts[w];
                    total += warp_counts[w];
                }
                if (cand) {
                    const unsigned slot = pass_base + prefix + __popc(mask & ((1U << lane) - 1U));
                    if (slot < kMaxCandidatesPerBlock)
                        L.candidate_list[block * kMaxCandidatesPerBlock + slot] = i;
                    else
                        atomicAdd(&st->candidate_overflow, 1U);
                }
                __syncthreads();
                if (tid == 0U) pass_base += total;
                __syncthreads();
            }
            if (tid == 0U)
                L.candidate_count[block] = pass_base < kMaxCandidatesPerBlock ? pass_base : kMaxCandidatesPerBlock;
        }
        sync();
        mark(3);
        if (leader) {
            SphereState<Real> s = *sphere_ptr;
            s.velocity = s.velocity + S.dt * S.gravity;
            if (S.sphere_enabled) sphereContactPass(L, S, s, 1, st->contact);
            *sphere_ptr = s;
        }
        sync();
        mark(4);

        for (unsigned iteration = 0; iteration < S.constraint_iterations; ++iteration) {
            const bool first = iteration == 0U;
            sweep(0U, [&](unsigned j) { bondSolve(L, j, S.dt, direct, first); });
            sync();
            mark(5);
            if ((block & 1U) == 0U) sweep(1U, [&](unsigned j) { bondSolve(L, j, S.dt, direct, first); });
            sync();
            if ((block & 1U) == 1U) sweep(1U, [&](unsigned j) { bondSolve(L, j, S.dt, direct, first); });
            sync();
            mark(6);
            for (unsigned i = nb + tid; i < ne; i += nthreads) nodeSupportProject(L, S, i);
            sync();
            mark(7);
        }
        for (unsigned i = nb + tid; i < ne; i += nthreads) nodeVelocityUpdate(L, S, i);
        sync();
        mark(8);
        if (S.damping_fraction > Real(0)) {
            sweep(0U, [&](unsigned j) { bondDamp(L, j, S.damping_fraction, direct); });
            sync();
            if ((block & 1U) == 0U) sweep(1U, [&](unsigned j) { bondDamp(L, j, S.damping_fraction, direct); });
            sync();
            if ((block & 1U) == 1U) sweep(1U, [&](unsigned j) { bondDamp(L, j, S.damping_fraction, direct); });
            sync();
            for (unsigned i = nb + tid; i < ne; i += nthreads)
                if (!L.candidate[i]) nodeSupportVelocity(L, S, i);
            sync();
            mark(9);
        }
        if (leader && S.sphere_enabled) {
            SphereState<Real> s = *sphere_ptr;
            sphereContactPass(L, S, s, 2, st->contact);
            *sphere_ptr = s;
        }
        sync();
        mark(10);
        for (unsigned i = nb + tid; i < ne; i += nthreads) nodeStrain(L, i, direct);
        sync();
        mark(11);
        for (unsigned j = bb + tid; j < be; j += nthreads) {
            if (!L.alive[j]) continue;
            const FailureOutcome out = bondEndSampleAndFailure(L, j, direct);
            max_tensile = fmaxf(max_tensile, out.peak_tensile);
            max_compressive = fmaxf(max_compressive, out.peak_compressive);
            max_shear = fmaxf(max_shear, out.peak_shear);
            if (!out.broke) continue;
            atomicAdd(&st->removed_energy_j, out.removed_energy_j);
            atomicAdd(&st->broken_bonds, 1U);
            st->any_failed = 1U;
            L.node_dirty[L.bond_a[j]] = 1U;
            L.node_dirty[L.bond_b[j]] = 1U;
        }
        sync();
        mark(12);
        if (leader) {
            SphereState<Real> s = *sphere_ptr;
            s.center = s.center + S.dt * s.velocity;
            sphereSupportContact(S, s, st->contact);
            *sphere_ptr = s;
            const unsigned long long completed = step + 1ULL;
            if (st->any_failed) {
                st->dirty_start = 1U;
                if (st->first_failure_step == ~0ULL) st->first_failure_step = step;
                st->last_failure_step = step;
                st->failure_rounds += 1U;
                st->any_failed = 0U;
            } else {
                st->dirty_start = 0U;
            }
            st->steps_completed = completed;
            if (capture) st->frames_captured = frames_done + 1U;
            st->exit_reason = latticeExitReason(completed, st->broken_bonds, st->last_failure_step,
                                                C.quiet_steps, C.min_steps, C.no_failure_steps);
        }
        sync();
        mark(13);
        if (*exit_flag != 0U) break;
    }
    __syncthreads();
    if (shared_u) copyReal(global_u, L.u, 3U * L.node_count);
    if (shared_strain) {
        copyReal(global_strain, L.strain, 6U * L.node_count);
        for (unsigned k = tid; k < L.node_count; k += nthreads) global_valid[k] = L.node_valid[k];
    }
    atomicMax(&st->max_tensile_bits, __float_as_int(max_tensile));
    atomicMax(&st->max_compressive_bits, __float_as_int(max_compressive));
    atomicMax(&st->max_shear_bits, __float_as_int(max_shear));
}

template <typename Real>
class CudaLatticeBackend final : public LatticeBackend {
public:
    CudaLatticeBackend(LatticeSchedule schedule, unsigned threads_per_block)
        : schedule_(std::move(schedule)), threads_(threads_per_block) {
        if (threads_ == 0U || threads_ > kMaxThreads || threads_ % 32U != 0U)
            throw std::invalid_argument("threads per block must be a positive multiple of 32 up to 1024");
        int device = 0;
        check(cudaGetDevice(&device), "get device");
        check(cudaGetDeviceProperties(&properties_, device), "device properties");
        if (!properties_.cooperativeLaunch)
            throw std::runtime_error("CUDA device does not support cooperative launch");
        int per_sm = 0;
        check(cudaOccupancyMaxActiveBlocksPerMultiprocessor(
                  &per_sm, latticeKernel<Real>, static_cast<int>(threads_), 0),
              "occupancy");
        const unsigned resident = static_cast<unsigned>(per_sm) * static_cast<unsigned>(properties_.multiProcessorCount);
        if (schedule_.block_count > resident)
            throw std::runtime_error("lattice schedule needs " + std::to_string(schedule_.block_count) +
                                     " co-resident blocks but the device holds " + std::to_string(resident));
        check(cudaEventCreate(&start_), "event create");
        check(cudaEventCreate(&stop_), "event create");
    }
    ~CudaLatticeBackend() override {
        cudaEventDestroy(start_);
        cudaEventDestroy(stop_);
    }

    [[nodiscard]] std::string name() const override {
        return std::string("cuda-") + (sizeof(Real) == 4 ? "float" : "double") + "-" +
               std::to_string(schedule_.block_count) + "x" + std::to_string(threads_);
    }

    void upload(const LatticeState &state, const StepSettings<double> &settings,
                const SphereState<double> &sphere) override {
        WorkingLattice<Real> w = WorkingLattice<Real>::fromState(state, schedule_);
        node_count_ = w.node_count;
        bond_count_ = w.bond_count;
        S_ = convertSettings<Real>(settings);
        x0_.upload(w.x0); u_.upload(w.u); u_prev_.upload(w.u_prev); v_.upload(w.v);
        inv_mass_.upload(w.inv_mass); mass_.upload(w.mass); rinv_.upload(w.rinv);
        strain_.upload(w.strain); approach_.upload(w.approach);
        node_valid_.upload(w.node_valid); node_dirty_.upload(w.node_dirty);
        engaged_.upload(w.engaged); candidate_.upload(w.candidate);
        adj_offsets_.upload(w.adj_offsets); adj_bonds_.upload(w.adj_bonds);
        nbr_bond_.upload(w.nbr_bond); nbr_other_.upload(w.nbr_other);
        nbr_rest_.upload(w.nbr_rest); nbr_weight_.upload(w.nbr_weight);
        nbr_alive_.upload(w.nbr_alive); bond_slot_a_.upload(w.bond_slot_a); bond_slot_b_.upload(w.bond_slot_b);
        node_block_begin_.upload(w.node_block_begin);
        bond_a_.upload(w.bond_a); bond_b_.upload(w.bond_b);
        rest_edge_.upload(w.rest_edge); rest_length_.upload(w.rest_length);
        rest_length_sq_minus_.upload(w.rest_length_sq_minus); weight_.upload(w.weight);
        compliance_.upload(w.compliance); threshold_.upload(w.threshold);
        alive_.upload(w.alive); damage_.upload(w.damage); failure_mode_.upload(w.failure_mode);
        accumulated_lambda_.upload(w.accumulated_lambda);
        prev_tensile_.upload(w.prev_tensile); prev_compressive_.upload(w.prev_compressive);
        prev_shear_.upload(w.prev_shear);
        range_begin_.upload(w.range_begin); range_end_.upload(w.range_end);
        bond_block_begin_.upload(w.bond_block_begin);
        candidate_list_.upload(w.candidate_list); candidate_count_.upload(w.candidate_count);
        degenerate_.upload(w.degenerate_disagreements);

        L_ = w.arrays();
        L_.x0 = x0_.data(); L_.u = u_.data(); L_.u_prev = u_prev_.data(); L_.v = v_.data();
        L_.inv_mass = inv_mass_.data(); L_.mass = mass_.data(); L_.rinv = rinv_.data();
        L_.node_valid = node_valid_.data(); L_.node_dirty = node_dirty_.data();
        L_.strain = strain_.data(); L_.approach = approach_.data(); L_.engaged = engaged_.data();
        L_.candidate = candidate_.data(); L_.adj_offsets = adj_offsets_.data();
        L_.adj_bonds = adj_bonds_.data(); L_.node_block_begin = node_block_begin_.data();
        L_.nbr_bond = nbr_bond_.data(); L_.nbr_other = nbr_other_.data();
        L_.nbr_rest = nbr_rest_.data(); L_.nbr_weight = nbr_weight_.data();
        L_.nbr_alive = nbr_alive_.data(); L_.bond_slot_a = bond_slot_a_.data(); L_.bond_slot_b = bond_slot_b_.data();
        L_.bond_a = bond_a_.data(); L_.bond_b = bond_b_.data(); L_.rest_edge = rest_edge_.data();
        L_.rest_length = rest_length_.data(); L_.rest_length_sq_minus = rest_length_sq_minus_.data();
        L_.weight = weight_.data(); L_.compliance = compliance_.data(); L_.threshold = threshold_.data();
        L_.alive = alive_.data(); L_.damage = damage_.data(); L_.failure_mode = failure_mode_.data();
        L_.accumulated_lambda = accumulated_lambda_.data(); L_.prev_tensile = prev_tensile_.data();
        L_.prev_compressive = prev_compressive_.data(); L_.prev_shear = prev_shear_.data();
        L_.range_begin = range_begin_.data(); L_.range_end = range_end_.data();
        L_.bond_block_begin = bond_block_begin_.data(); L_.candidate_list = candidate_list_.data();
        L_.candidate_count = candidate_count_.data();
        L_.degenerate_disagreements = degenerate_.data();

        std::vector<SphereState<Real>> sphere_host{convertSphere<Real>(sphere)};
        sphere_.upload(sphere_host);
        DeviceStatus initial{};
        initial.first_failure_step = ~0ULL;
        initial.last_failure_step = ~0ULL;
        initial.dirty_start = 1U;
        clearContactAccumulators(initial.contact);
        std::vector<DeviceStatus> status_host{initial};
        status_.upload(status_host);
        host_status_ = {};
        frame_capacity_ = 0;
        // Shared-memory state for single-block runs, as much as fits.
        layout_ = SharedLayout{};
        if (schedule_.block_count == 1U) {
            int limit = 0;
            check(cudaDeviceGetAttribute(&limit, cudaDevAttrMaxSharedMemoryPerBlockOptin, 0), "shared memory limit");
            // Static shared arrays of the kernel (range cache, compaction) take ~1.2 KB.
            const std::size_t usable = limit > 2048 ? static_cast<std::size_t>(limit) - 2048U : 0U;
            layout_ = planSharedLayout<Real>(node_count_, bond_count_, usable);
            if (layout_.total_bytes > 0U)
                check(cudaFuncSetAttribute(reinterpret_cast<const void *>(latticeKernel<Real>),
                                           cudaFuncAttributeMaxDynamicSharedMemorySize,
                                           static_cast<int>(layout_.total_bytes)),
                      "shared memory attribute");
        }
        host_status_.shared_memory_positions = layout_.has_positions != 0U;
        host_status_.shared_memory_bytes = layout_.total_bytes;
    }

    RunStatus run(const RunControl &control) override {
        const auto begin = std::chrono::steady_clock::now();
        ensureFrames(control.max_frames);
        host_status_.exit_reason = 0;
        std::uint64_t done = 0;
        const std::uint64_t per_launch = control.steps_per_launch == 0 ? control.max_steps : control.steps_per_launch;
        while (done < control.max_steps) {
            const std::uint64_t steps = std::min(per_launch, control.max_steps - done);
            DeviceControl dc{};
            dc.step_begin = host_status_.total_steps;
            dc.step_end = dc.step_begin + steps;
            dc.quiet_steps = control.quiet_steps;
            dc.min_steps = control.min_steps;
            dc.no_failure_steps = control.no_failure_steps;
            dc.capture_stride = control.capture_stride;
            dc.capture_max = control.max_frames;
            dc.layout = layout_;
            FrameBuffers<Real> frames{frame_u_.data(), frame_alive_.data(), frame_damage_.data(),
                                      frame_step_.data(), frame_sphere_.data()};
            DeviceStatus *status_ptr = status_.data();
            SphereState<Real> *sphere_ptr = sphere_.data();
            void *args[] = {&L_, &S_, &dc, &status_ptr, &sphere_ptr, &frames};
            check(cudaEventRecord(start_), "event record");
            check(cudaLaunchCooperativeKernel(reinterpret_cast<const void *>(latticeKernel<Real>),
                                              dim3(schedule_.block_count), dim3(threads_), args, layout_.total_bytes, nullptr),
                  "cooperative launch");
            check(cudaEventRecord(stop_), "event record");
            check(cudaEventSynchronize(stop_), "event synchronize");
            float ms = 0.0F;
            check(cudaEventElapsedTime(&ms, start_, stop_), "event elapsed");
            host_status_.kernel_seconds += ms * 1.0e-3;
            ++host_status_.launches;
            std::vector<DeviceStatus> status_host;
            status_.download(status_host);
            const DeviceStatus &d = status_host.front();
            done += d.steps_completed - host_status_.total_steps;
            host_status_.total_steps = d.steps_completed;
            host_status_.first_failure_step = d.first_failure_step;
            host_status_.last_failure_step = d.last_failure_step;
            for (unsigned p = 0; p < kPhaseCount; ++p)
                host_status_.phase_seconds[p] = static_cast<double>(d.phase_cycles[p]) / (properties_.clockRate * 1.0e3);
            float peak = 0.0F;
            std::memcpy(&peak, &d.max_tensile_bits, sizeof(float));
            host_status_.max_tensile_stretch = peak;
            std::memcpy(&peak, &d.max_compressive_bits, sizeof(float));
            host_status_.max_compressive_strain = peak;
            std::memcpy(&peak, &d.max_shear_bits, sizeof(float));
            host_status_.max_shear_strain = peak;
            std::vector<std::uint32_t> degenerate;
            degenerate_.download(degenerate);
            host_status_.degenerate_disagreements = degenerate.empty() ? 0U : degenerate.front();
            host_status_.failure_rounds = d.failure_rounds;
            host_status_.broken_bonds = d.broken_bonds;
            host_status_.removed_energy_j = d.removed_energy_j;
            host_status_.contact = d.contact;
            host_status_.contact.candidate_overflow = d.candidate_overflow;
            host_status_.frames_captured = d.frames_captured;
            host_status_.exit_reason = d.exit_reason;
            if (d.candidate_overflow != 0U)
                throw std::runtime_error("sphere contact candidate list overflowed a block; "
                                         "reduce the prefilter slack or raise kMaxCandidatesPerBlock");
            if (d.exit_reason != 0U) break;
        }
        if (host_status_.exit_reason == 0U && done >= control.max_steps) host_status_.exit_reason = 3U;
        host_status_.wall_seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
        return host_status_;
    }

    void download(LatticeState &state, SphereState<double> &sphere) override {
        WorkingLattice<Real> w;
        u_.download(w.u); u_prev_.download(w.u_prev); v_.download(w.v);
        alive_.download(w.alive); failure_mode_.download(w.failure_mode); damage_.download(w.damage);
        prev_tensile_.download(w.prev_tensile); prev_compressive_.download(w.prev_compressive);
        prev_shear_.download(w.prev_shear);
        w.toState(state);
        std::vector<SphereState<Real>> s;
        sphere_.download(s);
        sphere = widenSphere(s.front());
    }

    std::vector<FrameCapture> takeFrames() override {
        std::vector<FrameCapture> out;
        const unsigned count = host_status_.frames_captured;
        if (count == 0U) return out;
        std::vector<Real> u, damage;
        std::vector<std::uint8_t> alive;
        std::vector<unsigned long long> step;
        std::vector<SphereState<Real>> sphere;
        frame_u_.download(u, static_cast<std::size_t>(count) * 3U * node_count_);
        frame_alive_.download(alive, static_cast<std::size_t>(count) * bond_count_);
        frame_damage_.download(damage, static_cast<std::size_t>(count) * bond_count_);
        frame_step_.download(step, count);
        frame_sphere_.download(sphere, count);
        out.resize(count);
        for (unsigned f = 0; f < count; ++f) {
            FrameCapture &frame = out[f];
            frame.step = step[f];
            frame.u.resize(3U * node_count_);
            for (std::size_t i = 0; i < frame.u.size(); ++i)
                frame.u[i] = static_cast<float>(u[static_cast<std::size_t>(f) * 3U * node_count_ + i]);
            frame.alive.assign(alive.begin() + static_cast<std::ptrdiff_t>(static_cast<std::size_t>(f) * bond_count_),
                               alive.begin() + static_cast<std::ptrdiff_t>(static_cast<std::size_t>(f + 1U) * bond_count_));
            frame.damage.resize(bond_count_);
            for (std::size_t j = 0; j < bond_count_; ++j)
                frame.damage[j] = static_cast<float>(damage[static_cast<std::size_t>(f) * bond_count_ + j]);
            frame.sphere = widenSphere(sphere[f]);
        }
        // Reset the device frame counter so the next run captures from slot 0.
        std::vector<DeviceStatus> status_host;
        status_.download(status_host);
        status_host.front().frames_captured = 0U;
        status_.upload(status_host);
        host_status_.frames_captured = 0U;
        return out;
    }

    [[nodiscard]] const RunStatus &status() const override { return host_status_; }

private:
    void ensureFrames(unsigned max_frames) {
        if (max_frames <= frame_capacity_) return;
        frame_u_.allocate(static_cast<std::size_t>(max_frames) * 3U * node_count_);
        frame_alive_.allocate(static_cast<std::size_t>(max_frames) * bond_count_);
        frame_damage_.allocate(static_cast<std::size_t>(max_frames) * bond_count_);
        frame_step_.allocate(max_frames);
        frame_sphere_.allocate(max_frames);
        frame_capacity_ = max_frames;
    }

    LatticeSchedule schedule_;
    unsigned threads_;
    cudaDeviceProp properties_{};
    cudaEvent_t start_{}, stop_{};
    std::uint32_t node_count_{}, bond_count_{};
    LatticeArrays<Real> L_{};
    StepSettings<Real> S_{};
    RunStatus host_status_{};
    unsigned frame_capacity_{};
    SharedLayout layout_{};

    DeviceVector<Real> x0_, u_, u_prev_, v_, inv_mass_, mass_, rinv_, strain_, approach_;
    DeviceVector<std::uint8_t> node_valid_, node_dirty_, engaged_, candidate_;
    DeviceVector<std::uint32_t> adj_offsets_, adj_bonds_, node_block_begin_;
    DeviceVector<std::uint32_t> nbr_bond_, nbr_other_;
    DeviceVector<Real> nbr_rest_, nbr_weight_;
    DeviceVector<std::uint8_t> nbr_alive_;
    DeviceVector<std::uint32_t> bond_slot_a_, bond_slot_b_;
    DeviceVector<std::uint32_t> bond_a_, bond_b_;
    DeviceVector<Real> rest_edge_, rest_length_, rest_length_sq_minus_, weight_, compliance_, threshold_;
    DeviceVector<std::uint8_t> alive_, failure_mode_;
    DeviceVector<Real> damage_, accumulated_lambda_, prev_tensile_, prev_compressive_, prev_shear_;
    DeviceVector<std::uint32_t> range_begin_, range_end_, bond_block_begin_;
    DeviceVector<std::uint32_t> candidate_list_, candidate_count_;
    DeviceVector<std::uint32_t> degenerate_;
    DeviceVector<SphereState<Real>> sphere_;
    DeviceVector<DeviceStatus> status_;
    DeviceVector<Real> frame_u_, frame_damage_;
    DeviceVector<std::uint8_t> frame_alive_;
    DeviceVector<unsigned long long> frame_step_;
    DeviceVector<SphereState<Real>> frame_sphere_;
};

} // namespace

bool cudaLatticeAvailable() {
    int count = 0;
    return cudaGetDeviceCount(&count) == cudaSuccess && count > 0;
}

std::string cudaLatticeDescription() {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || count == 0) return "no CUDA device";
    cudaDeviceProp p{};
    if (cudaGetDeviceProperties(&p, 0) != cudaSuccess) return "CUDA device (properties unavailable)";
    int runtime = 0, driver = 0;
    cudaRuntimeGetVersion(&runtime);
    cudaDriverGetVersion(&driver);
    return std::string(p.name) + " sm_" + std::to_string(p.major) + std::to_string(p.minor) + ", " +
           std::to_string(p.multiProcessorCount) + " SMs, runtime " + std::to_string(runtime) +
           ", driver " + std::to_string(driver);
}

unsigned cudaLatticeMultiprocessorCount() {
    int count = 0;
    if (cudaGetDeviceCount(&count) != cudaSuccess || count == 0) return 0;
    cudaDeviceProp p{};
    if (cudaGetDeviceProperties(&p, 0) != cudaSuccess) return 0;
    return static_cast<unsigned>(p.multiProcessorCount);
}

std::unique_ptr<LatticeBackend> makeCudaLatticeBackend(
    const LatticeSchedule &schedule, Precision precision, unsigned threads_per_block) {
    if (!cudaLatticeAvailable()) throw std::runtime_error("no CUDA device is available");
    if (precision == Precision::Float)
        return std::make_unique<CudaLatticeBackend<float>>(schedule, threads_per_block);
    return std::make_unique<CudaLatticeBackend<double>>(schedule, threads_per_block);
}

} // namespace banjo::fastlattice
