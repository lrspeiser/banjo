#include "griffith/GriffithCascade.hpp"

#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCompiler.hpp"
#include "modal/ModalBasis.hpp"

#include <array>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <numbers>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace banjo::griffith {
namespace {

using Clock = std::chrono::steady_clock;

double since(Clock::time_point start) { return std::chrono::duration<double>(Clock::now() - start).count(); }

void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error(message);
}

constexpr std::uint32_t kNoIndex = PlateModel::kNoIndex;
constexpr std::size_t kTimeBlock = 64;
constexpr std::uint32_t kCacheMagic = 0x32474241u; // "ABG2"
constexpr std::uint32_t kCacheVersion = 3u;

// Everything the tables depend on. A cache entry whose key differs anywhere is
// a different object and is never reused: blending an unrelated entry would be
// the silent-reuse failure AGENTS.md names.
struct CacheKey {
    double length_m{}, width_m{}, thickness_m{}, cell_m{}, ball_diameter_m{};
    double ledge_width_m{}, ledge_height_m{};
    double peak_window_transits{}, peak_sample_fraction{};
    std::uint32_t support{}, plate_material{}, horizon{};
    std::uint64_t seed{};
    std::uint32_t cells_x{}, cells_y{}, cells_z{};
    std::uint32_t bonds{}, modes{}, strikes{};
    double sample_dt_s{}, window_s{};
    std::uint32_t samples{};

    [[nodiscard]] bool operator==(const CacheKey &) const = default;
};

CacheKey keyOf(const PlateModel &plate, std::size_t modes, double sample_dt_s, double window_s,
               std::size_t samples) {
    const PlateRequest &r = plate.request;
    CacheKey key;
    key.length_m = r.length_m;
    key.width_m = r.width_m;
    key.thickness_m = r.thickness_m;
    key.cell_m = r.cell_m;
    key.ball_diameter_m = r.ball_diameter_m;
    key.ledge_width_m = r.ledge_width_m;
    key.ledge_height_m = r.ledge_height_m;
    key.peak_window_transits = r.peak_window_transits;
    key.peak_sample_fraction = r.peak_sample_fraction;
    key.support = static_cast<std::uint32_t>(r.support);
    key.plate_material = static_cast<std::uint32_t>(r.plate_material);
    key.horizon = r.horizon;
    key.seed = r.seed;
    key.cells_x = plate.layout.nx;
    key.cells_y = plate.layout.ny;
    key.cells_z = plate.layout.nz;
    key.bonds = static_cast<std::uint32_t>(plate.matter.bonds.size());
    key.modes = static_cast<std::uint32_t>(modes);
    key.strikes = static_cast<std::uint32_t>(plate.strike_nodes.size());
    key.sample_dt_s = sample_dt_s;
    key.window_s = window_s;
    key.samples = static_cast<std::uint32_t>(samples);
    return key;
}

std::string keyDigest(const CacheKey &key) {
    // FNV-1a over the key bytes; the full key is stored in the file and
    // compared exactly on load, so the digest only has to name the file.
    const auto *bytes = reinterpret_cast<const unsigned char *>(&key);
    std::uint64_t hash = 1469598103934665603ull;
    for (std::size_t i = 0; i < sizeof(CacheKey); ++i) {
        hash ^= bytes[i];
        hash *= 1099511628211ull;
    }
    char text[17];
    std::snprintf(text, sizeof text, "%016llx", static_cast<unsigned long long>(hash));
    return text;
}

template <typename T> void writePod(std::ostream &out, const T &value) {
    out.write(reinterpret_cast<const char *>(&value), static_cast<std::streamsize>(sizeof(T)));
}
template <typename T> bool readPod(std::istream &in, T &value) {
    in.read(reinterpret_cast<char *>(&value), static_cast<std::streamsize>(sizeof(T)));
    return static_cast<bool>(in);
}
template <typename T> void writeArray(std::ostream &out, const std::vector<T> &values) {
    const std::uint64_t count = values.size();
    writePod(out, count);
    if (count > 0)
        out.write(reinterpret_cast<const char *>(values.data()),
                  static_cast<std::streamsize>(count * sizeof(T)));
}
template <typename T> bool readArray(std::istream &in, std::vector<T> &values, std::uint64_t expected) {
    std::uint64_t count = 0;
    if (!readPod(in, count) || count != expected) return false;
    values.resize(static_cast<std::size_t>(count));
    if (count > 0)
        in.read(reinterpret_cast<char *>(values.data()), static_cast<std::streamsize>(count * sizeof(T)));
    return static_cast<bool>(in);
}

} // namespace

const char *supportName(SupportKind support) {
    return support == SupportKind::Ledges ? "ledges" : "clamped";
}

const char *criterionName(CriterionKind criterion) {
    return criterion == CriterionKind::Griffith ? "griffith" : "strain";
}

double cutAreaNormalisation(unsigned horizon) {
    require(horizon >= 1, "horizon must be at least one cell");
    const int h = static_cast<int>(horizon);
    double total = 0.0;
    for (int dx = 1; dx <= h; ++dx)
        for (int dy = -h; dy <= h; ++dy)
            for (int dz = -h; dz <= h; ++dz) {
                const double d2 = static_cast<double>(dx * dx + dy * dy + dz * dz);
                if (d2 > static_cast<double>(h) * static_cast<double>(h) + 1.0e-9) continue;
                // A bond of x-span dx crosses a given cut in dx of the cell
                // columns; its elastic-equivalence area is h^2 / (horizon * d).
                total += static_cast<double>(dx) / (static_cast<double>(horizon) * std::sqrt(d2));
            }
    return total;
}

std::unique_ptr<PlateModel> buildPlate(const PlateRequest &request) {
    require(request.length_m > 0 && request.width_m > 0 && request.thickness_m > 0 && request.cell_m > 0,
            "plate dimensions and cell size must be positive");
    require(request.horizon >= 1, "horizon must be at least one cell");
    auto plate = std::make_unique<PlateModel>();
    plate->request = request;

    const double h = request.cell_m;
    const auto count = [&](double extent, const char *name) {
        const long cells = std::lround(extent / h);
        require(cells >= 1, std::string("the plate is thinner than one cell along ") + name);
        require(std::abs(static_cast<double>(cells) * h - extent) <= 0.02 * h,
                std::string("the plate's ") + name + " is not a whole number of cells; cells must stay cubic");
        return static_cast<unsigned>(cells);
    };
    plate->layout.nx = count(request.length_m, "length");
    plate->layout.ny = count(request.thickness_m, "thickness");
    plate->layout.nz = count(request.width_m, "width");

    plate->plate_material = makeReferenceMaterial(request.plate_material, request.seed);
    plate->ball_material = makeReferenceMaterial(request.ball_material, request.seed);
    // The reference lane's own route (fastlattice/TileImpactScene.cpp): the
    // strength-derived failure strains on the elastic lattice reference, so
    // both lanes see identical bond stiffness and identical strain thresholds.
    // That route leaves fracture_energy_j_m2 unset, so Gc is taken from the
    // material definition itself rather than invented here.
    plate->compiled = withStrengthDerivedFailure(
        compileElasticLatticeReference(plate->plate_material, h, request.horizon), plate->plate_material);
    plate->compiled.fracture_energy_j_m2 = plate->plate_material.fracture_energy_j_m2;
    require(plate->compiled.fracture_energy_j_m2 > 0.0,
            "the plate material declares no fracture energy; a Griffith cascade needs Gc");
    plate->young_modulus_pa = plate->plate_material.young_modulus_pa;

    plate->asset = generateBoxLattice(
        {plate->layout.nx, plate->layout.ny, plate->layout.nz, h, request.horizon}, plate->compiled);
    plate->limit = measureLatticeResolutionLimit(plate->asset, plate->compiled);

    // Both supports put the plate the same height above the floor, so the two
    // scenes are watched under identical gravity and fall distance.
    plate->ground_y = 0.0;
    plate->plate_bottom_y = request.ledge_height_m;
    plate->plate_top_y = plate->plate_bottom_y + request.thickness_m;
    plate->origin = {0.0, plate->plate_bottom_y + 0.5 * request.thickness_m, 0.0};

    ActiveMatter &matter = plate->matter;
    matter.body_id = 2;
    matter.asset = &plate->asset;
    matter.material = plate->compiled;
    matter.nodes.reserve(plate->asset.nodes.size());
    matter.reference_positions_world_m.reserve(plate->asset.nodes.size());
    for (const LatticeNodeRest &node : plate->asset.nodes) {
        const Vec3 position = plate->origin + (node.local_position_m - plate->asset.rest_center_of_mass_m);
        const double mass = node.represented_volume_m3 * plate->compiled.density_kg_m3;
        matter.nodes.push_back({position, position, {}, mass, {}});
        matter.reference_positions_world_m.push_back(position);
    }
    matter.bonds.resize(plate->asset.bonds.size());

    // Support.
    const int top_layer = static_cast<int>(plate->layout.ny) - 1;
    const double support_edge = 0.5 * request.length_m - request.ledge_width_m;
    plate->fixed.assign(plate->asset.nodes.size(), 0);
    plate->free_index.assign(plate->asset.nodes.size(), kNoIndex);
    plate->strike_row.assign(plate->asset.nodes.size(), kNoIndex);
    for (std::uint32_t i = 0; i < plate->asset.nodes.size(); ++i) {
        const LatticeNodeRest &node = plate->asset.nodes[i];
        const double x = node.local_position_m.x - plate->asset.rest_center_of_mass_m.x;
        bool held = false;
        if (request.support == SupportKind::Ledges) {
            held = node.grid.y == 0 && std::abs(x) >= support_edge - 1.0e-9;
        } else {
            held = node.grid.x == 0 || node.grid.z == 0 ||
                   node.grid.x + 1 == static_cast<int>(plate->layout.nx) ||
                   node.grid.z + 1 == static_cast<int>(plate->layout.nz);
        }
        plate->fixed[i] = held ? 1 : 0;
        plate->total_mass_kg += matter.nodes[i].mass_kg;
        if (!held) {
            plate->free_index[i] = static_cast<std::uint32_t>(plate->free_nodes.size());
            plate->free_nodes.push_back(i);
            plate->free_mass_kg += matter.nodes[i].mass_kg;
        }
        if (node.grid.y == top_layer) {
            plate->strike_row[i] = static_cast<std::uint32_t>(plate->strike_nodes.size());
            plate->strike_nodes.push_back(i);
        }
    }
    require(!plate->free_nodes.empty(),
            "the support holds every cell; widen the plate or narrow the support");
    require(plate->free_nodes.size() < plate->asset.nodes.size(),
            "no cell is held; a Griffith cascade needs a supported plate for K to be invertible");

    // Per-bond geometry and the crack area that makes a planar cut cost Gc per
    // unit area (see cutAreaNormalisation).
    plate->area_normalisation = cutAreaNormalisation(request.horizon);
    const std::size_t bonds = plate->asset.bonds.size();
    plate->bond_stiffness_n_m.resize(bonds);
    plate->bond_length_m.resize(bonds);
    plate->bond_area_m2.resize(bonds);
    for (std::size_t b = 0; b < bonds; ++b) {
        const BondRest &rest = plate->asset.bonds[b];
        require(rest.compliance > 0.0 && rest.rest_length_m > 0.0, "a bond has no stiffness or length");
        plate->bond_stiffness_n_m[b] = 1.0 / rest.compliance;
        plate->bond_length_m[b] = rest.rest_length_m;
        const double raw_area = plate->bond_stiffness_n_m[b] * rest.rest_length_m / plate->young_modulus_pa;
        plate->bond_area_m2[b] = raw_area / plate->area_normalisation;
    }

    const double radius = 0.5 * request.ball_diameter_m;
    plate->ball_mass_kg = plate->ball_material.density_kg_m3 * 4.0 / 3.0 * std::numbers::pi *
                          radius * radius * radius;

    if (request.support == SupportKind::Ledges) {
        const double ledge_depth = request.width_m + 2.0 * h;
        for (const double sign : {-1.0, 1.0})
            plate->ledges.push_back({{sign * 0.5 * request.length_m, 0.5 * request.ledge_height_m, 0.0},
                                     {2.0 * request.ledge_width_m, request.ledge_height_m, ledge_depth}});
    }
    return plate;
}

// ---------------------------------------------------------------------------
// Precompute
// ---------------------------------------------------------------------------

namespace {

struct BasisTables {
    std::size_t modes{};
    std::vector<double> omega;            // per mode
    std::vector<double> strain_gradient;  // bonds * modes: (g_b . phi_k) / L_b
    std::vector<double> compliance_row;   // bonds * modes: (g_b . phi_k) / omega_k
    std::vector<double> strike_response;  // strikes * modes: phi row of the strike cell's y dof
};

// One strike row's modal impulse coefficients, then the closed-form peak.
void peakColumn(const BasisTables &basis, const std::vector<float> &sin_table, std::size_t samples,
                const std::vector<double> &modal_impulse, float *out, std::size_t bonds) {
    const std::size_t modes = basis.modes;
    std::vector<float> weight(modes);
    for (std::size_t k = 0; k < modes; ++k)
        weight[k] = static_cast<float>(modal_impulse[k] / basis.omega[k]);
    std::fill(out, out + bonds, 0.0f);
    // One block of time samples at a time: the bond-by-mode table is read once
    // per block instead of once per sample, and the innermost loop runs over a
    // contiguous run of kTimeBlock samples.
    std::vector<float> block(modes * kTimeBlock);
    for (std::size_t t0 = 0; t0 < samples; t0 += kTimeBlock) {
        const std::size_t span = std::min(kTimeBlock, samples - t0);
        for (std::size_t k = 0; k < modes; ++k) {
            const float scale = weight[k];
            const float *source = sin_table.data() + k * samples + t0;
            float *target = block.data() + k * kTimeBlock;
            for (std::size_t j = 0; j < span; ++j) target[j] = scale * source[j];
        }
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (std::ptrdiff_t index = 0; index < static_cast<std::ptrdiff_t>(bonds); ++index) {
            const std::size_t b = static_cast<std::size_t>(index);
            const double *row = basis.strain_gradient.data() + b * modes;
            float accumulator[kTimeBlock] = {};
            for (std::size_t k = 0; k < modes; ++k) {
                const float value = static_cast<float>(row[k]);
                if (value == 0.0f) continue;
                const float *source = block.data() + k * kTimeBlock;
                for (std::size_t j = 0; j < span; ++j) accumulator[j] += value * source[j];
            }
            float best = out[b];
            for (std::size_t j = 0; j < span; ++j) best = std::max(best, accumulator[j]);
            out[b] = best;
        }
    }
}

} // namespace

InfluenceTables precompute(const PlateModel &plate, const PrecomputeOptions &options,
                           std::uint32_t strike_row) {
    const auto total_start = Clock::now();
    InfluenceTables tables;
    const std::size_t bonds = plate.matter.bonds.size();
    const std::size_t strikes = plate.strike_nodes.size();
    require(bonds > 0 && strikes > 0, "the plate has no bonds or no strikeable surface");

    const std::size_t influence_bytes = bonds * bonds * sizeof(float);
    require(influence_bytes <= options.maximum_bytes,
            "the crack-influence matrix would need " + std::to_string(influence_bytes / (1024 * 1024)) +
                " MiB for " + std::to_string(bonds) + " bonds; coarsen the cells or shrink the plate");

    // Sampling of the peak response. The window is a stated multiple of the
    // time a longitudinal wave needs to cross the plate's longest side, and the
    // step a stated fraction of the lattice's own explicit substep limit.
    const double wave_speed =
        std::sqrt(plate.young_modulus_pa / plate.compiled.density_kg_m3);
    const double longest = std::max(plate.request.length_m, plate.request.width_m);
    const double window_s = plate.request.peak_window_transits * longest / wave_speed;
    const double sample_dt_s = plate.request.peak_sample_fraction * plate.limit.explicit_substep_limit_s;
    const std::size_t samples = std::max<std::size_t>(
        8, static_cast<std::size_t>(std::llround(window_s / sample_dt_s)));

    tables.bonds = bonds;
    tables.strikes = strikes;
    tables.window_s = window_s;
    tables.sample_dt_s = sample_dt_s;
    tables.samples = samples;
    tables.stats.peak_window_s = window_s;
    tables.stats.peak_sample_dt_s = sample_dt_s;
    tables.stats.peak_samples = samples;
    tables.stats.bonds = bonds;
    tables.stats.strike_cells = strikes;

    const std::size_t modes = 3U * plate.free_nodes.size();
    CacheKey key = keyOf(plate, modes, sample_dt_s, window_s, samples);
    std::filesystem::path cache_path;
    if (!options.cache_dir.empty()) {
        cache_path = std::filesystem::path(options.cache_dir) / ("algo2-" + keyDigest(key) + ".bin");
        tables.stats.path = cache_path.string();
    }

    bool loaded = false;
    if (!cache_path.empty() && std::filesystem::exists(cache_path)) {
        const auto read_start = Clock::now();
        std::ifstream in(cache_path, std::ios::binary);
        std::uint32_t magic = 0, version = 0;
        CacheKey stored{};
        if (in && readPod(in, magic) && magic == kCacheMagic && readPod(in, version) &&
            version == kCacheVersion && readPod(in, stored) && stored == key &&
            readArray(in, tables.release_scale, bonds) &&
            readArray(in, tables.release_singular, bonds) &&
            readArray(in, tables.influence, static_cast<std::uint64_t>(bonds) * bonds) &&
            readArray(in, tables.peak_ready, strikes) &&
            readArray(in, tables.peak, static_cast<std::uint64_t>(strikes) * bonds)) {
            loaded = true;
            tables.modes = modes;
            tables.stats.tables_cached = true;
        } else {
            tables.influence.clear();
            tables.peak.clear();
            tables.peak_ready.clear();
            tables.release_scale.clear();
            tables.release_singular.clear();
        }
        tables.stats.cache_read_s = since(read_start);
    }

    BasisTables basis;
    const auto buildBasis = [&]() {
        modal::ModalBuildTimings timings;
        modal::ModalBasis modal_basis(plate.matter, plate.free_nodes, {}, &timings);
        require(modal_basis.modes() == modes, "the basis lost modes; the plate must be fully supported");
        const auto &omega2 = modal_basis.omegaSquared();
        const double largest = *std::max_element(omega2.begin(), omega2.end());
        basis.modes = modes;
        basis.omega.resize(modes);
        for (std::size_t k = 0; k < modes; ++k) {
            require(omega2[k] > 1.0e-12 * largest,
                    "the supported plate still has a free rigid motion; K is singular and the "
                    "influence matrix cannot be formed");
            basis.omega[k] = std::sqrt(omega2[k]);
        }
        basis.strain_gradient.assign(bonds * modes, 0.0);
        basis.compliance_row.assign(bonds * modes, 0.0);
        const modal::DenseMatrix &phi = modal_basis.phi();
        for (std::size_t b = 0; b < bonds; ++b) {
            const modal::BondGradient gradient = modal_basis.bondGradient(plate.matter, static_cast<std::uint32_t>(b));
            double *strain = basis.strain_gradient.data() + b * modes;
            double *compliance = basis.compliance_row.data() + b * modes;
            for (unsigned i = 0; i < gradient.count; ++i) {
                const double *row = phi.row(gradient.dof[i]);
                const double value = gradient.value[i];
                for (std::size_t k = 0; k < modes; ++k) compliance[k] += value * row[k];
            }
            const double inverse_length = 1.0 / plate.bond_length_m[b];
            for (std::size_t k = 0; k < modes; ++k) {
                strain[k] = compliance[k] * inverse_length;
                compliance[k] /= basis.omega[k];
            }
        }
        basis.strike_response.assign(strikes * modes, 0.0);
        for (std::size_t s = 0; s < strikes; ++s) {
            const std::uint32_t node = plate.strike_nodes[s];
            const std::uint32_t f = plate.free_index[node];
            if (f == kNoIndex) continue;
            const double *row = phi.row(3U * static_cast<std::size_t>(f) + 1U);
            std::copy(row, row + modes, basis.strike_response.begin() + static_cast<std::ptrdiff_t>(s * modes));
        }
        return timings.assemble_s + timings.decompose_s;
    };

    if (!loaded) {
        const auto eigen_start = Clock::now();
        buildBasis();
        tables.stats.eigen_s = since(eigen_start);
        tables.modes = modes;

        // A[b][b'] = (g_b^T K^-1 g_b') / (L_b (1 - k_b' g_b'^T K^-1 g_b')), from
        // Sherman-Morrison on K' = K - k_b' g_b' g_b'^T. K^-1 = phi diag(1/w^2) phi^T,
        // so g_b^T K^-1 g_b' is the inner product of two compliance rows.
        const auto influence_start = Clock::now();
        tables.release_scale.assign(bonds, 0.0);
        tables.release_singular.assign(bonds, 0);
        std::size_t singular = 0;
        for (std::size_t b = 0; b < bonds; ++b) {
            const double *row = basis.compliance_row.data() + b * modes;
            double self = 0.0;
            for (std::size_t k = 0; k < modes; ++k) self += row[k] * row[k];
            const double denominator = 1.0 - plate.bond_stiffness_n_m[b] * self;
            if (denominator < 1.0e-6) {
                // Removing this bond leaves the reduced stiffness singular (it
                // is the last tie of a node). The released force cannot be
                // equilibrated by the rest of the lattice, so it redistributes
                // nothing; the bond is flagged rather than amplified.
                tables.release_scale[b] = 0.0;
                tables.release_singular[b] = 1;
                ++singular;
            } else {
                tables.release_scale[b] = 1.0 / denominator;
            }
        }
        tables.influence.assign(bonds * bonds, 0.0f);
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
        for (std::ptrdiff_t bp = 0; bp < static_cast<std::ptrdiff_t>(bonds); ++bp) {
            const std::size_t prime = static_cast<std::size_t>(bp);
            const double *column_row = basis.compliance_row.data() + prime * modes;
            const double scale = tables.release_scale[prime];
            float *column = tables.influence.data() + prime * bonds;
            if (scale == 0.0) continue;
            for (std::size_t b = 0; b < bonds; ++b) {
                const double *row = basis.compliance_row.data() + b * modes;
                double product = 0.0;
                for (std::size_t k = 0; k < modes; ++k) product += row[k] * column_row[k];
                column[b] = static_cast<float>(product * scale / plate.bond_length_m[b]);
            }
        }
        tables.stats.influence_s = since(influence_start);
        if (singular > 0)
            tables.stats.note = std::to_string(singular) +
                                " bonds are a node's last tie; their release redistributes nothing";
        tables.peak.assign(strikes * bonds, 0.0f);
        tables.peak_ready.assign(strikes, 0);
    }

    // Peak dynamic strain columns. peak_ready is 0 (not built), 1 (built) or
    // 2 (the cell sits on the support and cannot be struck), so a refused cell
    // is not retried on every run.
    require(strike_row == kNoIndex || strike_row < strikes, "strike row outside the strikeable surface");
    std::size_t attempted = 0;
    for (const auto flag : tables.peak_ready) attempted += flag ? 1 : 0;
    const bool needs_requested = strike_row != kNoIndex && tables.peak_ready[strike_row] == 0;
    tables.stats.strike_cached = strike_row != kNoIndex && !needs_requested;
    bool changed = false;
    if (needs_requested || (!options.force_single_strike && attempted < strikes)) {
        if (basis.modes == 0) {
            const auto eigen_start = Clock::now();
            buildBasis();
            tables.stats.eigen_s += since(eigen_start);
        }
        const auto peak_start = Clock::now();
        std::vector<float> sin_table(modes * samples);
        for (std::size_t k = 0; k < modes; ++k) {
            const double omega = basis.omega[k];
            float *row = sin_table.data() + k * samples;
            for (std::size_t t = 0; t < samples; ++t)
                row[t] = static_cast<float>(std::sin(omega * static_cast<double>(t + 1) * sample_dt_s));
        }
        // The load: a unit downward impulse spread over the ball's Hertzian
        // footprint centred on the strike cell. Fixed cells in the footprint
        // take their share into the support and are dropped, and the remaining
        // weights are renormalised.
        const double radius = 0.5 * plate.request.ball_diameter_m;
        const double h = plate.request.cell_m;
        const double contact_radius = std::sqrt(std::max(1.0e-12, radius * h - 0.25 * h * h));
        const auto columnFor = [&](std::size_t s) {
            const std::uint32_t centre = plate.strike_nodes[s];
            const Vec3 origin = plate.matter.reference_positions_world_m[centre];
            std::vector<double> modal_impulse(modes, 0.0);
            double total_weight = 0.0;
            std::vector<std::pair<std::uint32_t, double>> patch;
            for (const std::uint32_t node : plate.strike_nodes) {
                if (plate.free_index[node] == kNoIndex) continue;
                const Vec3 position = plate.matter.reference_positions_world_m[node];
                const double dx = position.x - origin.x, dz = position.z - origin.z;
                const double r = std::sqrt(dx * dx + dz * dz);
                if (r > contact_radius) continue;
                const double weight = std::sqrt(std::max(1.0e-6, 1.0 - (r * r) / (contact_radius * contact_radius)));
                patch.emplace_back(node, weight);
                total_weight += weight;
            }
            if (patch.empty()) {
                if (plate.free_index[centre] == kNoIndex) return false; // the strike lands on the support
                patch.emplace_back(centre, 1.0);
                total_weight = 1.0;
            }
            for (const auto &[node, weight] : patch) {
                const double share = -weight / total_weight; // downward
                const double *phi_row = basis.strike_response.data() +
                                        static_cast<std::size_t>(plate.strike_row[node]) * modes;
                for (std::size_t k = 0; k < modes; ++k) modal_impulse[k] += share * phi_row[k];
            }
            peakColumn(basis, sin_table, samples, modal_impulse, tables.peak.data() + s * bonds, bonds);
            tables.peak_ready[s] = 1;
            return true;
        };

        double one_column_s = 0.0;
        if (needs_requested) {
            const auto one_start = Clock::now();
            const bool built = columnFor(strike_row);
            one_column_s = since(one_start);
            changed = true;
            if (!built) {
                tables.peak_ready[strike_row] = 2;
                require(false, "the strike lands on the support; move the offset onto the free plate");
            }
            ++attempted;
        }
        bool fill_all = options.force_all_strikes;
        if (!fill_all && !options.force_single_strike && attempted < strikes) {
            if (one_column_s <= 0.0) {
                // Measure one column before committing to the rest.
                std::size_t first = strikes;
                for (std::size_t s = 0; s < strikes && first == strikes; ++s)
                    if (tables.peak_ready[s] == 0) first = s;
                if (first < strikes) {
                    const auto one_start = Clock::now();
                    tables.peak_ready[first] = columnFor(first) ? 1 : 2;
                    one_column_s = since(one_start);
                    changed = true;
                    ++attempted;
                }
            }
            const double estimate = one_column_s * static_cast<double>(strikes - attempted);
            fill_all = estimate <= options.all_strikes_budget_s;
            if (!fill_all) {
                tables.stats.note += (tables.stats.note.empty() ? "" : "; ");
                char text[256];
                std::snprintf(text, sizeof text,
                              "peak table built on demand: the remaining %zu strike cells would cost "
                              "an estimated %.1f s against a %.1f s budget",
                              strikes - attempted, estimate, options.all_strikes_budget_s);
                tables.stats.note += text;
            }
        }
        if (fill_all) {
            for (std::size_t s = 0; s < strikes; ++s) {
                if (tables.peak_ready[s] != 0) continue;
                tables.peak_ready[s] = columnFor(s) ? 1 : 2;
                changed = true;
            }
        }
        tables.stats.peak_s = since(peak_start);
    }

    tables.modes = modes;
    tables.stats.modes = modes;
    tables.stats.strike_cells_ready = 0;
    std::size_t attempted_total = 0;
    for (const auto flag : tables.peak_ready) {
        tables.stats.strike_cells_ready += flag == 1 ? 1 : 0;
        attempted_total += flag != 0 ? 1 : 0;
    }
    tables.stats.strikes_complete = attempted_total == strikes;
    tables.stats.bytes = tables.influence.size() * sizeof(float) + tables.peak.size() * sizeof(float) +
                         tables.release_scale.size() * sizeof(double) + tables.peak_ready.size();

    if (!cache_path.empty() && (!loaded || changed)) {
        const auto write_start = Clock::now();
        std::error_code error;
        std::filesystem::create_directories(cache_path.parent_path(), error);
        const std::filesystem::path temporary = cache_path.string() + ".partial";
        {
            std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
            if (out) {
                writePod(out, kCacheMagic);
                writePod(out, kCacheVersion);
                writePod(out, key);
                writeArray(out, tables.release_scale);
                writeArray(out, tables.release_singular);
                writeArray(out, tables.influence);
                writeArray(out, tables.peak_ready);
                writeArray(out, tables.peak);
            }
        }
        std::filesystem::remove(cache_path, error);
        std::filesystem::rename(temporary, cache_path, error);
        if (error) { std::error_code ignored; std::filesystem::remove(temporary, ignored); }
        tables.stats.cache_write_s = since(write_start);
    }
    tables.stats.total_s = since(total_start);
    return tables;
}

// ---------------------------------------------------------------------------
// Contact
// ---------------------------------------------------------------------------

ContactModel buildContact(const PlateModel &plate, double offset_x_m, double offset_z_m, double speed_m_s) {
    ContactModel contact;
    contact.ball_mass_kg = plate.ball_mass_kg;
    contact.speed_m_s = speed_m_s;
    contact.free_mass_kg = plate.free_mass_kg;

    const double radius = 0.5 * plate.request.ball_diameter_m;
    const double h = plate.request.cell_m;
    contact.contact_radius_m = std::sqrt(std::max(1.0e-12, radius * h - 0.25 * h * h));

    // Snap the strike axis to the nearest strikeable cell centre: that is the
    // centre the precomputed peak table is built around.
    double best = 1.0e300;
    for (const std::uint32_t node : plate.strike_nodes) {
        const Vec3 position = plate.matter.reference_positions_world_m[node];
        const double dx = position.x - offset_x_m, dz = position.z - offset_z_m;
        const double distance = std::sqrt(dx * dx + dz * dz);
        if (distance < best) { best = distance; contact.strike_node = node; }
    }
    require(contact.strike_node != kNoIndex, "the plate has no strikeable surface cell");
    contact.strike_snap_m = best;
    contact.strike_row = plate.strike_row[contact.strike_node];

    const Vec3 origin = plate.matter.reference_positions_world_m[contact.strike_node];
    double total_weight = 0.0;
    for (const std::uint32_t node : plate.strike_nodes) {
        if (plate.free_index[node] == kNoIndex) continue;
        const Vec3 position = plate.matter.reference_positions_world_m[node];
        const double dx = position.x - origin.x, dz = position.z - origin.z;
        const double r = std::sqrt(dx * dx + dz * dz);
        if (r > contact.contact_radius_m) continue;
        const double weight = std::sqrt(std::max(1.0e-6,
            1.0 - (r * r) / (contact.contact_radius_m * contact.contact_radius_m)));
        contact.patch_nodes.push_back(node);
        contact.patch_weights.push_back(weight);
        total_weight += weight;
    }
    if (contact.patch_nodes.empty()) {
        require(plate.free_index[contact.strike_node] != kNoIndex,
                "the strike lands on the support; move the offset onto the free plate");
        contact.patch_nodes.push_back(contact.strike_node);
        contact.patch_weights.push_back(1.0);
        total_weight = 1.0;
    }
    double inverse_effective_mass = 0.0;
    for (std::size_t i = 0; i < contact.patch_nodes.size(); ++i) {
        contact.patch_weights[i] /= total_weight;
        const double mass = plate.matter.nodes[contact.patch_nodes[i]].mass_kg;
        inverse_effective_mass += contact.patch_weights[i] * contact.patch_weights[i] / mass;
    }
    contact.patch_mass_kg = 1.0 / inverse_effective_mass;

    const double m_ball = contact.ball_mass_kg;
    contact.reduced_mass_patch_kg = m_ball * contact.patch_mass_kg / (m_ball + contact.patch_mass_kg);
    contact.reduced_mass_plate_kg = m_ball * contact.free_mass_kg / (m_ball + contact.free_mass_kg);
    contact.impulse_n_s = contact.reduced_mass_patch_kg * speed_m_s;
    contact.energy_budget_j = 0.5 * contact.reduced_mass_plate_kg * speed_m_s * speed_m_s;
    contact.ball_speed_after_m_s = speed_m_s - contact.impulse_n_s / std::max(1.0e-12, m_ball);
    contact.model =
        "rigid sphere, restitution zero. Footprint: Hertzian contact radius a = sqrt(R h - h^2/4) at an "
        "indentation of half a cell, impulse spread over the enclosed top-layer cells with weight "
        "sqrt(1 - (r/a)^2). Impulse J = mu_patch v with mu_patch the ball/footprint reduced mass (the "
        "footprint's modal effective mass, since phi phi^T = M^-1). Budget E_in = 0.5 mu_plate v^2 with "
        "mu_plate the ball/unsupported-plate reduced mass: the kinetic energy that leaves the rigid "
        "ledger over the whole contact, not just the first capture.";
    return contact;
}

// ---------------------------------------------------------------------------
// Cascade
// ---------------------------------------------------------------------------

CascadeResult runCascade(PlateModel &plate, const InfluenceTables &tables, const ContactModel &contact,
                         const CascadeOptions &options) {
    const auto start = Clock::now();
    CascadeResult result;
    const std::size_t bonds = plate.matter.bonds.size();
    require(tables.bonds == bonds, "the tables were built for a different plate");
    require(contact.strike_row != kNoIndex && contact.strike_row < tables.strikes,
            "the strike cell has no peak-response column");
    require(tables.peak_ready[contact.strike_row] == 1,
            "the peak-response column for this strike cell was not built");

    const float *peak = tables.peak.data() + static_cast<std::size_t>(contact.strike_row) * bonds;
    const double gc = plate.compiled.fracture_energy_j_m2;
    const double break_stretch = plate.compiled.damage_end_stretch;
    const bool griffith = options.criterion == CriterionKind::Griffith;
    require(griffith || std::isfinite(break_stretch),
            "the strain criterion needs a finite break strain from the compiled material");

    std::vector<double> load(bonds), correction(bonds, 0.0);
    std::vector<char> alive(bonds, 1);
    for (std::size_t b = 0; b < bonds; ++b) {
        load[b] = contact.impulse_n_s * static_cast<double>(peak[b]);
        result.maximum_initial_strain = std::max(result.maximum_initial_strain, load[b]);
        if (!plate.matter.bonds[b].alive) alive[b] = 0;
    }

    const auto driveOf = [&](std::size_t b, double strain) {
        if (strain <= 0.0) return 0.0;
        if (!griffith) return strain / break_stretch;
        const double extension = strain * plate.bond_length_m[b];
        const double stored = 0.5 * plate.bond_stiffness_n_m[b] * extension * extension;
        return stored / (gc * plate.bond_area_m2[b]);
    };

    for (std::size_t b = 0; b < bonds; ++b) {
        if (!alive[b]) continue;
        const double drive = driveOf(b, load[b]);
        if (drive >= 1.0) result.first_failure.push_back(static_cast<std::uint32_t>(b));
        result.first_failure_peak_drive = std::max(result.first_failure_peak_drive, drive);
    }

    result.energy_budget_j = contact.energy_budget_j;
    double budget = contact.energy_budget_j;
    const std::size_t limit = options.maximum_events > 0 ? options.maximum_events : bonds;
    for (std::size_t event = 0; event < limit; ++event) {
        std::size_t best = bonds;
        double best_drive = 1.0;
        double best_strain = 0.0;
        for (std::size_t b = 0; b < bonds; ++b) {
            if (!alive[b]) continue;
            const double strain = load[b] + correction[b];
            const double drive = driveOf(b, strain);
            // Ties go to the lower bond index: the scan keeps the first strict
            // maximum, so the rule is deterministic and order-free.
            if (drive > best_drive) { best_drive = drive; best = b; best_strain = strain; }
        }
        if (best == bonds) break;
        const double crack_work = gc * plate.bond_area_m2[best];
        if (crack_work > budget) { result.budget_exhausted = true; break; }
        budget -= crack_work;
        const double extension = best_strain * plate.bond_length_m[best];
        const double stored = 0.5 * plate.bond_stiffness_n_m[best] * extension * extension;
        const double force = plate.bond_stiffness_n_m[best] * extension;
        result.removed_energy_j += stored;
        result.events.push_back({static_cast<std::uint32_t>(best), best_drive, best_strain, force,
                                 crack_work, stored});
        alive[best] = 0;
        plate.matter.bonds[best].alive = false;
        plate.matter.bonds[best].damage = 1.0;
        plate.matter.bonds[best].failure_mode = BondFailureMode::Tension;
        if (tables.release_singular[best]) result.influence_singular_used = true;
        const float *column = tables.influence.data() + static_cast<std::size_t>(best) * bonds;
        for (std::size_t b = 0; b < bonds; ++b) correction[b] += static_cast<double>(column[b]) * force;
    }
    result.energy_spent_j = contact.energy_budget_j - budget;
    result.energy_remaining_j = budget;
    plate.matter.connectivity_dirty = true;
    result.cascade_wall_s = since(start);

    const auto components = findConnectedComponents(plate.matter);
    result.components = components.size();
    for (const auto &component : components) {
        if (component.node_indices.size() <= result.largest_component_cells) continue;
        result.largest_component_cells = component.node_indices.size();
        double mass = 0.0;
        for (const std::uint32_t node : component.node_indices) mass += plate.matter.nodes[node].mass_kg;
        result.largest_component_mass_kg = mass;
    }
    return result;
}

// ---------------------------------------------------------------------------
// Direct solve (tests)
// ---------------------------------------------------------------------------

std::vector<double> directBondStrains(const PlateModel &plate, const std::vector<double> &force,
                                      const std::vector<char> &bond_alive) {
    const std::size_t n = 3U * plate.free_nodes.size();
    require(force.size() == n, "the load vector must cover every free degree of freedom");
    const std::size_t bonds = plate.matter.bonds.size();
    require(bond_alive.size() == bonds, "the aliveness vector must cover every bond");

    std::vector<double> k(n * n, 0.0);
    std::vector<std::array<std::uint32_t, 6>> dof(bonds);
    std::vector<std::array<double, 6>> value(bonds);
    std::vector<unsigned> count(bonds, 0);
    for (std::size_t b = 0; b < bonds; ++b) {
        const BondRest &rest = plate.asset.bonds[b];
        const Vec3 edge = plate.matter.reference_positions_world_m[rest.node_b] -
                          plate.matter.reference_positions_world_m[rest.node_a];
        const double rest_length = length(edge);
        const Vec3 direction = edge * (1.0 / rest_length);
        const double components[3] = {direction.x, direction.y, direction.z};
        unsigned used = 0;
        const auto add = [&](std::uint32_t node, double sign) {
            const std::uint32_t f = plate.free_index[node];
            if (f == kNoIndex) return;
            for (unsigned c = 0; c < 3; ++c) {
                dof[b][used] = 3U * f + c;
                value[b][used] = sign * components[c];
                ++used;
            }
        };
        add(rest.node_b, 1.0);
        add(rest.node_a, -1.0);
        count[b] = used;
        if (!bond_alive[b]) continue;
        const double stiffness = plate.bond_stiffness_n_m[b];
        for (unsigned i = 0; i < used; ++i)
            for (unsigned j = 0; j < used; ++j)
                k[dof[b][i] * n + dof[b][j]] += stiffness * value[b][i] * value[b][j];
    }

    // Cholesky solve.
    std::vector<double> l = k;
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j <= i; ++j) {
            double sum = l[i * n + j];
            for (std::size_t p = 0; p < j; ++p) sum -= l[i * n + p] * l[j * n + p];
            if (i == j) {
                require(sum > 0.0, "the live lattice is not positive definite; a node is unsupported");
                l[i * n + j] = std::sqrt(sum);
            } else {
                l[i * n + j] = sum / l[j * n + j];
            }
        }
        for (std::size_t j = i + 1; j < n; ++j) l[i * n + j] = 0.0;
    }
    std::vector<double> u = force;
    for (std::size_t i = 0; i < n; ++i) {
        double sum = u[i];
        for (std::size_t p = 0; p < i; ++p) sum -= l[i * n + p] * u[p];
        u[i] = sum / l[i * n + i];
    }
    for (std::size_t i = n; i-- > 0;) {
        double sum = u[i];
        for (std::size_t p = i + 1; p < n; ++p) sum -= l[p * n + i] * u[p];
        u[i] = sum / l[i * n + i];
    }

    std::vector<double> strain(bonds, 0.0);
    for (std::size_t b = 0; b < bonds; ++b) {
        double extension = 0.0;
        for (unsigned i = 0; i < count[b]; ++i) extension += value[b][i] * u[dof[b][i]];
        strain[b] = extension / plate.bond_length_m[b];
    }
    return strain;
}

} // namespace banjo::griffith
