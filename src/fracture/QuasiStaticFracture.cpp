#include "fracture/QuasiStaticFracture.hpp"

#include "fracture/ConnectedComponents.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace banjo {
namespace {

constexpr double kInfinity = std::numeric_limits<double>::infinity();

Mat3 identity() {
    Mat3 m;
    for (unsigned i = 0; i < 3; ++i) m.m[i][i] = 1.0;
    return m;
}

void addOuter(Mat3 &m, const Vec3 &a, const Vec3 &b, double scale) {
    const double u[3]{a.x, a.y, a.z}, v[3]{b.x, b.y, b.z};
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j) m.m[i][j] += scale * u[i] * v[j];
}

Mat3 multiply(const Mat3 &a, const Mat3 &b) {
    Mat3 r;
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j)
            for (unsigned k = 0; k < 3; ++k) r.m[i][j] += a.m[i][k] * b.m[k][j];
    return r;
}

// Eigen-decomposition of a small symmetric matrix (n <= 6) by cyclic Jacobi
// rotations. On return a holds the eigenvalues on its diagonal and the columns
// of v are the eigenvectors.
template <unsigned N>
void symmetricEigen(double (&a)[N][N], double (&v)[N][N]) {
    for (unsigned i = 0; i < N; ++i)
        for (unsigned j = 0; j < N; ++j) v[i][j] = i == j ? 1.0 : 0.0;
    for (unsigned sweep = 0; sweep < 100; ++sweep) {
        double off = 0, diag = 1.0;
        for (unsigned p = 0; p < N; ++p) {
            diag += a[p][p] * a[p][p];
            for (unsigned q = p + 1; q < N; ++q) off += a[p][q] * a[p][q];
        }
        if (off < 1.0e-32 * diag) break;
        for (unsigned p = 0; p < N; ++p) {
            for (unsigned q = p + 1; q < N; ++q) {
                if (std::abs(a[p][q]) < 1.0e-300) continue;
                const double theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q]);
                const double t = (theta >= 0 ? 1.0 : -1.0) / (std::abs(theta) + std::sqrt(theta * theta + 1.0));
                const double c = 1.0 / std::sqrt(t * t + 1.0), s = t * c;
                for (unsigned k = 0; k < N; ++k) {
                    const double akp = a[k][p], akq = a[k][q];
                    a[k][p] = c * akp - s * akq;
                    a[k][q] = s * akp + c * akq;
                }
                for (unsigned k = 0; k < N; ++k) {
                    const double apk = a[p][k], aqk = a[q][k];
                    a[p][k] = c * apk - s * aqk;
                    a[q][k] = s * apk + c * aqk;
                }
                for (unsigned k = 0; k < N; ++k) {
                    const double vkp = v[k][p], vkq = v[k][q];
                    v[k][p] = c * vkp - s * vkq;
                    v[k][q] = s * vkp + c * vkq;
                }
            }
        }
    }
}

// Per-node constraint bookkeeping for one solve.
struct NodeSpace {
    unsigned raw_count{};
    std::array<Vec3, 9> raw_direction{};
    std::array<double, 9> raw_value{};
    std::array<std::uint32_t, 9> raw_constraint{}; // index into the input, or kMechanismPin
    std::array<bool, 9> raw_dependent{};
    std::array<bool, 9> raw_anchors{};
    unsigned q_count{};
    std::array<Vec3, 3> q{};
    Vec3 prescribed{};
    Mat3 projector{};
    Mat3 precondition{};
};

constexpr std::uint32_t kMechanismPin = std::numeric_limits<std::uint32_t>::max();

// Orthonormalise the raw directions, mark dependent ones, and solve the
// prescribed displacement in the constrained subspace.
void buildConstrainedSubspace(NodeSpace &space) {
    space.q_count = 0;
    for (unsigned k = 0; k < space.raw_count; ++k) {
        Vec3 v = space.raw_direction[k];
        for (unsigned pass = 0; pass < 2; ++pass)
            for (unsigned j = 0; j < space.q_count; ++j) v -= dot(v, space.q[j]) * space.q[j];
        const double norm = length(v);
        space.raw_dependent[k] = norm < 1.0e-9 || space.q_count >= 3;
        if (!space.raw_dependent[k]) space.q[space.q_count++] = v / norm;
    }
    // C = Q^T N over the independent raw constraints (square, invertible);
    // C^T alpha = b gives u_g = Q alpha.
    Mat3 c = identity();
    double b[3]{};
    unsigned m = 0;
    for (unsigned k = 0; k < space.raw_count && m < 3; ++k) {
        if (space.raw_dependent[k]) continue;
        for (unsigned j = 0; j < 3; ++j) c.m[j][m] = j < space.q_count ? dot(space.q[j], space.raw_direction[k]) : (j == m ? 1.0 : 0.0);
        b[m] = space.raw_value[k];
        ++m;
    }
    Mat3 ct;
    for (unsigned i = 0; i < 3; ++i)
        for (unsigned j = 0; j < 3; ++j) ct.m[i][j] = c.m[j][i];
    const auto inverse = ct.inverse(1.0e-30);
    const Vec3 alpha = inverse ? (*inverse) * Vec3{b[0], b[1], b[2]} : Vec3{};
    const double a[3]{alpha.x, alpha.y, alpha.z};
    space.prescribed = {};
    for (unsigned j = 0; j < space.q_count; ++j) space.prescribed += a[j] * space.q[j];
    space.projector = identity();
    for (unsigned j = 0; j < space.q_count; ++j) addOuter(space.projector, space.q[j], space.q[j], -1.0);
}

struct DeflationMode {
    std::vector<std::uint32_t> nodes;
    std::vector<Vec3> values; // unit in the n-vector norm, nonzero only on nodes
};

} // namespace

StaticLatticeSolver::StaticLatticeSolver(const ActiveMatter &matter) : matter_(&matter) {
    if (matter.asset == nullptr || matter.bonds.size() != matter.asset->bonds.size() ||
        matter.reference_positions_world_m.size() != matter.nodes.size())
        throw std::invalid_argument("static solver needs a lattice with reference positions");
    rebuild();
}

void StaticLatticeSolver::rebuild() {
    const ActiveMatter &matter = *matter_;
    edges_.clear();
    edges_.reserve(matter.bonds.size());
    diagonal_.assign(matter.nodes.size(), Mat3{});
    reference_stiffness_ = 0;
    for (std::uint32_t i = 0; i < matter.bonds.size(); ++i) {
        if (!matter.bonds[i].alive) continue;
        const BondRest &bond = matter.asset->bonds[i];
        if (!(bond.compliance > 0.0)) throw std::invalid_argument("static solver needs positive bond compliance");
        const Vec3 rest = matter.reference_positions_world_m[bond.node_b] - matter.reference_positions_world_m[bond.node_a];
        const double rest_length = length(rest);
        if (rest_length <= 1.0e-12) throw std::invalid_argument("static solver needs finite bond lengths");
        Edge edge{bond.node_a, bond.node_b, i, rest / rest_length, 1.0 / bond.compliance};
        addOuter(diagonal_[edge.a], edge.direction, edge.direction, edge.stiffness);
        addOuter(diagonal_[edge.b], edge.direction, edge.direction, edge.stiffness);
        reference_stiffness_ = std::max(reference_stiffness_, edge.stiffness);
        edges_.push_back(edge);
    }
}

void StaticLatticeSolver::applyStiffness(const std::vector<Vec3> &u, std::vector<Vec3> &out) const {
    out.assign(u.size(), Vec3{});
    for (const Edge &e : edges_) {
        const double t = e.stiffness * dot(e.direction, u[e.a] - u[e.b]);
        out[e.a] += t * e.direction;
        out[e.b] -= t * e.direction;
    }
}

std::vector<unsigned> StaticLatticeSolver::nodeStiffnessRanks(double stiffness_ratio) const {
    std::vector<unsigned> ranks(diagonal_.size(), 0);
    const double floor = stiffness_ratio * reference_stiffness_;
    for (std::size_t i = 0; i < diagonal_.size(); ++i) {
        double a[3][3], v[3][3];
        for (unsigned r = 0; r < 3; ++r)
            for (unsigned c = 0; c < 3; ++c) a[r][c] = diagonal_[i].m[r][c];
        symmetricEigen<3>(a, v);
        for (unsigned j = 0; j < 3; ++j) ranks[i] += a[j][j] > floor ? 1U : 0U;
    }
    return ranks;
}

double StaticLatticeSolver::elasticEnergy(const std::vector<Vec3> &u) const {
    double energy = 0;
    for (const Edge &e : edges_) {
        const double extension = dot(e.direction, u[e.b] - u[e.a]);
        energy += 0.5 * e.stiffness * extension * extension;
    }
    return energy;
}

double StaticLatticeSolver::bondElasticEnergy(std::uint32_t bond_index, const std::vector<Vec3> &u) const {
    const BondRest &bond = matter_->asset->bonds[bond_index];
    const Vec3 rest = matter_->reference_positions_world_m[bond.node_b] - matter_->reference_positions_world_m[bond.node_a];
    const double rest_length = length(rest);
    if (rest_length <= 1.0e-12 || !(bond.compliance > 0.0)) return 0.0;
    const double extension = dot(rest / rest_length, u[bond.node_b] - u[bond.node_a]);
    return 0.5 * extension * extension / bond.compliance;
}

StaticSolveResult StaticLatticeSolver::solve(const std::vector<Vec3> &loads, const std::vector<StaticConstraint> &constraints,
    std::vector<Vec3> &displacement, const StaticSolveSettings &settings, const std::vector<std::uint32_t> *component_of_node) const {
    const std::size_t count = matter_->nodes.size();
    if (loads.size() != count || displacement.size() != count)
        throw std::invalid_argument("static solve needs one load and one displacement per node");
    if (!(settings.relative_tolerance > 0.0) || settings.maximum_iterations == 0)
        throw std::invalid_argument("static solve needs a positive tolerance and iteration budget");
    if (component_of_node && component_of_node->size() != count)
        throw std::invalid_argument("component map needs one entry per node");
    StaticSolveResult result;
    result.reactions_n.assign(constraints.size(), 0.0);

    std::vector<NodeSpace> spaces(count);
    for (std::uint32_t k = 0; k < constraints.size(); ++k) {
        const StaticConstraint &c = constraints[k];
        if (c.node >= count || std::abs(lengthSquared(c.direction) - 1.0) > 1.0e-8 || !std::isfinite(c.value))
            throw std::invalid_argument("static constraint needs a valid node, unit direction and finite value");
        NodeSpace &space = spaces[c.node];
        if (space.raw_count >= 6) throw std::invalid_argument("a node carries at most six constraints");
        space.raw_direction[space.raw_count] = c.direction;
        space.raw_value[space.raw_count] = c.value;
        space.raw_constraint[space.raw_count] = k;
        space.raw_anchors[space.raw_count] = c.anchors_rigid_modes;
        ++space.raw_count;
    }
    const double pin_floor = settings.mechanism_stiffness_ratio * reference_stiffness_;
    for (std::size_t i = 0; i < count; ++i) {
        NodeSpace &space = spaces[i];
        for (unsigned pass = 0; pass < 4; ++pass) {
            buildConstrainedSubspace(space);
            if (space.q_count >= 3) break;
            // Stiffness seen by the free directions; constrained directions are
            // given the reference stiffness so they never register as mechanisms.
            Mat3 free_stiffness = multiply(space.projector, multiply(diagonal_[i], space.projector));
            for (unsigned r = 0; r < 3; ++r)
                for (unsigned c = 0; c < 3; ++c)
                    free_stiffness.m[r][c] += reference_stiffness_ * ((r == c ? 1.0 : 0.0) - space.projector.m[r][c]);
            double a[3][3], v[3][3];
            for (unsigned r = 0; r < 3; ++r)
                for (unsigned c = 0; c < 3; ++c) a[r][c] = free_stiffness.m[r][c];
            symmetricEigen<3>(a, v);
            bool pinned = false;
            for (unsigned j = 0; j < 3 && space.raw_count < 9; ++j) {
                if (a[j][j] > pin_floor) continue;
                const Vec3 direction = normalized({v[0][j], v[1][j], v[2][j]});
                space.raw_direction[space.raw_count] = direction;
                space.raw_value[space.raw_count] = settings.pin_mechanisms_at_zero ? 0.0 : dot(direction, displacement[i]);
                space.raw_constraint[space.raw_count] = kMechanismPin;
                space.raw_anchors[space.raw_count] = true;
                ++space.raw_count;
                ++result.pinned_mechanism_directions;
                pinned = true;
            }
            if (!pinned) break;
        }
        Mat3 preconditioned = multiply(space.projector, multiply(diagonal_[i], space.projector));
        for (unsigned r = 0; r < 3; ++r)
            for (unsigned c = 0; c < 3; ++c)
                preconditioned.m[r][c] += reference_stiffness_ * ((r == c ? 1.0 : 0.0) - space.projector.m[r][c]);
        const auto inverse = preconditioned.inverse(0.0);
        space.precondition = inverse ? multiply(space.projector, multiply(*inverse, space.projector)) : space.projector;
    }

    // Rigid modes each component can still perform under its constraints are
    // the null space of P K P. They are deflated: the load they would carry is
    // removed from the right-hand side and reported, and the iteration stays
    // in their complement.
    std::vector<DeflationMode> modes;
    std::vector<double> mode_removed;
    if (component_of_node) {
        std::uint32_t component_count = 0;
        for (const std::uint32_t c : *component_of_node) component_count = std::max(component_count, c + 1);
        std::vector<std::vector<std::uint32_t>> members(component_count);
        for (std::uint32_t i = 0; i < count; ++i) members[(*component_of_node)[i]].push_back(i);
        const auto &reference = matter_->reference_positions_world_m;
        for (const auto &nodes : members) {
            if (nodes.empty()) continue;
            Vec3 centroid{};
            for (const std::uint32_t i : nodes) centroid += reference[i];
            centroid = centroid / static_cast<double>(nodes.size());
            const auto rigid = [&](unsigned k, std::uint32_t i) -> Vec3 {
                const Vec3 d = reference[i] - centroid;
                switch (k) {
                case 0: return {1, 0, 0};
                case 1: return {0, 1, 0};
                case 2: return {0, 0, 1};
                case 3: return cross(Vec3{1, 0, 0}, d);
                case 4: return cross(Vec3{0, 1, 0}, d);
                default: return cross(Vec3{0, 0, 1}, d);
                }
            };
            // Gram matrix of the anchoring constraint rows (support, frozen
            // axes, mechanism pins) in the rigid basis. A contact that does not
            // anchor, the ball, is left out on purpose: a rigid mode the frame
            // would hold by friction must be pinned even when the ball's tilted
            // normal happens to touch it, otherwise the lattice slides instead
            // of deforming. The mode is then projected into the subspace all
            // constraints allow, so the deflated iteration stays exact.
            double g[6][6]{}, v[6][6]{};
            bool any_constraint = false;
            for (const std::uint32_t i : nodes) {
                const NodeSpace &space = spaces[i];
                for (unsigned k = 0; k < space.raw_count; ++k) {
                    if (!space.raw_anchors[k]) continue;
                    any_constraint = true;
                    double row[6];
                    for (unsigned m = 0; m < 6; ++m) row[m] = dot(space.raw_direction[k], rigid(m, i));
                    for (unsigned r = 0; r < 6; ++r)
                        for (unsigned c = 0; c < 6; ++c) g[r][c] += row[r] * row[c];
                }
            }
            double scale = 0;
            for (unsigned k = 0; k < 6; ++k) scale = std::max(scale, std::abs(g[k][k]));
            if (any_constraint) symmetricEigen<6>(g, v);
            for (unsigned j = 0; j < 6; ++j) {
                const bool compatible = !any_constraint || g[j][j] <= 1.0e-10 * std::max(scale, 1.0e-300);
                if (!compatible) continue;
                DeflationMode mode;
                mode.nodes = nodes;
                mode.values.resize(nodes.size());
                for (std::size_t n = 0; n < nodes.size(); ++n) {
                    Vec3 value{};
                    for (unsigned k = 0; k < 6; ++k) value += (any_constraint ? v[k][j] : (k == j ? 1.0 : 0.0)) * rigid(k, nodes[n]);
                    mode.values[n] = spaces[nodes[n]].projector * value;
                }
                // Orthonormalise against this component's accepted modes.
                for (unsigned pass = 0; pass < 2; ++pass)
                    for (const DeflationMode &other : modes) {
                        if (other.nodes.front() != nodes.front()) continue;
                        double projection = 0;
                        for (std::size_t n = 0; n < nodes.size(); ++n) projection += dot(other.values[n], mode.values[n]);
                        for (std::size_t n = 0; n < nodes.size(); ++n) mode.values[n] -= projection * other.values[n];
                    }
                double norm = 0;
                for (const Vec3 &value : mode.values) norm += lengthSquared(value);
                norm = std::sqrt(norm);
                if (norm < 1.0e-12) continue;
                for (Vec3 &value : mode.values) value = value / norm;
                modes.push_back(std::move(mode));
            }
        }
        mode_removed.assign(modes.size(), 0.0);
        result.deflated_modes = modes.size();
    }
    const auto deflate = [&](std::vector<Vec3> &vector, bool record) {
        for (std::size_t m = 0; m < modes.size(); ++m) {
            const DeflationMode &mode = modes[m];
            double projection = 0;
            for (std::size_t n = 0; n < mode.nodes.size(); ++n) projection += dot(mode.values[n], vector[mode.nodes[n]]);
            for (std::size_t n = 0; n < mode.nodes.size(); ++n) vector[mode.nodes[n]] -= projection * mode.values[n];
            if (record && m < mode_removed.size()) mode_removed[m] = projection;
        }
    };
    std::vector<Vec3> mechanism_removed(count);

    // Solve P K P w = P (f - K u_g) on the constrained subspace.
    std::vector<Vec3> prescribed(count), w(count), rhs(count), r(count), z(count), p(count), q(count);
    for (std::size_t i = 0; i < count; ++i) {
        prescribed[i] = spaces[i].prescribed;
        w[i] = spaces[i].projector * (displacement[i] - prescribed[i]);
    }
    applyStiffness(prescribed, rhs);
    for (std::size_t i = 0; i < count; ++i) rhs[i] = spaces[i].projector * (loads[i] - rhs[i]);
    std::vector<Vec3> removed = rhs;
    deflate(rhs, true);
    deflate(w, false);
    for (std::size_t i = 0; i < count; ++i) removed[i] -= rhs[i];
    const std::size_t rigid_modes = modes.size();
    if (!modes.empty()) {
        // The load the pins carry, per component: net force and torque.
        std::vector<Vec3> force, torque, centroid;
        std::vector<double> members;
        std::uint32_t component_count = 0;
        for (const std::uint32_t c : *component_of_node) component_count = std::max(component_count, c + 1);
        force.assign(component_count, {}); torque.assign(component_count, {}); centroid.assign(component_count, {}); members.assign(component_count, 0.0);
        for (std::uint32_t i = 0; i < count; ++i) { centroid[(*component_of_node)[i]] += matter_->reference_positions_world_m[i]; members[(*component_of_node)[i]] += 1.0; }
        for (std::uint32_t c = 0; c < component_count; ++c) if (members[c] > 0) centroid[c] = centroid[c] / members[c];
        for (std::uint32_t i = 0; i < count; ++i) {
            const std::uint32_t c = (*component_of_node)[i];
            force[c] += removed[i];
            torque[c] += cross(matter_->reference_positions_world_m[i] - centroid[c], removed[i]);
        }
        for (std::uint32_t c = 0; c < component_count; ++c) {
            result.pinned_rigid_force_n = std::max(result.pinned_rigid_force_n, length(force[c]));
            result.pinned_rigid_torque_n_m = std::max(result.pinned_rigid_torque_n_m, length(torque[c]));
        }
    }
    double rhs_norm = 0;
    for (const Vec3 &value : rhs) rhs_norm += lengthSquared(value);
    rhs_norm = std::sqrt(rhs_norm);
    const auto apply = [&](const std::vector<Vec3> &v, std::vector<Vec3> &out) {
        applyStiffness(v, out);
        for (std::size_t i = 0; i < count; ++i) out[i] = spaces[i].projector * out[i];
        deflate(out, false);
    };
    apply(w, q);
    double residual = 0;
    for (std::size_t i = 0; i < count; ++i) {
        r[i] = rhs[i] - q[i];
        residual += lengthSquared(r[i]);
    }
    residual = std::sqrt(residual);
    const double target = settings.relative_tolerance * std::max(rhs_norm, 1.0e-300);
    unsigned iterations = 0;
    bool converged = residual <= target || rhs_norm == 0.0;
    if (rhs_norm == 0.0) { for (Vec3 &value : w) value = {}; residual = 0; }
    if (!converged) {
        for (std::size_t i = 0; i < count; ++i) z[i] = spaces[i].precondition * r[i];
        deflate(z, false);
        p = z;
        double rz = 0;
        for (std::size_t i = 0; i < count; ++i) rz += dot(r[i], z[i]);
        unsigned restarts = 0;
        while (iterations < settings.maximum_iterations) {
            ++iterations;
            apply(p, q);
            double pq = 0, pp = 0;
            for (std::size_t i = 0; i < count; ++i) { pq += dot(p[i], q[i]); pp += lengthSquared(p[i]); }
            if (!std::isfinite(pq)) { result.failure = "non-finite curvature"; break; }
            if (pq <= settings.mechanism_stiffness_ratio * 1.0e-4 * reference_stiffness_ * pp) {
                // A search direction with no stiffness behind it is a mechanism
                // the per-node check could not see (a flap on a hinge). Statics
                // has no answer for it: pin it, charge the load it carried to the
                // pins, and continue in its complement.
                if (++restarts > 64 || pp <= 0) { result.failure = "operator not positive definite"; break; }
                DeflationMode mode;
                mode.nodes.resize(count);
                mode.values.resize(count);
                const double norm = std::sqrt(pp);
                for (std::uint32_t i = 0; i < count; ++i) { mode.nodes[i] = i; mode.values[i] = p[i] / norm; }
                modes.push_back(std::move(mode));
                ++result.deflated_mechanism_modes;
                std::vector<Vec3> before = rhs;
                deflate(rhs, false);
                deflate(w, false);
                for (std::size_t i = 0; i < count; ++i) mechanism_removed[i] += before[i] - rhs[i];
                apply(w, q);
                residual = 0;
                for (std::size_t i = 0; i < count; ++i) { r[i] = rhs[i] - q[i]; residual += lengthSquared(r[i]); }
                residual = std::sqrt(residual);
                if (residual <= target) { converged = true; break; }
                for (std::size_t i = 0; i < count; ++i) z[i] = spaces[i].precondition * r[i];
                deflate(z, false);
                p = z;
                rz = 0;
                for (std::size_t i = 0; i < count; ++i) rz += dot(r[i], z[i]);
                continue;
            }
            const double alpha = rz / pq;
            residual = 0;
            for (std::size_t i = 0; i < count; ++i) {
                w[i] += alpha * p[i];
                r[i] -= alpha * q[i];
                residual += lengthSquared(r[i]);
            }
            residual = std::sqrt(residual);
            if (!std::isfinite(residual)) { result.failure = "non-finite residual"; break; }
            if (residual <= target) { converged = true; break; }
            double rz_next = 0;
            for (std::size_t i = 0; i < count; ++i) z[i] = spaces[i].precondition * r[i];
            deflate(z, false);
            for (std::size_t i = 0; i < count; ++i) rz_next += dot(r[i], z[i]);
            const double beta = rz_next / rz;
            rz = rz_next;
            for (std::size_t i = 0; i < count; ++i) p[i] = z[i] + beta * p[i];
        }
    }
    result.iterations = iterations;
    result.relative_residual = rhs_norm > 0 ? residual / rhs_norm : 0.0;
    result.converged = converged;
    for (const Vec3 &value : mechanism_removed) result.pinned_mechanism_force_n += length(value);
    (void)rigid_modes;
    if (!converged) {
        if (result.failure == nullptr) result.failure = "iteration budget";
        for (const NodeSpace &space : spaces) {
            result.maximum_prescribed_m = std::max(result.maximum_prescribed_m, length(space.prescribed));
            for (unsigned k = 0; k < space.raw_count; ++k) result.dependent_constraints += space.raw_dependent[k] ? 1U : 0U;
        }
        return result;
    }

    for (std::size_t i = 0; i < count; ++i) displacement[i] = prescribed[i] + w[i];
    // Reactions: R = K u - f in the constrained subspace, resolved onto the
    // raw constraint directions through C = Q^T N (lambda = C^-1 Q^T R).
    std::vector<Vec3> force;
    applyStiffness(displacement, force);
    for (std::size_t i = 0; i < count; ++i) {
        const NodeSpace &space = spaces[i];
        if (space.raw_count == 0) continue;
        const Vec3 reaction = force[i] - loads[i];
        double rho[3]{};
        for (unsigned j = 0; j < space.q_count; ++j) rho[j] = dot(space.q[j], reaction);
        Mat3 c = identity();
        std::array<unsigned, 3> raw_of_column{};
        unsigned m = 0;
        for (unsigned k = 0; k < space.raw_count && m < 3; ++k) {
            if (space.raw_dependent[k]) continue;
            for (unsigned j = 0; j < 3; ++j) c.m[j][m] = j < space.q_count ? dot(space.q[j], space.raw_direction[k]) : (j == m ? 1.0 : 0.0);
            raw_of_column[m] = k;
            ++m;
        }
        const auto inverse = c.inverse(1.0e-30);
        const Vec3 lambda = inverse ? (*inverse) * Vec3{rho[0], rho[1], rho[2]} : Vec3{};
        const double l[3]{lambda.x, lambda.y, lambda.z};
        for (unsigned j = 0; j < m; ++j) {
            const unsigned k = raw_of_column[j];
            if (space.raw_constraint[k] == kMechanismPin) result.pinned_mechanism_force_n += std::abs(l[j]);
            else result.reactions_n[space.raw_constraint[k]] = l[j];
        }
    }
    return result;
}

const char *quasiStaticStopName(QuasiStaticStop stop) {
    switch (stop) {
    case QuasiStaticStop::None: return "none";
    case QuasiStaticStop::BallStopped: return "ball_stopped";
    case QuasiStaticStop::BallThrough: return "ball_through";
    case QuasiStaticStop::TravelLimit: return "travel_limit";
    case QuasiStaticStop::EventBudget: return "event_budget";
    case QuasiStaticStop::RoundBudget: return "round_budget";
    case QuasiStaticStop::SolverFailed: return "solver_failed";
    case QuasiStaticStop::ActiveSetFailed: return "active_set_failed";
    }
    return "unknown";
}

namespace {

using Clock = std::chrono::steady_clock;
double secondsSince(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

class ImpactRunner {
public:
    ImpactRunner(ActiveMatter &matter, const QuasiStaticImpactScene &scene, const QuasiStaticImpactSettings &settings)
        : matter_(matter), scene_(scene), settings_(settings), count_(matter.nodes.size()), solver_(matter) {
        if (count_ == 0 || matter.reference_positions_world_m.size() != count_)
            throw std::invalid_argument("quasi-static impact needs nodes with reference positions");
        if (!(scene.ball_radius_m > 0.0) || !(scene.ball_mass_kg > 0.0) || !(scene.ball_speed_m_s >= 0.0) ||
            !(scene.maximum_travel_m > 0.0) || std::abs(lengthSquared(scene.ball_direction) - 1.0) > 1.0e-8)
            throw std::invalid_argument("quasi-static impact needs a ball with radius, mass, speed, unit direction and travel limit");
        if (std::abs(lengthSquared(scene.support.normal_world) - 1.0) > 1.0e-8)
            throw std::invalid_argument("quasi-static impact needs a unit support normal");
        for (const std::uint32_t node : scene.support_nodes)
            if (node >= count_) throw std::invalid_argument("support node outside the lattice");
        for (const auto &node : matter.nodes)
            if (!(node.mass_kg > 0.0) || !std::isfinite(node.mass_kg)) throw std::invalid_argument("quasi-static impact needs positive node masses");
        reference_.assign(count_, {});
        displacement_.assign(count_, {});
        loads_.assign(count_, {});
        for (std::size_t i = 0; i < count_; ++i) {
            reference_[i] = matter.reference_positions_world_m[i];
            displacement_[i] = matter.nodes[i].position_world_m - reference_[i];
            loads_[i] = matter.nodes[i].mass_kg * scene.gravity_m_s2;
        }
        support_eligible_.assign(count_, 0);
        for (const std::uint32_t node : scene.support_nodes) support_eligible_[node] = 1;
        support_active_.assign(count_, 0);
        ball_active_.assign(count_, 0);
        support_released_at_.assign(count_, -1.0);
        ball_released_at_.assign(count_, -1.0);
        support_locked_.assign(count_, 0);
        ball_locked_.assign(count_, 0);
        frozen_.assign(count_, 0);
        rate_.assign(count_, {});
        loose_ = looseNodes();
        cell_size_ = matter.asset->recipe.voxel_size_m > 0 ? matter.asset->recipe.voxel_size_m : 1.0;
        result_.kinetic_energy_in_j = 0.5 * scene.ball_mass_kg * scene.ball_speed_m_s * scene.ball_speed_m_s;
        // Contacts that touch at the start are active: the rim resting on its
        // frame and the node the ball has just reached. A contact that turns
        // out to pull is released by the first active-set pass.
        const double touch_tolerance = 1.0e-9 * cell_size_;
        for (std::uint32_t i = 0; i < count_; ++i) {
            const Vec3 position = reference_[i] + displacement_[i];
            if (support_eligible_[i] && signedDistanceToPlane(scene.support, position) <= touch_tolerance) support_active_[i] = 1;
            if (!loose_[i] && length(position - scene.ball_center_m) <= scene.ball_radius_m + touch_tolerance) ball_active_[i] = 1;
        }
        refreshComponents(true);
    }

    // A node whose live bonds no longer span three directions has no static
    // answer to a push: the ball cannot rest on it, so it is never a contact.
    std::vector<char> looseNodes() const {
        const auto ranks = solver_.nodeStiffnessRanks(settings_.solver.mechanism_stiffness_ratio);
        std::vector<char> loose(count_, 0);
        for (std::size_t i = 0; i < count_; ++i) loose[i] = ranks[i] < 3 ? 1 : 0;
        return loose;
    }

    QuasiStaticImpactResult run() {
        // Equilibrium under gravity alone defines the starting potential.
        if (!solveCurrent()) return finish();
        result_.potential_start_j = potential();
        ledger_potential_ = result_.potential_start_j;
        unsigned nudges = 0, zero_steps_at_travel = 0;
        QuasiStaticImpactEvent event{};
        while (true) {
            const auto criterion_start = Clock::now();
            const double ratio = failureRatio(displacement_);
            result_.criterion_wall_s += secondsSince(criterion_start);
            if (ratio >= 1.0) {
                if (result_.rounds >= settings_.maximum_rounds) { result_.stop = QuasiStaticStop::RoundBudget; return finish(); }
                std::vector<std::uint32_t> removed;
                setPositions(displacement_);
                resetBondStrainPeaks(matter_);
                accumulateBondStrainPeaks(matter_);
                const BondFailureSummary summary = applyBondFailure(matter_, &removed);
                if (summary.newly_broken == 0) {
                    // The ratio said failure but the shared criterion did not act:
                    // that is a rounding edge, so nudge along the current rate.
                    if (++nudges > 16) { result_.stop = QuasiStaticStop::SolverFailed; return finish(); }
                    for (std::size_t i = 0; i < count_; ++i) displacement_[i] += 1.0e-12 * cell_size_ * rate_[i];
                    continue;
                }
                double removed_linear = 0;
                for (const std::uint32_t bond : removed) removed_linear += solver_.bondElasticEnergy(bond, displacement_);
                result_.removed_bond_energy_j += summary.removed_elastic_energy_j;
                result_.removed_bond_energy_linear_j += removed_linear;
                if (result_.first_failure_bonds.empty()) {
                    result_.first_failure_bonds = removed;
                    result_.first_failure_travel_m = travel_;
                    result_.first_failure_force_n = contact_force_;
                }
                ++result_.rounds;
                ++event.rounds;
                event.bonds_removed += summary.newly_broken;
                if (settings_.trace)
                    std::fprintf(stderr, "  round %u at travel %.3e m: %zu bonds removed (ratio %.6f, force %.3f N, removed %.3e J)\n",
                        result_.rounds, travel_, removed.size(), ratio, contact_force_, removed_linear);
                const auto topology_start = Clock::now();
                solver_.rebuild();
                loose_ = looseNodes();
                for (std::uint32_t i = 0; i < count_; ++i) if (loose_[i] && ball_active_[i]) { ball_active_[i] = 0; ball_released_at_[i] = travel_; }
                ledger_potential_ -= removed_linear;
                refreshComponents(true);
                result_.topology_wall_s += secondsSince(topology_start);
                if (!solveCurrent()) return finish();
                // Re-equilibration at fixed travel can only lower the potential;
                // what it sheds is energy the dynamic lane would carry as motion.
                result_.relaxation_energy_j += ledger_potential_ - potential();
                ledger_potential_ = potential();
                continue;
            }

            // No failure at this travel: the next event along the ball's path.
            if (result_.events >= settings_.maximum_events) { result_.stop = QuasiStaticStop::EventBudget; return finish(); }
            if (!solveRate()) return finish();
            const double force_rate = ballForceRate();
            enum class Kind { BondFailure, Release, Activation, Energy, Travel } kind = Kind::Travel;
            std::uint32_t event_node = 0;
            bool event_on_ball = false;
            const double remaining_travel = scene_.maximum_travel_m - travel_;
            if (remaining_travel <= 0) { result_.stop = QuasiStaticStop::TravelLimit; return finish(); }
            double step = remaining_travel;

            // Energy: work = W0 + F0 s + F' s^2 / 2 reaches the kinetic energy.
            {
                const double budget = result_.kinetic_energy_in_j - work_;
                if (budget <= 0) { result_.stop = QuasiStaticStop::BallStopped; return finish(); }
                double s = kInfinity;
                if (std::abs(force_rate) < 1.0e-12 * std::max(1.0, contact_force_)) {
                    if (contact_force_ > 0) s = budget / contact_force_;
                } else {
                    const double disc = contact_force_ * contact_force_ + 2.0 * force_rate * budget;
                    if (disc >= 0) {
                        const double root = (-contact_force_ + std::sqrt(disc)) / force_rate;
                        if (root > 0) s = root;
                        if (force_rate < 0) {
                            const double other = (-contact_force_ - std::sqrt(disc)) / force_rate;
                            if (other > 0 && other < s) s = other;
                        }
                    }
                }
                if (s < step) { step = s; kind = Kind::Energy; }
            }
            // Releases: an active unilateral reaction reaching zero.
            for (std::size_t k = 0; k < constraint_owner_.size(); ++k) {
                const Owner &owner = constraint_owner_[k];
                if (owner.kind != Owner::Kind::SupportNormal && owner.kind != Owner::Kind::Ball) continue;
                // A locked knife-edge is not a release candidate: it releases
                // inside the active-set pass once the travel has advanced.
                if (owner.kind == Owner::Kind::SupportNormal ? support_locked_[owner.node] : ball_locked_[owner.node]) continue;
                const double lambda = reactions_[k], rate = rate_reactions_[k];
                if (rate >= 0) continue;
                // A reaction already at or below zero that is falling separates
                // now: a zero-length release, so that no segment is integrated
                // with a contact that has stopped pushing.
                const double s = lambda <= 0 ? 0.0 : -lambda / rate;
                if (s < step) { step = s; kind = Kind::Release; event_node = owner.node; event_on_ball = owner.kind == Owner::Kind::Ball; }
            }
            std::vector<std::uint32_t> touching_ball, touching_support;
            // Activations: an inactive contact closing.
            const Vec3 centre = scene_.ball_center_m + travel_ * scene_.ball_direction;
            for (std::uint32_t i = 0; i < count_; ++i) {
                if (frozen_[i]) continue;
                if (support_eligible_[i] && !support_active_[i]) {
                    const double gap = signedDistanceToPlane(scene_.support, reference_[i] + displacement_[i]);
                    const double gap_rate = dot(rate_[i], scene_.support.normal_world);
                    if (gap_rate < 0) {
                        if (gap <= 0) { touching_support.push_back(i); if (step > 0) { step = 0; kind = Kind::Activation; } }
                        else {
                            const double s = -gap / gap_rate;
                            if (s > 0 && s < step) { step = s; kind = Kind::Activation; event_node = i; event_on_ball = false; }
                        }
                    }
                }
                if (!ball_active_[i] && !loose_[i]) {
                    const Vec3 a = reference_[i] + displacement_[i] - centre;
                    const Vec3 b = rate_[i] - scene_.ball_direction;
                    const double bb = lengthSquared(b), ab = dot(a, b), aa = lengthSquared(a) - scene_.ball_radius_m * scene_.ball_radius_m;
                    if (aa <= 0) {
                        // Already touching: it becomes a contact the moment it closes.
                        if (ab < 0) { touching_ball.push_back(i); if (step > 0) { step = 0; kind = Kind::Activation; } }
                        continue;
                    }
                    if (bb <= 0) continue;
                    const double disc = ab * ab - bb * aa;
                    if (disc < 0) continue;
                    const double s = (-ab - std::sqrt(disc)) / bb;
                    if (s > 0 && s < step) { step = s; kind = Kind::Activation; event_node = i; event_on_ball = true; }
                }
            }
            // Bond failure: the shared criterion's ratio reaches one.
            if (step > 0) {
                const auto criterion_start2 = Clock::now();
                const double s = bondEventTravel(ratio, step);
                result_.criterion_wall_s += secondsSince(criterion_start2);
                if (s < step) { step = s; kind = Kind::BondFailure; }
            }
            if (!std::isfinite(step) || step < 0 || (step == 0 && kind != Kind::Activation && kind != Kind::Release)) {
                result_.stop = QuasiStaticStop::TravelLimit;
                return finish();
            }
            if (step == 0) {
                if (++zero_steps_at_travel > 64) { result_.stop = QuasiStaticStop::ActiveSetFailed; return finish(); }
            } else zero_steps_at_travel = 0;
            if (!hasStaticContact() && kind != Kind::Activation && !(kind == Kind::Release && step == 0)) {
                // Nothing statically supported is in the way: the ball leaves.
                result_.stop = QuasiStaticStop::BallThrough;
                return finish();
            }
            if (settings_.trace)
                std::fprintf(stderr, "event %u: travel %.4e -> %.4e m kind=%s node=%u force=%.3f N rate=%.3f N/m ratio=%.6f work=%.4e J\n",
                    result_.events + 1, travel_, travel_ + step,
                    kind == Kind::BondFailure ? "bond" : kind == Kind::Release ? "release" : kind == Kind::Activation ? "activation"
                    : kind == Kind::Energy ? "energy" : "travel", event_node, contact_force_, force_rate, ratio, work_);

            // Advance along the affine segment. Within a segment the ball's
            // work is the change of the lattice potential; the mismatch between
            // the two is recorded because it is the check on the reactions.
            for (std::size_t i = 0; i < count_; ++i) displacement_[i] += step * rate_[i];
            for (std::size_t k = 0; k < reactions_.size(); ++k) reactions_[k] += step * rate_reactions_[k];
            const double segment_work = contact_force_ * step + 0.5 * force_rate * step * step;
            work_ += segment_work;
            ledger_potential_ += segment_work;
            result_.segment_work_mismatch_j = std::max(result_.segment_work_mismatch_j, std::abs(potential() - ledger_potential_));
            contact_force_ += force_rate * step;
            travel_ += step;
            if (step > 0) { std::fill(ball_locked_.begin(), ball_locked_.end(), char{0}); std::fill(support_locked_.begin(), support_locked_.end(), char{0}); }
            ++result_.events;
            event.travel_m = travel_;
            event.contact_force_n = contact_force_;
            event.ball_work_j = work_;
            event.stored_elastic_j = solver_.elasticEnergy(displacement_);
            event.components = components_.size();
            event.frozen_components = frozenCount();
            result_.log.push_back(event);
            event = {};

            if (kind == Kind::Energy) { result_.stop = QuasiStaticStop::BallStopped; return finish(); }
            if (kind == Kind::Travel) { result_.stop = QuasiStaticStop::TravelLimit; return finish(); }
            if (kind == Kind::Release) {
                if (event_on_ball) { ball_active_[event_node] = 0; ball_released_at_[event_node] = travel_; }
                else { support_active_[event_node] = 0; support_released_at_[event_node] = travel_; }
            } else if (kind == Kind::Activation && step == 0) {
                // Every contact that touches and closes at this travel joins at
                // once. One that was already released at this travel is a
                // knife-edge (zero force, closing): it stays active until the
                // travel advances and its rate settles the sign.
                for (const std::uint32_t i : touching_ball) { ball_active_[i] = 1; if (ball_released_at_[i] == travel_) ball_locked_[i] = 1; }
                for (const std::uint32_t i : touching_support) { support_active_[i] = 1; if (support_released_at_[i] == travel_) support_locked_[i] = 1; }
            } else if (kind == Kind::Activation) {
                if (event_on_ball) ball_active_[event_node] = 1; else support_active_[event_node] = 1;
            }
            if (!solveCurrent()) return finish();
        }
    }

private:
    struct Owner {
        enum class Kind : std::uint8_t { SupportNormal, Ball, Frozen } kind{};
        std::uint32_t node{};
    };

    void setPositions(const std::vector<Vec3> &u) {
        for (std::size_t i = 0; i < count_; ++i) matter_.nodes[i].position_world_m = reference_[i] + u[i];
    }

    double potential() const {
        double load_work = 0;
        for (std::size_t i = 0; i < count_; ++i) load_work += dot(loads_[i], displacement_[i]);
        return solver_.elasticEnergy(displacement_) - load_work;
    }

    std::size_t frozenCount() const {
        std::size_t frozen = 0;
        for (const bool flag : component_frozen_) frozen += flag ? 1 : 0;
        return frozen;
    }

    bool hasStaticContact() const {
        for (std::uint32_t i = 0; i < count_; ++i)
            if (ball_active_[i] && !frozen_[i]) return true;
        return false;
    }

    // Recompute components after a topology change. A component without a
    // static answer is frozen: snapped to its rest shape about its mass-weighted
    // mean displacement, its stored energy returned as released.
    void refreshComponents(bool allow_freeze) {
        components_ = findConnectedComponents(matter_);
        component_of_.assign(count_, 0);
        component_frozen_.assign(components_.size(), false);
        for (const FragmentComponent &component : components_)
            for (const std::uint32_t node : component.node_indices) component_of_[node] = component.id;
        for (const FragmentComponent &component : components_) {
            bool frozen = false;
            for (const std::uint32_t node : component.node_indices) if (frozen_[node]) { frozen = true; break; }
            if (!frozen && allow_freeze && !staticallySupported(component)) {
                frozen = true;
                freeze(component);
            }
            component_frozen_[component.id] = frozen;
            if (frozen) for (const std::uint32_t node : component.node_indices) { frozen_[node] = 1; support_active_[node] = 0; ball_active_[node] = 0; }
        }
    }

    bool staticallySupported(const FragmentComponent &component) const {
        std::vector<Vec3> points;
        for (const std::uint32_t node : component.node_indices)
            if (support_active_[node]) points.push_back(reference_[node]);
        if (points.size() < settings_.minimum_support_nodes) return false;
        const Vec3 origin = points.front();
        Vec3 axis{};
        for (const Vec3 &p : points) if (lengthSquared(p - origin) > 1.0e-12 * cell_size_ * cell_size_) { axis = normalized(p - origin); break; }
        if (lengthSquared(axis) == 0) return false;
        for (const Vec3 &p : points) {
            const Vec3 d = p - origin;
            if (lengthSquared(d - dot(d, axis) * axis) > 1.0e-6 * cell_size_ * cell_size_) return true;
        }
        return false;
    }

    double freeze(const FragmentComponent &component) {
        double energy = 0;
        for (std::uint32_t b = 0; b < matter_.bonds.size(); ++b) {
            if (!matter_.bonds[b].alive) continue;
            if (component_of_[matter_.asset->bonds[b].node_a] != component.id) continue;
            energy += solver_.bondElasticEnergy(b, displacement_);
        }
        Vec3 weighted{};
        double mass = 0;
        for (const std::uint32_t node : component.node_indices) {
            weighted += matter_.nodes[node].mass_kg * displacement_[node];
            mass += matter_.nodes[node].mass_kg;
        }
        const Vec3 mean = weighted / mass;
        for (const std::uint32_t node : component.node_indices) displacement_[node] = mean;
        result_.released_energy_j += energy;
        ledger_potential_ -= energy;
        if (settings_.trace) std::fprintf(stderr, "  freeze component %u (%zu nodes), released %.3e J\n", component.id, component.node_indices.size(), energy);
        return energy;
    }

    // Constraints for the current active set. Values follow the current ball
    // travel; the rate problem uses the same directions with rate values.
    void buildConstraints(bool rate_problem, std::vector<StaticConstraint> &out) {
        out.clear();
        constraint_owner_.clear();
        const Vec3 centre = scene_.ball_center_m + travel_ * scene_.ball_direction;
        for (std::uint32_t i = 0; i < count_; ++i) {
            if (frozen_[i]) {
                for (const Vec3 axis : {Vec3{1, 0, 0}, Vec3{0, 1, 0}, Vec3{0, 0, 1}}) {
                    out.push_back({i, axis, rate_problem ? 0.0 : dot(axis, displacement_[i])});
                    constraint_owner_.push_back({Owner::Kind::Frozen, i});
                }
                continue;
            }
            if (support_active_[i]) {
                const SupportPlaneFrame &plane = scene_.support;
                out.push_back({i, plane.normal_world, rate_problem ? 0.0 : dot(plane.normal_world, plane.point_world_m - reference_[i])});
                constraint_owner_.push_back({Owner::Kind::SupportNormal, i});
            }
            if (ball_active_[i]) {
                const Vec3 normal = normalized(reference_[i] + displacement_[i] - centre, scene_.ball_direction);
                out.push_back({i, normal, rate_problem ? dot(normal, scene_.ball_direction)
                                                       : scene_.ball_radius_m - dot(normal, reference_[i] - centre), false});
                constraint_owner_.push_back({Owner::Kind::Ball, i});
            }
        }
    }

    double ballForce(const std::vector<double> &reactions) const {
        double force = 0;
        for (std::size_t k = 0; k < constraint_owner_.size(); ++k)
            if (constraint_owner_[k].kind == Owner::Kind::Ball)
                force += reactions[k] * dot(constraints_[k].direction, scene_.ball_direction);
        return force;
    }
    double ballForceRate() const { return ballForce(rate_reactions_); }

    // Active-set iteration at the current travel. Returns false on failure,
    // with result_.stop set.
    bool solveCurrent() {
        for (unsigned iteration = 0; iteration < settings_.maximum_active_set_iterations; ++iteration) {
            ++result_.active_set_iterations;
            buildConstraints(false, constraints_);
            const auto solve_start = Clock::now();
            const StaticSolveResult solved = solver_.solve(loads_, constraints_, displacement_, settings_.solver, &component_of_);
            result_.solve_wall_s += secondsSince(solve_start);
            ++result_.static_solves;
            result_.linear_iterations += solved.iterations;
            if (!solved.converged) {
                if (settings_.trace) std::fprintf(stderr, "  static solve failed: %s after %u iterations, residual %.3e, pins %zu, dependent %zu, max prescribed %.3e m, deflated %zu\n",
                    solved.failure, solved.iterations, solved.relative_residual, solved.pinned_mechanism_directions, solved.dependent_constraints, solved.maximum_prescribed_m, solved.deflated_modes);
                result_.stop = QuasiStaticStop::SolverFailed;
                return false;
            }
            reactions_ = solved.reactions_n;
            result_.pinned_mechanism_directions = std::max(result_.pinned_mechanism_directions, solved.pinned_mechanism_directions);
            result_.pinned_mechanism_modes = std::max(result_.pinned_mechanism_modes, solved.deflated_mechanism_modes);
            result_.pinned_mechanism_force_n = std::max(result_.pinned_mechanism_force_n, solved.pinned_mechanism_force_n);
            result_.pinned_rigid_force_n = std::max(result_.pinned_rigid_force_n, solved.pinned_rigid_force_n);
            result_.pinned_rigid_torque_n_m = std::max(result_.pinned_rigid_torque_n_m, solved.pinned_rigid_torque_n_m);
            // A reaction is K u - f evaluated in floating point: its rounding
            // noise scales with the stiffness times the displacement, so the
            // release threshold must sit above that as well as above 1e-9 of
            // the physical force scale.
            double force_scale = 0, displacement_scale = 0;
            for (const double lambda : reactions_) force_scale = std::max(force_scale, std::abs(lambda));
            for (const Vec3 &load : loads_) force_scale = std::max(force_scale, length(load));
            for (const Vec3 &u : displacement_) displacement_scale = std::max(displacement_scale, length(u));
            const double force_tolerance = std::max(1.0e-9 * force_scale, 1.0e-12 * solver_.referenceStiffness() * displacement_scale + 1.0e-300);
            // Releases first. A locked (knife-edge) contact releases only when it
            // is clearly pulling against the scale of the other reactions.
            bool changed = false;
            unsigned released = 0, activated = 0;
            // A knife-edge contact pulls only by the force the contact stiffness
            // develops over the geometric tolerance; more than that is a real
            // separation even for a locked contact.
            const double strong_pull = std::max(1.0e-6 * force_scale, solver_.referenceStiffness() * 1.0e-9 * cell_size_);
            for (std::size_t k = 0; k < constraint_owner_.size(); ++k) {
                const Owner &owner = constraint_owner_[k];
                const bool locked = owner.kind == Owner::Kind::SupportNormal ? support_locked_[owner.node] != 0
                                  : owner.kind == Owner::Kind::Ball ? ball_locked_[owner.node] != 0 : false;
                if (locked && reactions_[k] >= -strong_pull) continue;
                if (owner.kind == Owner::Kind::SupportNormal && reactions_[k] < -force_tolerance) {
                    support_active_[owner.node] = 0; support_released_at_[owner.node] = travel_; changed = true; ++released;
                    if (settings_.trace) std::fprintf(stderr, "    release support node %u (%.3e N)\n", owner.node, reactions_[k]);
                }
                if (owner.kind == Owner::Kind::Ball && reactions_[k] < -force_tolerance) {
                    ball_active_[owner.node] = 0; ball_released_at_[owner.node] = travel_; changed = true; ++released;
                    if (settings_.trace) std::fprintf(stderr, "    release ball node %u (%.3e N)\n", owner.node, reactions_[k]);
                }
            }
            if (changed) {
                // A release can leave a piece without a static answer.
                for (const FragmentComponent &component : components_) {
                    if (component_frozen_[component.id] || staticallySupported(component)) continue;
                    freeze(component);
                    component_frozen_[component.id] = true;
                    for (const std::uint32_t node : component.node_indices) { frozen_[node] = 1; support_active_[node] = 0; ball_active_[node] = 0; }
                }
                if (settings_.trace) std::fprintf(stderr, "  active set: released %u\n", released);
                continue;
            }
            // Then activations.
            const Vec3 centre = scene_.ball_center_m + travel_ * scene_.ball_direction;
            const double gap_tolerance = 1.0e-12 * cell_size_;
            for (std::uint32_t i = 0; i < count_; ++i) {
                if (frozen_[i]) continue;
                const Vec3 position = reference_[i] + displacement_[i];
                if (support_eligible_[i] && !support_active_[i] && signedDistanceToPlane(scene_.support, position) < -gap_tolerance) {
                    support_active_[i] = 1;
                    if (support_released_at_[i] == travel_) support_locked_[i] = 1;
                    changed = true;
                    ++activated;
                }
                if (!ball_active_[i] && !loose_[i] && length(position - centre) < scene_.ball_radius_m - gap_tolerance) {
                    ball_active_[i] = 1;
                    if (ball_released_at_[i] == travel_) ball_locked_[i] = 1;
                    changed = true;
                    ++activated;
                    if (settings_.trace) std::fprintf(stderr, "    activate ball node %u%s\n", i, ball_locked_[i] ? " (locked)" : "");
                }
            }
            if (changed) {
                if (settings_.trace) std::fprintf(stderr, "  active set: activated %u\n", activated);
                continue;
            }
            contact_force_ = ballForce(reactions_);
            recordSupportForces(solved);
            if (settings_.trace) {
                unsigned support = 0, ball = 0;
                for (std::uint32_t i = 0; i < count_; ++i) { support += support_active_[i]; ball += ball_active_[i]; }
                std::fprintf(stderr, "  solved: support=%u ball=%u force=%.4f N pcg=%u deflated=%zu pinned_force=%.3e N stored=%.4e J\n",
                    support, ball, contact_force_, solved.iterations, solved.deflated_modes, solved.pinned_rigid_force_n, solver_.elasticEnergy(displacement_));
            }
            return true;
        }
        result_.stop = QuasiStaticStop::ActiveSetFailed;
        return false;
    }

    void recordSupportForces(const StaticSolveResult &solved) {
        double total = 0, largest = 0;
        for (std::size_t k = 0; k < constraint_owner_.size(); ++k) {
            if (constraint_owner_[k].kind != Owner::Kind::SupportNormal) continue;
            total += reactions_[k];
            largest = std::max(largest, reactions_[k]);
        }
        result_.maximum_support_normal_force_n = std::max(result_.maximum_support_normal_force_n, largest);
        result_.total_support_normal_force_n = total;
        if (total > 1.0e-9) result_.required_friction_coefficient = std::max(result_.required_friction_coefficient, solved.pinned_rigid_force_n / total);
    }

    // Displacement per unit ball travel for the current active set.
    bool solveRate() {
        buildConstraints(true, rate_constraints_);
        std::vector<Vec3> zero_loads(count_);
        StaticSolveSettings rate_settings = settings_.solver;
        rate_settings.pin_mechanisms_at_zero = true;
        const auto solve_start = Clock::now();
        const StaticSolveResult solved = solver_.solve(zero_loads, rate_constraints_, rate_, rate_settings, &component_of_);
        result_.solve_wall_s += secondsSince(solve_start);
        ++result_.static_solves;
        result_.linear_iterations += solved.iterations;
        if (!solved.converged) {
            if (settings_.trace) std::fprintf(stderr, "  rate solve failed: %s after %u iterations, residual %.3e\n", solved.failure, solved.iterations, solved.relative_residual);
            result_.stop = QuasiStaticStop::SolverFailed;
            return false;
        }
        rate_reactions_ = solved.reactions_n;
        result_.pinned_mechanism_modes = std::max(result_.pinned_mechanism_modes, solved.deflated_mechanism_modes);
        if (settings_.trace) std::fprintf(stderr, "  rate: pcg=%u deflated=%zu mechanisms=%zu force_rate=%.4e N/m\n",
            solved.iterations, solved.deflated_modes, solved.deflated_mechanism_modes, ballForceRate());
        return true;
    }

    // Largest ratio of a live bond's recorded peak to its removal threshold,
    // through the shared criterion's own strain evaluation.
    double failureRatio(const std::vector<Vec3> &u) {
        setPositions(u);
        resetBondStrainPeaks(matter_);
        accumulateBondStrainPeaks(matter_);
        double ratio = 0;
        for (std::size_t b = 0; b < matter_.bonds.size(); ++b) {
            const ActiveBondState &state = matter_.bonds[b];
            if (!state.alive) continue;
            const BondRest &rest = matter_.asset->bonds[b];
            const auto part = [&](double peak, double end) {
                return std::isfinite(end) && end > 0 ? peak / end : 0.0;
            };
            ratio = std::max({ratio, part(state.peak_tensile_stretch, rest.damage_end_stretch),
                part(state.peak_compressive_strain, rest.compression_damage_end_strain),
                part(state.peak_shear_strain, rest.shear_damage_end_strain)});
        }
        return ratio;
    }

    // Travel at which the failure ratio reaches one along the current rate,
    // or +infinity if it does not within the limit. The ratio is nearly affine
    // in travel, so a secant bracket then Illinois converges in a few steps.
    double bondEventTravel(double ratio_now, double limit) {
        const double target = 1.0 + settings_.event_overshoot;
        std::vector<Vec3> trial(count_);
        const auto ratio_at = [&](double s) {
            for (std::size_t i = 0; i < count_; ++i) trial[i] = displacement_[i] + s * rate_[i];
            return failureRatio(trial);
        };
        const double probe = 1.0e-4 * cell_size_;
        const double ratio_probe = ratio_at(probe);
        const double slope = (ratio_probe - ratio_now) / probe;
        if (!(slope > 1.0e-12) || !std::isfinite(slope)) return kInfinity;
        double lo = 0, lo_ratio = ratio_now;
        double hi = (target - ratio_now) / slope;
        if (!std::isfinite(hi) || hi <= 0) return kInfinity;
        if (std::isfinite(limit) && hi > 4.0 * limit) return kInfinity;
        double hi_ratio = ratio_at(hi);
        unsigned expansions = 0;
        while (hi_ratio < target) {
            if (++expansions > 60 || (std::isfinite(limit) && hi > 4.0 * limit)) return kInfinity;
            lo = hi; lo_ratio = hi_ratio;
            const double local_slope = std::max((hi_ratio - ratio_now) / std::max(hi, 1.0e-300), 1.0e-12);
            hi = hi + std::max((target - hi_ratio) / local_slope, 0.25 * hi);
            hi_ratio = ratio_at(hi);
        }
        // Illinois on [lo, hi] with ratio(lo) < target <= ratio(hi).
        int side = 0;
        for (unsigned iteration = 0; iteration < 200; ++iteration) {
            if (hi_ratio - target <= 1.0e-10 && hi_ratio >= 1.0) break;
            if (hi - lo <= 1.0e-15 * std::max(hi, 1.0)) break;
            const double mid = hi - (hi_ratio - target) * (hi - lo) / (hi_ratio - lo_ratio);
            const double mid_ratio = ratio_at(mid);
            if (mid_ratio >= target) {
                hi = mid; hi_ratio = mid_ratio;
                if (side == -1) lo_ratio = target + 0.5 * (lo_ratio - target);
                side = -1;
            } else {
                lo = mid; lo_ratio = mid_ratio;
                if (side == 1) hi_ratio = target + 0.5 * (hi_ratio - target);
                side = 1;
            }
        }
        return hi;
    }

    QuasiStaticImpactResult finish() {
        setPositions(displacement_);
        result_.converged = result_.stop == QuasiStaticStop::BallStopped || result_.stop == QuasiStaticStop::BallThrough ||
                            result_.stop == QuasiStaticStop::TravelLimit;
        result_.travel_m = travel_;
        result_.ball_center_m = scene_.ball_center_m + travel_ * scene_.ball_direction;
        result_.ball_work_j = work_;
        result_.kinetic_energy_out_j = std::max(0.0, result_.kinetic_energy_in_j - work_);
        result_.potential_end_j = potential();
        result_.stored_elastic_j = solver_.elasticEnergy(displacement_);
        if (result_.stop == QuasiStaticStop::BallStopped) {
            // The lattice held: unloading returns the stored energy to the ball.
            result_.ball_velocity_m_s = -std::sqrt(2.0 * result_.stored_elastic_j / scene_.ball_mass_kg) * scene_.ball_direction;
        } else {
            result_.ball_velocity_m_s = std::sqrt(2.0 * result_.kinetic_energy_out_j / scene_.ball_mass_kg) * scene_.ball_direction;
        }
        result_.components = components_.size();
        result_.frozen_components = frozenCount();
        result_.component_frozen = component_frozen_;
        result_.failure_modes = countBondFailureModes(matter_);
        result_.broken_bonds = countBrokenBonds(matter_);
        return result_;
    }

    ActiveMatter &matter_;
    const QuasiStaticImpactScene &scene_;
    const QuasiStaticImpactSettings &settings_;
    std::size_t count_;
    StaticLatticeSolver solver_;
    QuasiStaticImpactResult result_;
    std::vector<Vec3> reference_, displacement_, loads_, rate_;
    std::vector<char> support_eligible_, support_active_, ball_active_, frozen_, loose_;
    std::vector<double> support_released_at_, ball_released_at_;
    std::vector<char> support_locked_, ball_locked_;
    std::vector<StaticConstraint> constraints_, rate_constraints_;
    std::vector<Owner> constraint_owner_;
    std::vector<double> reactions_, rate_reactions_;
    std::vector<FragmentComponent> components_;
    std::vector<std::uint32_t> component_of_;
    std::vector<bool> component_frozen_;
    double cell_size_{1.0};
    double travel_{}, work_{}, contact_force_{}, ledger_potential_{};
};

} // namespace

QuasiStaticImpactResult runQuasiStaticImpact(ActiveMatter &matter, const QuasiStaticImpactScene &scene,
    const QuasiStaticImpactSettings &settings) {
    ImpactRunner runner(matter, scene, settings);
    return runner.run();
}

} // namespace banjo
