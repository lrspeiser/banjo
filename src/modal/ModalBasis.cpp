#include "modal/ModalBasis.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <stdexcept>

namespace banjo::modal {
namespace {

double seconds(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

void requireMatter(const ActiveMatter &matter) {
    if (matter.asset == nullptr || matter.bonds.size() != matter.asset->bonds.size() ||
        matter.nodes.size() != matter.asset->nodes.size() ||
        matter.reference_positions_world_m.size() != matter.nodes.size())
        throw std::invalid_argument("modal basis needs an ActiveMatter with asset, bonds and reference positions");
}

} // namespace

ModalBasis::ModalBasis(const ActiveMatter &matter, std::vector<std::uint32_t> free_nodes,
                       const ModalBasisOptions &options, ModalBuildTimings *timings)
    : free_nodes_(std::move(free_nodes)), options_(options) {
    requireMatter(matter);
    if (free_nodes_.empty()) throw std::invalid_argument("modal basis needs at least one free node");
    free_index_.assign(matter.nodes.size(), kFixed);
    for (std::uint32_t f = 0; f < free_nodes_.size(); ++f) {
        const std::uint32_t node = free_nodes_[f];
        if (node >= matter.nodes.size() || free_index_[node] != kFixed)
            throw std::invalid_argument("free node list must name distinct lattice nodes");
        free_index_[node] = f;
        const double mass = matter.nodes[node].mass_kg;
        if (!std::isfinite(mass) || mass <= 0.0) throw std::invalid_argument("free nodes need positive mass");
        mass_.push_back(mass);
    }
    decompose(matter, timings);
    omega2_max_creation_ = 0.0;
    for (double value : omega2_) omega2_max_creation_ = std::max(omega2_max_creation_, value);
    rigid_threshold_ = options_.rigid_relative_threshold * omega2_max_creation_;
}

BondGradient ModalBasis::bondGradient(const ActiveMatter &matter, std::uint32_t bond) const {
    const BondRest &rest = matter.asset->bonds[bond];
    const Vec3 edge = matter.reference_positions_world_m[rest.node_b] -
                      matter.reference_positions_world_m[rest.node_a];
    const double rest_length = length(edge);
    if (!(rest_length > 0.0) || !(rest.compliance > 0.0))
        throw std::invalid_argument("bond gradient needs a positive rest length and compliance");
    const Vec3 direction = edge * (1.0 / rest_length);
    BondGradient gradient;
    gradient.stiffness_n_m = 1.0 / rest.compliance;
    const auto add = [&](std::uint32_t node, double sign) {
        const std::uint32_t f = free_index_[node];
        if (f == kFixed) return;
        const double components[3] = {direction.x, direction.y, direction.z};
        for (unsigned c = 0; c < 3; ++c) {
            gradient.dof[gradient.count] = 3U * f + c;
            gradient.value[gradient.count] = sign * components[c];
            ++gradient.count;
        }
    };
    add(rest.node_b, 1.0);
    add(rest.node_a, -1.0);
    return gradient;
}

DenseMatrix ModalBasis::assembleScaledStiffness(const ActiveMatter &matter) const {
    const std::size_t n = dofs();
    DenseMatrix a(n, n);
    std::vector<double> inverse_sqrt_mass(n);
    for (std::size_t f = 0; f < free_nodes_.size(); ++f)
        for (unsigned c = 0; c < 3; ++c) inverse_sqrt_mass[3 * f + c] = 1.0 / std::sqrt(mass_[f]);
    for (std::uint32_t bond = 0; bond < matter.bonds.size(); ++bond) {
        if (!matter.bonds[bond].alive) continue;
        const BondGradient g = bondGradient(matter, bond);
        if (g.count == 0) continue;
        for (unsigned i = 0; i < g.count; ++i)
            for (unsigned j = 0; j < g.count; ++j)
                a(g.dof[i], g.dof[j]) += g.stiffness_n_m * g.value[i] * g.value[j] *
                                         inverse_sqrt_mass[g.dof[i]] * inverse_sqrt_mass[g.dof[j]];
    }
    return a;
}

void ModalBasis::decompose(const ActiveMatter &matter, ModalBuildTimings *timings) {
    const auto start = std::chrono::steady_clock::now();
    const DenseMatrix a = assembleScaledStiffness(matter);
    const double assemble = seconds(start);
    const auto decomposition_start = std::chrono::steady_clock::now();
    SymmetricEigenDecomposition decomposition = decomposeSymmetric(a);
    const std::size_t n = dofs();
    std::size_t keep = n;
    if (options_.retained_fraction < 1.0)
        keep = std::max<std::size_t>(1, static_cast<std::size_t>(std::llround(options_.retained_fraction * static_cast<double>(n))));
    omega2_.assign(decomposition.values.begin(), decomposition.values.begin() + static_cast<std::ptrdiff_t>(keep));
    for (double &value : omega2_) value = std::max(value, 0.0);
    // phi = M^-1/2 psi, so phi^T M phi = I. Values ascend, so keeping the
    // first `keep` columns keeps the lowest frequencies.
    phi_ = DenseMatrix(n, keep);
    for (std::size_t f = 0; f < free_nodes_.size(); ++f) {
        const double scale = 1.0 / std::sqrt(mass_[f]);
        for (unsigned c = 0; c < 3; ++c) {
            const double *source = decomposition.vectors.row(3 * f + c);
            double *row = phi_.row(3 * f + c);
            for (std::size_t k = 0; k < keep; ++k) row[k] = source[k] * scale;
        }
    }
    if (timings) {
        timings->assemble_s += assemble;
        timings->decompose_s += seconds(decomposition_start);
    }
}

std::size_t ModalBasis::rigidModeCount() const {
    std::size_t count = 0;
    for (std::size_t k = 0; k < omega2_.size(); ++k) if (isRigidMode(k)) ++count;
    return count;
}

RankOneUpdateStats ModalBasis::removeBond(const ActiveMatter &matter, std::uint32_t bond,
                                          const std::vector<std::vector<double> *> &co_transform) {
    if (bond >= matter.bonds.size()) throw std::invalid_argument("bond index outside the lattice");
    const BondGradient g = bondGradient(matter, bond);
    RankOneUpdateStats stats;
    if (g.count == 0) { stats.deflated_small = modes(); return stats; }
    // z = phi^T g: only the rows the bond touches contribute.
    const std::size_t n = modes();
    std::vector<double> z(n, 0.0);
    for (unsigned i = 0; i < g.count; ++i) {
        const double *row = phi_.row(g.dof[i]);
        const double value = g.value[i];
        for (std::size_t k = 0; k < n; ++k) z[k] += value * row[k];
    }
    stats = updateRankOne(omega2_, phi_, -g.stiffness_n_m, z, co_transform);
    for (double &value : omega2_) value = std::max(value, 0.0);
    return stats;
}

void ModalBasis::rebuild(const ActiveMatter &matter, const std::vector<std::vector<double> *> &co_transform,
                         ModalBuildTimings *timings) {
    requireMatter(matter);
    // Carry every state through physical space: x = phi q, then q' = phi'^T M x.
    std::vector<std::vector<double>> physical(co_transform.size());
    for (std::size_t s = 0; s < co_transform.size(); ++s) displacement(*co_transform[s], physical[s]);
    decompose(matter, timings);
    for (std::size_t s = 0; s < co_transform.size(); ++s) project(physical[s], *co_transform[s]);
}

void ModalBasis::displacement(const std::vector<double> &q, std::vector<double> &u) const {
    const std::size_t n = dofs(), m = modes();
    if (q.size() != m) throw std::invalid_argument("modal amplitude vector has the wrong size");
    u.resize(n);
    const long long rows = static_cast<long long>(n);
#if defined(_OPENMP)
#pragma omp parallel for schedule(static) if (n > 256)
#endif
    for (long long r = 0; r < rows; ++r) {
        const double *row = phi_.row(static_cast<std::size_t>(r));
        double sum = 0.0;
        for (std::size_t k = 0; k < m; ++k) sum += row[k] * q[k];
        u[static_cast<std::size_t>(r)] = sum;
    }
}

void ModalBasis::project(const std::vector<double> &x, std::vector<double> &q) const {
    const std::size_t n = dofs();
    if (x.size() != n) throw std::invalid_argument("physical vector has the wrong size");
    std::vector<double> weighted(n);
    for (std::size_t f = 0; f < free_nodes_.size(); ++f)
        for (unsigned c = 0; c < 3; ++c) weighted[3 * f + c] = mass_[f] * x[3 * f + c];
    projectForce(weighted, q);
}

void ModalBasis::projectForce(const std::vector<double> &x, std::vector<double> &q) const {
    const std::size_t n = dofs();
    if (x.size() != n) throw std::invalid_argument("physical vector has the wrong size");
    const std::size_t m = modes();
    q.assign(m, 0.0);
    for (std::size_t r = 0; r < n; ++r) {
        const double value = x[r];
        if (value == 0.0) continue;
        const double *row = phi_.row(r);
        for (std::size_t k = 0; k < m; ++k) q[k] += value * row[k];
    }
}

Vec3 ModalBasis::nodeDisplacement(const std::vector<double> &q, std::uint32_t node_free) const {
    const std::size_t n = modes();
    double out[3] = {0.0, 0.0, 0.0};
    for (unsigned c = 0; c < 3; ++c) {
        const double *row = phi_.row(3 * node_free + c);
        double sum = 0.0;
        for (std::size_t k = 0; k < n; ++k) sum += row[k] * q[k];
        out[c] = sum;
    }
    return {out[0], out[1], out[2]};
}

void ModalBasis::addNodeImpulse(std::vector<double> &qdot, std::uint32_t node_free, const Vec3 &impulse) const {
    const std::size_t n = modes();
    const double components[3] = {impulse.x, impulse.y, impulse.z};
    for (unsigned c = 0; c < 3; ++c) {
        const double value = components[c];
        if (value == 0.0) continue;
        const double *row = phi_.row(3 * node_free + c);
        for (std::size_t k = 0; k < n; ++k) qdot[k] += value * row[k];
    }
}

double ModalBasis::residualAgainst(const ActiveMatter &matter) const {
    const DenseMatrix a = assembleScaledStiffness(matter);
    // Scale phi back to psi = M^1/2 phi for the mass-scaled residual.
    SymmetricEigenDecomposition decomposition;
    decomposition.values = omega2_;
    decomposition.vectors = phi_;
    for (std::size_t f = 0; f < free_nodes_.size(); ++f) {
        const double scale = std::sqrt(mass_[f]);
        for (unsigned c = 0; c < 3; ++c) {
            double *row = decomposition.vectors.row(3 * f + c);
            for (std::size_t k = 0; k < modes(); ++k) row[k] *= scale;
        }
    }
    // For a truncated basis this is the residual of the retained columns only.
    const std::size_t n = dofs();
    double scale = 1.0;
    for (double value : decomposition.values) scale = std::max(scale, std::abs(value));
    double worst = 0.0;
    std::vector<double> column(n);
    for (std::size_t k = 0; k < modes(); ++k) {
        for (std::size_t r = 0; r < n; ++r) column[r] = decomposition.vectors(r, k);
        for (std::size_t r = 0; r < n; ++r) {
            double sum = 0.0;
            for (std::size_t c = 0; c < n; ++c) sum += a(r, c) * column[c];
            worst = std::max(worst, std::abs(sum - decomposition.values[k] * column[r]));
        }
    }
    return worst / scale;
}

double ModalBasis::orthogonalityDefect() const {
    DenseMatrix psi = phi_;
    for (std::size_t f = 0; f < free_nodes_.size(); ++f) {
        const double scale = std::sqrt(mass_[f]);
        for (unsigned c = 0; c < 3; ++c) {
            double *row = psi.row(3 * f + c);
            for (std::size_t k = 0; k < modes(); ++k) row[k] *= scale;
        }
    }
    return modal::orthogonalityDefect(psi);
}

} // namespace banjo::modal
