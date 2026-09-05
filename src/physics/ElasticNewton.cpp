#include "physics/ElasticNewton.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>

namespace banjo::detail {
namespace {
using Vector = std::vector<Vec3>;
double inner(const Vector &a, const Vector &b) {
    double sum = 0;
    for (std::size_t i = 0; i < a.size(); ++i) sum += dot(a[i], b[i]);
    return sum;
}
double norm(const Vector &a) { return std::sqrt(inner(a, a)); }
void axpy(Vector &a, double scale, const Vector &b) {
    for (std::size_t i = 0; i < a.size(); ++i) a[i] += scale * b[i];
}
void add(Mat3 &a, const Mat3 &b, double scale) {
    for (unsigned i = 0; i < 3; ++i) for (unsigned j = 0; j < 3; ++j) a.m[i][j] += scale * b.m[i][j];
}
Mat3 identity() { Mat3 m; for (unsigned i = 0; i < 3; ++i) m.m[i][i] = 1; return m; }

struct BondEvaluation { Vec3 impulse; Mat3 tangent; };
BondEvaluation evaluate(const BondRest &bond, Vec3 q0, Vec3 displacement, double dt) {
    const Vec3 q1 = q0 + displacement, sum_vector = 2 * q0 + displacement;
    const double r0 = length(q0), r1 = length(q1), sum = r0 + r1;
    // Stable length increment: subtracting two almost equal lengths loses the
    // very small strain that determines a stiff material's restoring force.
    const double length_change = dot(displacement, sum_vector) / sum;
    const double strain_numerator = 2 * (r0 - bond.rest_length_m) + length_change;
    const double coefficient = strain_numerator / sum;
    BondEvaluation out;
    out.impulse = (-.5 * dt / bond.compliance * coefficient) * sum_vector;
    // Minus d(impulse_on_b)/d(v_b-v_a). The dyadic is generally nonsymmetric,
    // so use GMRES rather than assuming an SPD conjugate-gradient system.
    const double scale = .25 * dt * dt / bond.compliance;
    const double dyadic = r1 > 1e-15 ? 2 * bond.rest_length_m / (sum * sum * r1) : 0;
    const double u[3]{sum_vector.x, sum_vector.y, sum_vector.z};
    const double q[3]{q1.x, q1.y, q1.z};
    for (unsigned i = 0; i < 3; ++i) for (unsigned j = 0; j < 3; ++j)
        out.tangent.m[i][j] = scale * ((i == j ? coefficient : 0) + dyadic * u[i] * q[j]);
    return out;
}
struct Edge { std::uint32_t a, b; Mat3 tangent; };
}

double elasticVelocityResidual(const ActiveMatter &matter, double dt,
    const Vector &initial, const Vector &base, const std::vector<double> &inverse_mass,
    const Vector &velocity, Vector *output, const ElasticSupport *support, std::vector<bool> *active_support) {
    Vector residual(velocity.size());
    for (std::size_t i = 0; i < velocity.size(); ++i) residual[i] = velocity[i] - base[i];
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) if (matter.bonds[i].alive) {
        const auto &bond = matter.asset->bonds[i];
        const auto a = bond.node_a, b = bond.node_b;
        const auto e = evaluate(bond, matter.nodes[b].position_world_m - matter.nodes[a].position_world_m,
            .5 * dt * (initial[b] - initial[a] + velocity[b] - velocity[a]), dt);
        residual[a] += inverse_mass[a] * e.impulse;
        residual[b] -= inverse_mass[b] * e.impulse;
    }
    if (active_support) active_support->assign(velocity.size(), false);
    if (support) for (std::size_t i = 0; i < velocity.size(); ++i) {
        const double reaction_velocity = dot(residual[i], support->normal);
        const double gap_velocity = dot(velocity[i], support->normal) - support->minimum_velocity[i];
        // Complementarity: R.n = lambda/m >= 0, gap >= 0, lambda*gap = 0.
        // Replace the normal equation by min(R.n, 2*gap/dt) = 0. Active
        // constraints get a normal-velocity row; tangential momentum is kept.
        const bool active = reaction_velocity > gap_velocity;
        if (active) residual[i] += (gap_velocity - reaction_velocity) * support->normal;
        if (active_support) (*active_support)[i] = active;
    }
    double maximum = 0;
    for (const auto r : residual) {
        const double value = length(r);
        if (!std::isfinite(value)) return std::numeric_limits<double>::infinity();
        maximum = std::max(maximum, value);
    }
    if (output) *output = std::move(residual);
    return maximum;
}

bool elasticNewtonUpdate(const ActiveMatter &matter, double dt,
    const Vector &initial, const Vector &base, const std::vector<double> &inverse_mass,
    Vector &velocity, double tolerance, unsigned maximum_linear_iterations, unsigned &linear_iterations,
    const ElasticSupport *support) {
    Vector residual;
    std::vector<bool> active;
    const double maximum = elasticVelocityResidual(matter, dt, initial, base, inverse_mass, velocity, &residual, support, &active);
    if (!std::isfinite(maximum)) return false;
    if (maximum <= tolerance) return true;
    const std::size_t count = velocity.size();
    std::vector<Edge> edges;
    edges.reserve(matter.bonds.size());
    std::vector<Mat3> diagonal(count, identity());
    for (std::size_t i = 0; i < matter.bonds.size(); ++i) if (matter.bonds[i].alive) {
        const auto &bond = matter.asset->bonds[i];
        const auto a = bond.node_a, b = bond.node_b;
        const auto e = evaluate(bond, matter.nodes[b].position_world_m - matter.nodes[a].position_world_m,
            .5 * dt * (initial[b] - initial[a] + velocity[b] - velocity[a]), dt);
        edges.push_back({a, b, e.tangent});
        add(diagonal[a], e.tangent, inverse_mass[a]);
        add(diagonal[b], e.tangent, inverse_mass[b]);
    }
    std::vector<Mat3> inverse_diagonal(count);
    for (std::size_t i = 0; i < count; ++i) {
        if (active[i]) {
            const auto n = support->normal;
            const double normal[3]{n.x, n.y, n.z};
            for (unsigned j = 0; j < 3; ++j) {
                Vec3 column{diagonal[i].m[0][j], diagonal[i].m[1][j], diagonal[i].m[2][j]};
                column += (normal[j] - dot(column, n)) * n;
                diagonal[i].m[0][j] = column.x;
                diagonal[i].m[1][j] = column.y;
                diagonal[i].m[2][j] = column.z;
            }
        }
        inverse_diagonal[i] = diagonal[i].inverse(0).value_or(identity());
    }
    const auto precondition = [&](Vector &v) {
        for (std::size_t i = 0; i < count; ++i) v[i] = inverse_diagonal[i] * v[i];
    };
    const auto apply = [&](const Vector &v) {
        Vector out = v;
        for (const auto &edge : edges) {
            const auto product = edge.tangent * (v[edge.a] - v[edge.b]);
            out[edge.a] += inverse_mass[edge.a] * product;
            out[edge.b] -= inverse_mass[edge.b] * product;
        }
        if (support) for (std::size_t i = 0; i < count; ++i) if (active[i])
            out[i] += (dot(v[i], support->normal) - dot(out[i], support->normal)) * support->normal;
        precondition(out);
        return out;
    };
    Vector rhs = residual;
    for (auto &v : rhs) v = -v;
    precondition(rhs);
    Vector increment(count);
    const double initial_norm = norm(rhs);
    if (!std::isfinite(initial_norm) || initial_norm == 0) return false;
    // This only controls the inexact Newton direction. The outer constitutive
    // residual and independent momentum/energy audits still decide acceptance.
    const double linear_tolerance = 1e-5 * initial_norm;
    constexpr unsigned restart = 40;
    unsigned used = 0;
    while (used < maximum_linear_iterations) {
        Vector r = rhs;
        axpy(r, -1, apply(increment));
        const double beta = norm(r);
        if (beta <= linear_tolerance) break;
        if (!std::isfinite(beta)) return false;
        std::vector<Vector> basis;
        basis.reserve(restart + 1);
        for (auto &v : r) v *= 1 / beta;
        basis.push_back(std::move(r));
        double h[restart + 1][restart]{};
        double cosine[restart]{}, sine[restart]{}, g[restart + 1]{};
        g[0] = beta;
        unsigned columns = 0;
        for (; columns < restart && used < maximum_linear_iterations; ++columns, ++used) {
            Vector w = apply(basis[columns]);
            // Reorthogonalized modified Gram-Schmidt keeps the Krylov basis
            // usable when stiffness and rigid-motion scales are very different.
            for (unsigned pass = 0; pass < 2; ++pass) for (unsigned j = 0; j <= columns; ++j) {
                const double projection = inner(w, basis[j]);
                h[j][columns] += projection;
                axpy(w, -projection, basis[j]);
            }
            const double next_norm = norm(w);
            h[columns + 1][columns] = next_norm;
            const bool breakdown = next_norm <= 1e-30;
            if (!breakdown) { for (auto &v : w) v *= 1 / next_norm; basis.push_back(std::move(w)); }
            for (unsigned j = 0; j < columns; ++j) {
                const double first = cosine[j]*h[j][columns] + sine[j]*h[j+1][columns];
                h[j+1][columns] = -sine[j]*h[j][columns] + cosine[j]*h[j+1][columns];
                h[j][columns] = first;
            }
            const double divisor = std::hypot(h[columns][columns], h[columns+1][columns]);
            if (!std::isfinite(divisor) || divisor <= 1e-30) return false;
            cosine[columns] = h[columns][columns] / divisor;
            sine[columns] = h[columns+1][columns] / divisor;
            h[columns][columns] = divisor;
            h[columns+1][columns] = 0;
            g[columns+1] = -sine[columns]*g[columns];
            g[columns] *= cosine[columns];
            if (std::abs(g[columns+1]) <= linear_tolerance || breakdown) { ++columns; ++used; break; }
        }
        double y[restart]{};
        for (int j = static_cast<int>(columns) - 1; j >= 0; --j) {
            y[j] = g[j];
            for (unsigned k = static_cast<unsigned>(j) + 1; k < columns; ++k) y[j] -= h[j][k]*y[k];
            y[j] /= h[j][j];
        }
        for (unsigned j = 0; j < columns; ++j) axpy(increment, y[j], basis[j]);
    }
    linear_iterations += used;
    const double old_norm = norm(residual);
    for (double scale = 1; scale >= 1.0 / 4096; scale *= .5) {
        Vector trial = velocity;
        axpy(trial, scale, increment);
        Vector trial_residual;
        const double trial_max = elasticVelocityResidual(matter, dt, initial, base, inverse_mass, trial, &trial_residual, support);
        if (trial_max <= tolerance || (std::isfinite(trial_max) && norm(trial_residual) < old_norm * (1 - 1e-4*scale))) {
            velocity = std::move(trial);
            return true;
        }
    }
    return false;
}
}
