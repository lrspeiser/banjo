#include "algo1/ImpulseLibrary.hpp"

#include "modal/SymmetricEigen.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <numbers>
#include <sstream>
#include <stdexcept>
#include <utility>

#ifdef _OPENMP
#include <omp.h>
#endif

namespace banjo::algo1 {
namespace {

using Clock = std::chrono::steady_clock;
double since(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

constexpr char kMagic[8] = {'B', 'A', 'N', 'J', 'O', 'A', '1', 'L'};
constexpr std::uint32_t kVersion = 1U;
// How many bonds share one pass over phi when the compliance block is formed.
constexpr std::size_t kComplianceBlock = 16;

std::uint64_t hash64(const std::string &text) {
    std::uint64_t value = 1469598103934665603ULL;
    for (const char character : text) {
        value ^= static_cast<std::uint8_t>(character);
        value *= 1099511628211ULL;
    }
    return value;
}

template <typename T>
void writePod(std::ostream &out, const T &value) {
    out.write(reinterpret_cast<const char *>(&value), sizeof(T));
}

template <typename T>
bool readPod(std::istream &in, T &value) {
    in.read(reinterpret_cast<char *>(&value), sizeof(T));
    return static_cast<bool>(in);
}

} // namespace

std::string libraryKey(const std::string &material, unsigned nx, unsigned ny, unsigned nz,
                       double cell_m, unsigned horizon, std::uint64_t seed,
                       const std::string &support, double ledge_width_m) {
    std::ostringstream key;
    key.precision(17);
    key << "v1|" << material << '|' << nx << 'x' << ny << 'x' << nz << '|' << cell_m << '|'
        << horizon << '|' << seed << '|' << support << '|' << ledge_width_m;
    return key.str();
}

void ImpulseLibrary::buildTopology(const ActiveMatter &matter, const std::vector<std::uint8_t> &dof_free) {
    const std::size_t nodes = matter.nodes.size();
    if (dof_free.size() != 3U * nodes) throw std::invalid_argument("dof mask must cover 3 * nodes");
    free_dof_of_.assign(3U * nodes, kFixedDof);
    dof_of_free_.clear();
    dof_mass_.clear();
    for (std::size_t dof = 0; dof < 3U * nodes; ++dof) {
        if (!dof_free[dof]) continue;
        free_dof_of_[dof] = static_cast<std::uint32_t>(dof_of_free_.size());
        dof_of_free_.push_back(static_cast<std::uint32_t>(dof));
        dof_mass_.push_back(matter.nodes[dof / 3U].mass_kg);
    }
    if (dof_of_free_.empty()) throw std::invalid_argument("the support holds every degree of freedom");

    loose_dof_.assign(dof_of_free_.size(), 1U);
    gradients_.assign(matter.bonds.size(), BondGradient{});
    for (std::size_t bond = 0; bond < matter.bonds.size(); ++bond) {
        const BondRest &rest = matter.asset->bonds[bond];
        BondGradient &gradient = gradients_[bond];
        const Vec3 edge = matter.reference_positions_world_m[rest.node_b] -
                          matter.reference_positions_world_m[rest.node_a];
        const double rest_length = length(edge);
        gradient.rest_length_m = rest_length;
        gradient.stiffness_n_m = rest.compliance > 0.0 ? 1.0 / rest.compliance : 0.0;
        gradient.break_strain = std::min({rest.damage_end_stretch, rest.compression_damage_end_strain,
                                          rest.shear_damage_end_strain});
        if (rest_length <= 1.0e-12) continue;
        const Vec3 direction = edge * (1.0 / rest_length);
        const double component[3] = {direction.x, direction.y, direction.z};
        // e = (x_b - x_a) . d, so the gradient is +d at b and -d at a.
        for (const auto &[node, sign] : {std::pair<std::uint32_t, double>{rest.node_a, -1.0},
                                         std::pair<std::uint32_t, double>{rest.node_b, 1.0}}) {
            for (unsigned axis = 0; axis < 3U; ++axis) {
                const std::uint32_t free_index = free_dof_of_[3U * node + axis];
                if (free_index == kFixedDof) continue;
                gradient.dof[gradient.count] = free_index;
                gradient.value[gradient.count] = sign * component[axis];
                if (gradient.stiffness_n_m > 0.0 && component[axis] != 0.0) loose_dof_[free_index] = 0U;
                ++gradient.count;
            }
        }
    }
}

modal::DenseMatrix ImpulseLibrary::assembleScaledStiffness(const ActiveMatter &matter) const {
    const std::size_t n = dofs();
    modal::DenseMatrix scaled(n, n);
    std::vector<double> inverse_root(n);
    for (std::size_t dof = 0; dof < n; ++dof) inverse_root[dof] = 1.0 / std::sqrt(dof_mass_[dof]);
    for (std::size_t bond = 0; bond < gradients_.size(); ++bond) {
        if (!matter.bonds[bond].alive) continue;
        const BondGradient &gradient = gradients_[bond];
        const double stiffness = gradient.stiffness_n_m;
        if (!(stiffness > 0.0)) continue;
        for (unsigned p = 0; p < gradient.count; ++p) {
            const std::uint32_t row = gradient.dof[p];
            const double left = gradient.value[p] * inverse_root[row];
            for (unsigned q = 0; q < gradient.count; ++q) {
                const std::uint32_t column = gradient.dof[q];
                scaled(row, column) += stiffness * left * gradient.value[q] * inverse_root[column];
            }
        }
    }
    return scaled;
}

void ImpulseLibrary::decompose(const ActiveMatter &matter) {
    const auto assemble_start = Clock::now();
    modal::DenseMatrix scaled = assembleScaledStiffness(matter);
    const std::size_t n = dofs();

    // A free degree of freedom whose stiffness row is identically zero carries
    // no elastic force at all: it is a mechanism, not a mode. A plate one cell
    // thick has every bond in the mid-plane, so every out-of-plane dof is one of
    // these. They are separated out here rather than handed to the eigensolver,
    // for three reasons: their eigenpair is known exactly (omega = 0, phi =
    // e_d / sqrt(m_d)); several hundred exactly equal eigenvalues make the
    // implicit-QL deflation test (relative to |d_m| + |d_m+1|, which is zero
    // here) fail to converge; and the remaining problem is much smaller.
    std::vector<std::uint32_t> coupled;
    std::vector<std::uint32_t> loose;
    coupled.reserve(n);
    for (std::size_t dof = 0; dof < n; ++dof) {
        if (loose_dof_[dof] != 0U) loose.push_back(static_cast<std::uint32_t>(dof));
        else coupled.push_back(static_cast<std::uint32_t>(dof));
    }
    stats_.assemble_s = since(assemble_start);

    const auto decompose_start = Clock::now();
    const std::size_t reduced = coupled.size();
    modal::DenseMatrix block(reduced, reduced);
    for (std::size_t row = 0; row < reduced; ++row) {
        const double *source = scaled.row(coupled[row]);
        double *target = block.row(row);
        for (std::size_t column = 0; column < reduced; ++column) target[column] = source[coupled[column]];
    }
    scaled = modal::DenseMatrix{};
    modal::SymmetricEigenDecomposition decomposition = modal::decomposeSymmetric(block);
    stats_.decompose_s = since(decompose_start);

    omega2_.assign(n, 0.0);
    phi_ = modal::DenseMatrix(n, n);
    for (std::size_t mode = 0; mode < reduced; ++mode) omega2_[mode] = decomposition.values[mode];
    for (std::size_t row = 0; row < reduced; ++row) {
        const double *source = decomposition.vectors.row(row);
        double *target = phi_.row(coupled[row]);
        for (std::size_t mode = 0; mode < reduced; ++mode) target[mode] = source[mode];
    }
    for (std::size_t index = 0; index < loose.size(); ++index)
        phi_(loose[index], reduced + index) = 1.0;
    // phi = M^-1/2 v, so phi^T M phi = I and K phi = omega^2 M phi.
    for (std::size_t dof = 0; dof < n; ++dof) {
        const double scale = 1.0 / std::sqrt(dof_mass_[dof]);
        double *row = phi_.row(dof);
        for (std::size_t mode = 0; mode < phi_.cols; ++mode) row[mode] *= scale;
    }
}

void ImpulseLibrary::classifyModes() {
    const std::size_t m = omega2_.size();
    double largest = 0.0;
    for (const double value : omega2_) largest = std::max(largest, value);
    const double threshold = options_.rigid_relative_threshold * largest;
    rigid_.assign(m, 0U);
    omega_.assign(m, 0.0);
    stats_.rigid_modes = 0;
    stats_.omega_max_rad_s = 0.0;
    stats_.omega_min_elastic_rad_s = 0.0;
    for (std::size_t mode = 0; mode < m; ++mode) {
        if (omega2_[mode] <= threshold) {
            omega2_[mode] = 0.0;
            rigid_[mode] = 1U;
            ++stats_.rigid_modes;
            continue;
        }
        omega_[mode] = std::sqrt(omega2_[mode]);
        stats_.omega_max_rad_s = std::max(stats_.omega_max_rad_s, omega_[mode]);
        stats_.omega_min_elastic_rad_s = stats_.omega_min_elastic_rad_s == 0.0
            ? omega_[mode]
            : std::min(stats_.omega_min_elastic_rad_s, omega_[mode]);
    }
    stats_.fastest_period_s = stats_.omega_max_rad_s > 0.0 ? 2.0 * std::numbers::pi / stats_.omega_max_rad_s : 0.0;
}

void ImpulseLibrary::buildAmplitudes() {
    const auto start = Clock::now();
    const std::size_t m = modes();
    const std::size_t bonds = gradients_.size();
    amplitude_ = modal::DenseMatrix(bonds, m);
    // A mechanism is a zero-frequency mode that still strains a bond: the model
    // has no restoring force for it, so its amplitude grows without bound in
    // time. Count them here, where the evidence is.
    std::vector<std::uint8_t> strains_a_bond(m, 0U);
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::ptrdiff_t index = 0; index < static_cast<std::ptrdiff_t>(bonds); ++index) {
        const std::size_t bond = static_cast<std::size_t>(index);
        const BondGradient &gradient = gradients_[bond];
        double *out = amplitude_.row(bond);
        std::fill(out, out + m, 0.0);
        if (!(gradient.rest_length_m > 0.0)) continue;
        const double inverse_length = 1.0 / gradient.rest_length_m;
        for (unsigned p = 0; p < gradient.count; ++p) {
            const double *row = phi_.row(gradient.dof[p]);
            const double weight = gradient.value[p] * inverse_length;
            for (std::size_t mode = 0; mode < m; ++mode) out[mode] += weight * row[mode];
        }
    }
    // A mode's amplitude scale: the largest |a(b,i)| over bonds.
    std::vector<double> peak(m, 0.0);
    for (std::size_t bond = 0; bond < bonds; ++bond) {
        const double *row = amplitude_.row(bond);
        for (std::size_t mode = 0; mode < m; ++mode) peak[mode] = std::max(peak[mode], std::abs(row[mode]));
    }
    double largest_peak = 0.0;
    for (const double value : peak) largest_peak = std::max(largest_peak, value);
    stats_.straining_rigid_modes = 0;
    for (std::size_t mode = 0; mode < m; ++mode) {
        strains_a_bond[mode] = peak[mode] > 1.0e-9 * largest_peak ? 1U : 0U;
        if (rigid_[mode] != 0U && strains_a_bond[mode] != 0U) ++stats_.straining_rigid_modes;
    }
    stats_.amplitude_s = since(start);
    stats_.amplitude_bytes = amplitude_.data.size() * sizeof(double);
}

void ImpulseLibrary::buildCompliance(const LibraryOptions &options) {
    const auto start = Clock::now();
    const std::size_t n = dofs();
    const std::size_t m = modes();
    const std::size_t bonds = gradients_.size();
    const std::size_t bytes = bonds * n * sizeof(double);
    stats_.compliance_bytes = bytes;
    stats_.compliance_stored = bytes <= options.compliance_budget_bytes;
    if (!stats_.compliance_stored) {
        stats_.compliance_s = since(start);
        return;
    }
    compliance_ = modal::DenseMatrix(bonds, n);
    const std::size_t blocks = (bonds + kComplianceBlock - 1) / kComplianceBlock;
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::ptrdiff_t block_index = 0; block_index < static_cast<std::ptrdiff_t>(blocks); ++block_index) {
        const std::size_t first = static_cast<std::size_t>(block_index) * kComplianceBlock;
        const std::size_t last = std::min(first + kComplianceBlock, bonds);
        const std::size_t width = last - first;
        // z(b, i) = L_b a(b, i) / omega_i^2, zero on rigid modes: the
        // pseudo-inverse drops the null space, which every bond gradient is
        // orthogonal to by construction.
        std::vector<double> weighted(width * m, 0.0);
        for (std::size_t local = 0; local < width; ++local) {
            const double *row = amplitude_.row(first + local);
            const double rest_length = gradients_[first + local].rest_length_m;
            double *out = weighted.data() + local * m;
            for (std::size_t mode = 0; mode < m; ++mode)
                out[mode] = rigid_[mode] != 0U ? 0.0 : rest_length * row[mode] / omega2_[mode];
        }
        double accumulator[kComplianceBlock];
        for (std::size_t dof = 0; dof < n; ++dof) {
            const double *phi_row = phi_.row(dof);
            for (std::size_t local = 0; local < width; ++local) {
                const double *weight = weighted.data() + local * m;
                double sum = 0.0;
                for (std::size_t mode = 0; mode < m; ++mode) sum += weight[mode] * phi_row[mode];
                accumulator[local] = sum;
            }
            for (std::size_t local = 0; local < width; ++local)
                compliance_(first + local, dof) = accumulator[local];
        }
    }
    stats_.compliance_s = since(start);
}

const double *ImpulseLibrary::complianceColumn(std::uint32_t bond, std::vector<double> &scratch) const {
    if (stats_.compliance_stored) return compliance_.row(bond);
    const std::size_t n = dofs();
    const std::size_t m = modes();
    scratch.assign(n, 0.0);
    std::vector<double> weighted(m, 0.0);
    const double *row = amplitude_.row(bond);
    const double rest_length = gradients_[bond].rest_length_m;
    for (std::size_t mode = 0; mode < m; ++mode)
        weighted[mode] = rigid_[mode] != 0U ? 0.0 : rest_length * row[mode] / omega2_[mode];
    for (std::size_t dof = 0; dof < n; ++dof) {
        const double *phi_row = phi_.row(dof);
        double sum = 0.0;
        for (std::size_t mode = 0; mode < m; ++mode) sum += weighted[mode] * phi_row[mode];
        scratch[dof] = sum;
    }
    return scratch.data();
}

double ImpulseLibrary::bondExtension(std::uint32_t bond, const std::vector<double> &field) const {
    const BondGradient &gradient = gradients_[bond];
    double sum = 0.0;
    for (unsigned p = 0; p < gradient.count; ++p) sum += gradient.value[p] * field[gradient.dof[p]];
    return sum;
}

void ImpulseLibrary::displacement(const std::vector<double> &q, std::vector<double> &out) const {
    const std::size_t n = dofs();
    const std::size_t m = modes();
    out.assign(n, 0.0);
#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::ptrdiff_t index = 0; index < static_cast<std::ptrdiff_t>(n); ++index) {
        const double *row = phi_.row(static_cast<std::size_t>(index));
        double sum = 0.0;
        for (std::size_t mode = 0; mode < m; ++mode) sum += row[mode] * q[mode];
        out[static_cast<std::size_t>(index)] = sum;
    }
}

Vec3 ImpulseLibrary::nodeDisplacement(const std::vector<double> &q, std::uint32_t node) const {
    const std::size_t m = modes();
    double component[3] = {0.0, 0.0, 0.0};
    for (unsigned axis = 0; axis < 3U; ++axis) {
        const std::uint32_t free_index = free_dof_of_[3U * node + axis];
        if (free_index == kFixedDof) continue;
        const double *row = phi_.row(free_index);
        double sum = 0.0;
        for (std::size_t mode = 0; mode < m; ++mode) sum += row[mode] * q[mode];
        component[axis] = sum;
    }
    return {component[0], component[1], component[2]};
}

Vec3 ImpulseLibrary::nodeValue(const std::vector<double> &field, std::uint32_t node) const {
    double component[3] = {0.0, 0.0, 0.0};
    for (unsigned axis = 0; axis < 3U; ++axis) {
        const std::uint32_t free_index = free_dof_of_[3U * node + axis];
        if (free_index != kFixedDof) component[axis] = field[free_index];
    }
    return {component[0], component[1], component[2]};
}

void ImpulseLibrary::addNodeImpulse(std::vector<double> &qdot, std::uint32_t node, const Vec3 &impulse) const {
    const std::size_t m = modes();
    const double component[3] = {impulse.x, impulse.y, impulse.z};
    for (unsigned axis = 0; axis < 3U; ++axis) {
        const std::uint32_t free_index = free_dof_of_[3U * node + axis];
        if (free_index == kFixedDof || component[axis] == 0.0) continue;
        const double *row = phi_.row(free_index);
        const double weight = component[axis];
        for (std::size_t mode = 0; mode < m; ++mode) qdot[mode] += weight * row[mode];
    }
}

bool ImpulseLibrary::readCache(const std::filesystem::path &path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    char magic[8]{};
    in.read(magic, 8);
    if (!in || std::memcmp(magic, kMagic, 8) != 0) return false;
    std::uint32_t version = 0;
    if (!readPod(in, version) || version != kVersion) return false;
    std::uint64_t key_length = 0, dof_count = 0, mode_count = 0, node_count = 0;
    if (!readPod(in, key_length)) return false;
    std::string key(static_cast<std::size_t>(key_length), '\0');
    in.read(key.data(), static_cast<std::streamsize>(key_length));
    if (!in) return false;
    if (!readPod(in, dof_count) || !readPod(in, mode_count) || !readPod(in, node_count)) return false;
    if (dof_count != dofs() || node_count != free_dof_of_.size() / 3U) return false;
    std::vector<std::uint32_t> map(static_cast<std::size_t>(dof_count));
    in.read(reinterpret_cast<char *>(map.data()), static_cast<std::streamsize>(dof_count * sizeof(std::uint32_t)));
    if (!in || map != dof_of_free_) return false;
    std::vector<double> mass(static_cast<std::size_t>(dof_count));
    in.read(reinterpret_cast<char *>(mass.data()), static_cast<std::streamsize>(dof_count * sizeof(double)));
    if (!in) return false;
    for (std::size_t dof = 0; dof < mass.size(); ++dof)
        if (std::abs(mass[dof] - dof_mass_[dof]) > 1.0e-12 * std::max(1.0, dof_mass_[dof])) return false;
    omega2_.assign(static_cast<std::size_t>(mode_count), 0.0);
    in.read(reinterpret_cast<char *>(omega2_.data()), static_cast<std::streamsize>(mode_count * sizeof(double)));
    phi_ = modal::DenseMatrix(static_cast<std::size_t>(dof_count), static_cast<std::size_t>(mode_count));
    in.read(reinterpret_cast<char *>(phi_.data.data()),
            static_cast<std::streamsize>(phi_.data.size() * sizeof(double)));
    if (!in) return false;
    return true;
}

void ImpulseLibrary::writeCache(const std::filesystem::path &path, const std::string &key) {
    std::error_code code;
    std::filesystem::create_directories(path.parent_path(), code);
    const std::filesystem::path temporary = path.string() + ".partial";
    {
        std::ofstream out(temporary, std::ios::binary);
        if (!out) return;
        out.write(kMagic, 8);
        writePod(out, kVersion);
        const std::uint64_t key_length = key.size();
        writePod(out, key_length);
        out.write(key.data(), static_cast<std::streamsize>(key.size()));
        const std::uint64_t dof_count = dofs(), mode_count = modes(), node_count = free_dof_of_.size() / 3U;
        writePod(out, dof_count);
        writePod(out, mode_count);
        writePod(out, node_count);
        out.write(reinterpret_cast<const char *>(dof_of_free_.data()),
                  static_cast<std::streamsize>(dof_of_free_.size() * sizeof(std::uint32_t)));
        out.write(reinterpret_cast<const char *>(dof_mass_.data()),
                  static_cast<std::streamsize>(dof_mass_.size() * sizeof(double)));
        out.write(reinterpret_cast<const char *>(omega2_.data()),
                  static_cast<std::streamsize>(omega2_.size() * sizeof(double)));
        out.write(reinterpret_cast<const char *>(phi_.data.data()),
                  static_cast<std::streamsize>(phi_.data.size() * sizeof(double)));
    }
    std::filesystem::rename(temporary, path, code);
    if (code) std::filesystem::remove(temporary, code);
}

ImpulseLibrary ImpulseLibrary::create(const ActiveMatter &matter,
                                      const std::vector<std::uint8_t> &dof_free,
                                      const LibraryOptions &options,
                                      const std::string &key,
                                      const std::filesystem::path &cache_dir) {
    ImpulseLibrary library;
    library.options_ = options;
    const auto total_start = Clock::now();
    library.buildTopology(matter, dof_free);

    std::ostringstream name;
    name << "algo1-" << std::hex << hash64(key) << ".bin";
    const std::filesystem::path path = cache_dir.empty() ? std::filesystem::path{} : cache_dir / name.str();
    bool loaded = false;
    if (!path.empty()) {
        const auto read_start = Clock::now();
        loaded = library.readCache(path);
        library.stats_.cache_read_s = since(read_start);
        if (!loaded) library.stats_.cache_read_s = 0.0;
    }
    library.stats_.cached = loaded;
    if (!loaded) {
        library.decompose(matter);
        if (!path.empty()) {
            const auto write_start = Clock::now();
            library.writeCache(path, key);
            library.stats_.cache_write_s = since(write_start);
        }
    }
    library.classifyModes();
    library.buildAmplitudes();
    library.buildCompliance(options);

    library.stats_.mechanism_modes = static_cast<std::size_t>(
        std::count(library.loose_dof_.begin(), library.loose_dof_.end(), std::uint8_t{1}));
    library.stats_.dofs = library.dofs();
    library.stats_.modes = library.modes();
    library.stats_.bonds = library.gradients_.size();
    library.stats_.nodes = matter.nodes.size();
    library.stats_.phi_bytes = library.phi_.data.size() * sizeof(double);
    std::error_code code;
    library.stats_.cache_bytes = path.empty() ? 0 : static_cast<std::size_t>(std::filesystem::file_size(path, code));
    if (code) library.stats_.cache_bytes = 0;
    library.stats_.cache_path = path.empty() ? std::string{} : path.string();
    library.stats_.total_s = since(total_start);
    return library;
}

} // namespace banjo::algo1
