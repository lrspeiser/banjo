// Algorithm 3: the substep as a map, probed from the engine's own backend.

#include "fastlattice/Propagator.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <thread>

namespace banjo::fastlattice {
namespace {

constexpr std::uint64_t kCacheMagic = 0x424a4f414c474f33ULL; // "BJOALGO3"
constexpr std::uint32_t kCacheVersion = 1;

std::uint64_t fnv1a(const std::string &text) {
    std::uint64_t hash = 1469598103934665603ULL;
    for (const char c : text) {
        hash ^= static_cast<std::uint64_t>(static_cast<unsigned char>(c));
        hash *= 1099511628211ULL;
    }
    return hash;
}

} // namespace

// ---------------------------------------------------------------------------
// SubstepMap
// ---------------------------------------------------------------------------

SubstepMap::SubstepMap(const LatticeState &state, const LatticeSchedule &schedule,
                       const StepSettings<double> &settings, Precision precision)
    : pristine_(state), scratch_(state), schedule_(schedule), settings_(settings) {
    settings_.sphere_enabled = 0;
    sphere_.radius = 1.0;
    sphere_.mass = 1.0;
    sphere_.inertia = 1.0;
    sphere_.center = {0.0, 1.0e6, 0.0};
    backend_ = makeCpuLatticeBackend(schedule_, precision);
}

void SubstepMap::pack(const LatticeState &state, double *x) {
    const std::size_t three_n = 3U * static_cast<std::size_t>(state.node_count);
    std::memcpy(x, state.u.data(), three_n * sizeof(double));
    std::memcpy(x + three_n, state.v.data(), three_n * sizeof(double));
}

void SubstepMap::unpack(const double *x, LatticeState &state) {
    const std::size_t three_n = 3U * static_cast<std::size_t>(state.node_count);
    std::memcpy(state.u.data(), x, three_n * sizeof(double));
    std::memcpy(state.v.data(), x + three_n, three_n * sizeof(double));
}

void SubstepMap::apply(const double *x, double *y) {
    // Restore exactly what download() writes; everything else is constant.
    scratch_.u_prev = pristine_.u_prev;
    scratch_.alive = pristine_.alive;
    scratch_.failure_mode = pristine_.failure_mode;
    scratch_.damage = pristine_.damage;
    scratch_.prev_tensile = pristine_.prev_tensile;
    scratch_.prev_compressive = pristine_.prev_compressive;
    scratch_.prev_shear = pristine_.prev_shear;
    unpack(x, scratch_);

    backend_->upload(scratch_, settings_, sphere_);
    RunControl control{};
    control.max_steps = 1;
    backend_->run(control);
    SphereState<double> unused = sphere_;
    backend_->download(scratch_, unused);
    pack(scratch_, y);
    ++applications_;
}

// ---------------------------------------------------------------------------
// Linearity probe
// ---------------------------------------------------------------------------

namespace {

// Random increment of the given amplitude, in the u block alone unless the
// caller asks for the whole state.
void randomIncrement(std::mt19937_64 &rng, std::size_t n, double amplitude, bool displacement_only,
                     std::vector<double> &out) {
    std::uniform_real_distribution<double> dist(-1.0, 1.0);
    const std::size_t half = n / 2;
    for (std::size_t i = 0; i < n; ++i)
        out[i] = (displacement_only && i >= half) ? 0.0 : amplitude * dist(rng);
}

// Worst absolute difference over the u block and over the v block.
void blockMax(const std::vector<double> &a, const std::vector<double> &b, std::size_t n,
              double &u_max, double &v_max) {
    const std::size_t half = n / 2;
    for (std::size_t i = 0; i < half; ++i) u_max = std::max(u_max, std::abs(a[i] - b[i]));
    for (std::size_t i = half; i < n; ++i) v_max = std::max(v_max, std::abs(a[i] - b[i]));
}

} // namespace

LinearityReport probeLinearity(SubstepMap &map, const double *x0, double amplitude,
                               unsigned samples, std::uint64_t seed, bool displacement_only) {
    const std::size_t n = map.dimension(), half = n / 2;
    LinearityReport report{};
    report.amplitude_m = amplitude;
    const std::uint64_t before = map.applications();

    std::vector<double> f0(n), a(n), b(n), work(n), fa(n), fb(n), fab(n), f2a(n);
    map.apply(x0, f0.data());

    std::mt19937_64 rng(seed);
    for (unsigned s = 0; s < samples; ++s) {
        randomIncrement(rng, n, amplitude, displacement_only, a);
        randomIncrement(rng, n, amplitude, displacement_only, b);
        const auto shifted = [&](double scale_a, double scale_b, std::vector<double> &out) {
            for (std::size_t i = 0; i < n; ++i) work[i] = x0[i] + scale_a * a[i] + scale_b * b[i];
            map.apply(work.data(), out.data());
        };
        shifted(1.0, 0.0, fa);
        shifted(0.0, 1.0, fb);
        shifted(1.0, 1.0, fab);
        shifted(2.0, 0.0, f2a);
        for (std::size_t i = 0; i < n; ++i) {
            const double ga = fa[i] - f0[i], gb = fb[i] - f0[i];
            const double gab = fab[i] - f0[i], g2a = f2a[i] - f0[i];
            const double additivity = std::abs(gab - ga - gb);
            const double homogeneity = std::abs(g2a - 2.0 * ga);
            if (i < half) {
                report.u_image = std::max(report.u_image, std::abs(ga));
                report.u_additivity = std::max(report.u_additivity, additivity);
                report.u_homogeneity = std::max(report.u_homogeneity, homogeneity);
            } else {
                report.v_image = std::max(report.v_image, std::abs(ga));
                report.v_additivity = std::max(report.v_additivity, additivity);
                report.v_homogeneity = std::max(report.v_homogeneity, homogeneity);
            }
        }
    }
    const auto ratio = [](double error, double scale) { return scale > 0.0 ? error / scale : 0.0; };
    report.additivity_rel = std::max(ratio(report.u_additivity, report.u_image),
                                     ratio(report.v_additivity, report.v_image));
    report.homogeneity_rel = std::max(ratio(report.u_homogeneity, report.u_image),
                                      ratio(report.v_homogeneity, report.v_image));
    report.substeps = map.applications() - before;
    return report;
}

PropagatorCheck checkPropagator(SubstepMap &map, const DensePropagator &p, double amplitude,
                                unsigned samples, std::uint64_t seed, bool displacement_only) {
    const std::size_t n = map.dimension();
    PropagatorCheck check{};
    check.amplitude_m = amplitude;
    std::vector<double> d(n), x(n), truth(n), predicted(n), zero(n, 0.0);
    std::mt19937_64 rng(seed);
    for (unsigned s = 0; s < samples; ++s) {
        randomIncrement(rng, n, amplitude, displacement_only, d);
        for (std::size_t i = 0; i < n; ++i) x[i] = p.base[i] + d[i];
        map.apply(x.data(), truth.data());
        p.apply(x.data(), predicted.data());
        blockMax(truth, predicted, n, check.u_error, check.v_error);
        blockMax(truth, p.offset, n, check.u_image, check.v_image);
    }
    const auto ratio = [](double error, double scale) { return scale > 0.0 ? error / scale : 0.0; };
    check.rel_error = std::max(ratio(check.u_error, check.u_image), ratio(check.v_error, check.v_image));
    return check;
}

// ---------------------------------------------------------------------------
// Dense propagator
// ---------------------------------------------------------------------------

void DensePropagator::apply(const double *x, double *y) const {
    std::vector<double> d(n);
    for (std::size_t i = 0; i < n; ++i) d[i] = x[i] - base[i];
    std::memcpy(y, offset.data(), n * sizeof(double));
    for (std::size_t j = 0; j < n; ++j) {
        const double s = d[j];
        if (s == 0.0) continue;
        const double *col = columns.data() + j * n;
        for (std::size_t i = 0; i < n; ++i) y[i] += s * col[i];
    }
}

DensePropagator buildPropagator(SubstepMap &map, const double *x0, double eps) {
    const std::size_t n = map.dimension();
    DensePropagator p;
    p.n = n;
    p.power = 1;
    p.base.assign(x0, x0 + n);
    p.offset.assign(n, 0.0);
    p.columns.assign(n * n, 0.0);
    map.apply(x0, p.offset.data());

    std::vector<double> probe(n), image(n);
    const double inverse = 1.0 / eps;
    for (std::size_t j = 0; j < n; ++j) {
        std::memcpy(probe.data(), x0, n * sizeof(double));
        probe[j] += eps;
        map.apply(probe.data(), image.data());
        double *col = p.columns.data() + j * n;
        for (std::size_t i = 0; i < n; ++i) col[i] = (image[i] - p.offset[i]) * inverse;
    }
    return p;
}

namespace {

// C = A * B, all column-major n x n. Eight columns of C at a time so a column
// of A is read once for eight of them.
void gemm(const double *A, const double *B, double *C, std::size_t n, unsigned threads) {
    const auto worker = [&](std::size_t j_begin, std::size_t j_end) {
        constexpr std::size_t kBlock = 8;
        for (std::size_t j0 = j_begin; j0 < j_end; j0 += kBlock) {
            const std::size_t jn = std::min(kBlock, j_end - j0);
            for (std::size_t t = 0; t < jn; ++t)
                std::memset(C + (j0 + t) * n, 0, n * sizeof(double));
            for (std::size_t k = 0; k < n; ++k) {
                const double *a = A + k * n;
                double s[kBlock];
                bool any = false;
                for (std::size_t t = 0; t < jn; ++t) {
                    s[t] = B[k + (j0 + t) * n];
                    any = any || s[t] != 0.0;
                }
                if (!any) continue;
                for (std::size_t t = 0; t < jn; ++t) {
                    if (s[t] == 0.0) continue;
                    double *c = C + (j0 + t) * n;
                    const double scale = s[t];
                    for (std::size_t i = 0; i < n; ++i) c[i] += scale * a[i];
                }
            }
        }
    };
    const unsigned count = std::max(1U, threads);
    if (count == 1) {
        worker(0, n);
        return;
    }
    std::vector<std::thread> pool;
    const std::size_t chunk = ((n + count - 1) / count + 7) / 8 * 8;
    for (unsigned t = 0; t < count; ++t) {
        const std::size_t begin = std::min(n, t * chunk), end = std::min(n, begin + chunk);
        if (begin >= end) break;
        pool.emplace_back(worker, begin, end);
    }
    for (std::thread &thread : pool) thread.join();
}

// out = apply "second" after "first", both around the same base.
DensePropagator compose(const DensePropagator &second, const DensePropagator &first,
                        unsigned threads, double *gemm_seconds) {
    const std::size_t n = first.n;
    DensePropagator out;
    out.n = n;
    out.base = first.base;
    out.power = second.power + first.power;
    out.columns.assign(n * n, 0.0);
    const auto begin = std::chrono::steady_clock::now();
    gemm(second.columns.data(), first.columns.data(), out.columns.data(), n, threads);
    if (gemm_seconds != nullptr)
        *gemm_seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
    // offset = second.P (first.offset - base) + second.offset
    out.offset = second.offset;
    std::vector<double> d(n);
    for (std::size_t i = 0; i < n; ++i) d[i] = first.offset[i] - first.base[i];
    for (std::size_t j = 0; j < n; ++j) {
        const double s = d[j];
        if (s == 0.0) continue;
        const double *col = second.columns.data() + j * n;
        for (std::size_t i = 0; i < n; ++i) out.offset[i] += s * col[i];
    }
    return out;
}

} // namespace

DensePropagator propagatorPower(const DensePropagator &base, std::uint32_t m, unsigned threads,
                                double *gemm_seconds) {
    if (m == 0) throw std::invalid_argument("propagator power must be at least 1");
    DensePropagator result;
    DensePropagator square = base;
    bool have = false;
    std::uint32_t remaining = m;
    while (remaining > 0) {
        if ((remaining & 1U) != 0U) {
            result = have ? compose(square, result, threads, gemm_seconds) : square;
            have = true;
        }
        remaining >>= 1U;
        if (remaining > 0) square = compose(square, square, threads, gemm_seconds);
    }
    result.power = m;
    return result;
}

// ---------------------------------------------------------------------------
// Causal cone
// ---------------------------------------------------------------------------

std::vector<ConeGrowth> measureCone(SubstepMap &map, const double *x0, std::uint32_t seed_node,
                                    double delta, const std::vector<std::uint64_t> &checkpoints,
                                    double cell_size_m) {
    const std::size_t n = map.dimension();
    const std::uint32_t nodes = map.nodeCount();
    const LatticeState &reference = map.referenceState();
    std::vector<double> plain(x0, x0 + n), shaken(x0, x0 + n), work(n);
    shaken[3U * seed_node] += delta;

    const double sx = reference.x0[3U * seed_node];
    const double sy = reference.x0[3U * seed_node + 1];
    const double sz = reference.x0[3U * seed_node + 2];

    std::vector<ConeGrowth> out;
    std::uint64_t done = 0;
    for (const std::uint64_t target : checkpoints) {
        while (done < target) {
            map.apply(plain.data(), work.data());
            plain.swap(work);
            map.apply(shaken.data(), work.data());
            shaken.swap(work);
            ++done;
        }
        ConeGrowth growth{};
        growth.substeps = done;
        for (std::uint32_t i = 0; i < nodes; ++i) {
            bool touched = false;
            for (unsigned k = 0; k < 3; ++k) {
                const double du = std::abs(shaken[3U * i + k] - plain[3U * i + k]);
                const double dv = std::abs(shaken[3U * nodes + 3U * i + k] - plain[3U * nodes + 3U * i + k]);
                if (du != 0.0 || dv != 0.0) touched = true;
                growth.max_du_m = std::max(growth.max_du_m, du);
            }
            if (!touched) continue;
            ++growth.touched_nodes;
            const double dx = reference.x0[3U * i] - sx;
            const double dy = reference.x0[3U * i + 1] - sy;
            const double dz = reference.x0[3U * i + 2] - sz;
            growth.max_cell_distance =
                std::max(growth.max_cell_distance, std::sqrt(dx * dx + dy * dy + dz * dz) / cell_size_m);
        }
        growth.touched_fraction = nodes > 0 ? static_cast<double>(growth.touched_nodes) / nodes : 0.0;
        out.push_back(growth);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Cache
// ---------------------------------------------------------------------------

std::string PropagatorCacheKey::fileName() const {
    std::ostringstream name;
    name << "algo3-" << std::hex << fnv1a(scene) << std::dec << "-p" << power << ".bin";
    return name.str();
}

bool loadPropagator(const std::filesystem::path &dir, const PropagatorCacheKey &key, DensePropagator &out) {
    const std::filesystem::path path = dir / key.fileName();
    std::error_code ec;
    if (!std::filesystem::exists(path, ec)) return false;
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::uint64_t magic = 0;
    std::uint32_t version = 0, power = 0;
    std::uint64_t n = 0, scene_hash = 0;
    in.read(reinterpret_cast<char *>(&magic), sizeof(magic));
    in.read(reinterpret_cast<char *>(&version), sizeof(version));
    in.read(reinterpret_cast<char *>(&power), sizeof(power));
    in.read(reinterpret_cast<char *>(&n), sizeof(n));
    in.read(reinterpret_cast<char *>(&scene_hash), sizeof(scene_hash));
    if (!in || magic != kCacheMagic || version != kCacheVersion || power != key.power ||
        scene_hash != fnv1a(key.scene) || n == 0 || n > 200000)
        return false;
    out.n = static_cast<std::size_t>(n);
    out.power = power;
    out.base.resize(out.n);
    out.offset.resize(out.n);
    out.columns.resize(out.n * out.n);
    in.read(reinterpret_cast<char *>(out.base.data()), static_cast<std::streamsize>(out.n * sizeof(double)));
    in.read(reinterpret_cast<char *>(out.offset.data()), static_cast<std::streamsize>(out.n * sizeof(double)));
    in.read(reinterpret_cast<char *>(out.columns.data()),
            static_cast<std::streamsize>(out.columns.size() * sizeof(double)));
    return static_cast<bool>(in);
}

bool storePropagator(const std::filesystem::path &dir, const PropagatorCacheKey &key,
                     const DensePropagator &p) {
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    const std::filesystem::path path = dir / key.fileName();
    const std::filesystem::path temporary = dir / (key.fileName() + ".partial");
    {
        std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
        if (!out) return false;
        const std::uint64_t magic = kCacheMagic;
        const std::uint32_t version = kCacheVersion, power = p.power;
        const std::uint64_t n = p.n, scene_hash = fnv1a(key.scene);
        out.write(reinterpret_cast<const char *>(&magic), sizeof(magic));
        out.write(reinterpret_cast<const char *>(&version), sizeof(version));
        out.write(reinterpret_cast<const char *>(&power), sizeof(power));
        out.write(reinterpret_cast<const char *>(&n), sizeof(n));
        out.write(reinterpret_cast<const char *>(&scene_hash), sizeof(scene_hash));
        out.write(reinterpret_cast<const char *>(p.base.data()),
                  static_cast<std::streamsize>(p.base.size() * sizeof(double)));
        out.write(reinterpret_cast<const char *>(p.offset.data()),
                  static_cast<std::streamsize>(p.offset.size() * sizeof(double)));
        out.write(reinterpret_cast<const char *>(p.columns.data()),
                  static_cast<std::streamsize>(p.columns.size() * sizeof(double)));
        if (!out) return false;
    }
    std::filesystem::rename(temporary, path, ec);
    if (ec) {
        std::filesystem::remove(path, ec);
        std::filesystem::rename(temporary, path, ec);
    }
    return !ec;
}

} // namespace banjo::fastlattice
