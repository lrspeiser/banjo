#include "algo1/CrackCascade.hpp"

#include "fracture/BondFailure.hpp"
#include "fracture/ConnectedComponents.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <utility>

namespace banjo::algo1 {
namespace {

using Clock = std::chrono::steady_clock;
double since(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

// Closed-form advance of every modal oscillator over one fixed interval. The
// elastic evolution has no time step and no stability limit; this is the exact
// solution of q'' + 2 zeta w q' + w^2 q = 0 over dt.
struct Propagator {
    std::vector<double> a11, a12, a21, a22;

    void build(const ImpulseLibrary &library, double dt, double zeta) {
        const std::size_t m = library.modes();
        a11.assign(m, 1.0);
        a12.assign(m, dt);
        a21.assign(m, 0.0);
        a22.assign(m, 1.0);
        for (std::size_t mode = 0; mode < m; ++mode) {
            if (library.isRigidMode(mode)) continue;
            const double w = library.omega()[mode];
            const double wd = w * std::sqrt(std::max(1.0e-300, 1.0 - zeta * zeta));
            const double decay = std::exp(-zeta * w * dt);
            const double cosine = std::cos(wd * dt), sine = std::sin(wd * dt);
            a11[mode] = decay * (cosine + zeta * w / wd * sine);
            a12[mode] = decay * sine / wd;
            a21[mode] = -decay * (w * w / wd) * sine;
            a22[mode] = decay * (cosine - zeta * w / wd * sine);
        }
    }

    void advance(std::vector<double> &q, std::vector<double> &qdot) const {
        for (std::size_t mode = 0; mode < q.size(); ++mode) {
            const double x = q[mode], v = qdot[mode];
            q[mode] = a11[mode] * x + a12[mode] * v;
            qdot[mode] = a21[mode] * x + a22[mode] * v;
        }
    }
};

struct ImpulseEvent {
    std::uint32_t step{};
    std::uint32_t node{};
    Vec3 impulse{};
};

// The quasi-static release: K_k^-1 = S + S D (Kappa^-1 - D^T S D)^-1 D^T S.
// The columns S D are the library's compliance columns, so a round costs
// O(n k) for the field plus O(k^2) to extend the inverse by bordering.
class Woodbury {
public:
    explicit Woodbury(const ImpulseLibrary &library) : library_(&library) {}

    [[nodiscard]] std::size_t size() const { return released_.size(); }
    [[nodiscard]] unsigned singular() const { return singular_; }

    // Extends the released set. Returns false when the release detaches a
    // mechanism (the Schur complement collapses) and the quasi-static
    // correction for it is unbounded; the bond stays broken in the lattice but
    // is left out of the correction, and the caller reports the count.
    bool add(std::uint32_t bond, double schur_floor) {
        const BondGradient &gradient = library_->gradients()[bond];
        if (!(gradient.stiffness_n_m > 0.0)) return false;
        std::vector<double> scratch;
        const double *column = library_->complianceColumn(bond, scratch);
        std::vector<double> stored(column, column + library_->dofs());

        const std::size_t k = released_.size();
        std::vector<double> border(k, 0.0);
        for (std::size_t p = 0; p < k; ++p) {
            // M(p, k) = -g_p . c_bond
            border[p] = -dot6(released_[p], stored.data());
        }
        const double diagonal = 1.0 / gradient.stiffness_n_m - dot6(bond, stored.data());

        std::vector<double> weighted(k, 0.0);
        for (std::size_t p = 0; p < k; ++p) {
            double sum = 0.0;
            for (std::size_t q = 0; q < k; ++q) sum += inverse_[p * k + q] * border[q];
            weighted[p] = sum;
        }
        double schur = diagonal;
        for (std::size_t p = 0; p < k; ++p) schur -= border[p] * weighted[p];
        if (!(std::abs(schur) > schur_floor / gradient.stiffness_n_m)) {
            ++singular_;
            return false;
        }
        const double inverse_schur = 1.0 / schur;
        std::vector<double> extended((k + 1) * (k + 1), 0.0);
        for (std::size_t p = 0; p < k; ++p) {
            for (std::size_t q = 0; q < k; ++q)
                extended[p * (k + 1) + q] = inverse_[p * k + q] + weighted[p] * weighted[q] * inverse_schur;
            extended[p * (k + 1) + k] = -weighted[p] * inverse_schur;
            extended[k * (k + 1) + p] = -weighted[p] * inverse_schur;
        }
        extended[k * (k + 1) + k] = inverse_schur;
        inverse_ = std::move(extended);
        released_.push_back(bond);
        columns_.push_back(std::move(stored));
        return true;
    }

    // field += S D M^-1 D^T field0, with field0 the intact response.
    // Returns the largest correction applied to any degree of freedom.
    double correct(const std::vector<double> &intact, std::vector<double> &field) const {
        const std::size_t k = released_.size();
        if (k == 0) return 0.0;
        std::vector<double> load(k, 0.0), solution(k, 0.0);
        for (std::size_t p = 0; p < k; ++p) load[p] = library_->bondExtension(released_[p], intact);
        for (std::size_t p = 0; p < k; ++p) {
            double sum = 0.0;
            const double *row = inverse_.data() + p * k;
            for (std::size_t q = 0; q < k; ++q) sum += row[q] * load[q];
            solution[p] = sum;
        }
        const std::size_t n = library_->dofs();
        double largest = 0.0;
        for (std::size_t p = 0; p < k; ++p) {
            const double weight = solution[p];
            if (weight == 0.0) continue;
            const double *column = columns_[p].data();
            for (std::size_t dof = 0; dof < n; ++dof) field[dof] += weight * column[dof];
        }
        for (std::size_t dof = 0; dof < n; ++dof)
            largest = std::max(largest, std::abs(field[dof] - intact[dof]));
        return largest;
    }

private:
    [[nodiscard]] double dot6(std::uint32_t bond, const double *column) const {
        const BondGradient &gradient = library_->gradients()[bond];
        double sum = 0.0;
        for (unsigned p = 0; p < gradient.count; ++p) sum += gradient.value[p] * column[gradient.dof[p]];
        return sum;
    }

    const ImpulseLibrary *library_{};
    std::vector<std::uint32_t> released_;
    std::vector<std::vector<double>> columns_;
    std::vector<double> inverse_;
    unsigned singular_{};
};

// The envelope trackers the screen reads. For an elastic mode the amplitude
// never exceeds sqrt(q^2 + (qdot/w)^2); a zero-frequency mode has no envelope
// at all and its bound grows linearly with time, which is exactly what a
// mechanism does and why it is reported separately.
struct Envelope {
    std::vector<double> elastic;      // max sqrt(q^2 + (qdot/w)^2)
    std::vector<double> rigid_offset; // max |q| seen
    std::vector<double> rigid_rate;   // max |qdot| seen
    double sampled_until_s{};

    void reset(std::size_t modes) {
        elastic.assign(modes, 0.0);
        rigid_offset.assign(modes, 0.0);
        rigid_rate.assign(modes, 0.0);
        sampled_until_s = 0.0;
    }

    void observe(const ImpulseLibrary &library, const std::vector<double> &q,
                 const std::vector<double> &qdot, double time_s) {
        for (std::size_t mode = 0; mode < q.size(); ++mode) {
            if (library.isRigidMode(mode)) {
                rigid_offset[mode] = std::max(rigid_offset[mode], std::abs(q[mode]));
                rigid_rate[mode] = std::max(rigid_rate[mode], std::abs(qdot[mode]));
                continue;
            }
            const double scaled = qdot[mode] / library.omega()[mode];
            elastic[mode] = std::max(elastic[mode], std::sqrt(q[mode] * q[mode] + scaled * scaled));
        }
        sampled_until_s = std::max(sampled_until_s, time_s);
    }

    // A bound on |q_i(t)| valid for every instant up to `time_s`.
    void bound(const ImpulseLibrary &library, double time_s, std::vector<double> &out) const {
        out.assign(elastic.size(), 0.0);
        const double after = std::max(0.0, time_s - sampled_until_s);
        for (std::size_t mode = 0; mode < out.size(); ++mode)
            out[mode] = library.isRigidMode(mode) ? rigid_offset[mode] + rigid_rate[mode] * after
                                                  : elastic[mode];
    }
};

// Upper bound on every quantity the shared criterion reads, from a bound on the
// modal amplitudes. Rigorous for the intact field: the bond's own stretch from
// its axial and transverse relative displacement, and the nonlocal
// Green-Lagrange strain from the node's rest covariance.
} // namespace

void boundCriterionStrain(const ActiveMatter &matter, const ImpulseLibrary &library,
                          const std::vector<double> &amplitude_bound, StrainBounds &work) {
    const std::size_t bonds = library.bondCount();
    const std::size_t m = library.modes();
    const std::size_t nodes = matter.nodes.size();
    work.axial.assign(bonds, 0.0);
    work.relative.assign(bonds, 0.0);
    work.node_gradient.assign(nodes, 0.0);
    work.node_bound.assign(nodes, 0.0);
    work.criterion.assign(bonds, 0.0);

    const modal::DenseMatrix &amplitude = library.amplitude();
    const modal::DenseMatrix &phi = library.phi();
    const std::vector<std::uint32_t> &free_of = library.freeDofOf();

#ifdef _OPENMP
#pragma omp parallel for schedule(static)
#endif
    for (std::ptrdiff_t index = 0; index < static_cast<std::ptrdiff_t>(bonds); ++index) {
        const std::size_t bond = static_cast<std::size_t>(index);
        const double *row = amplitude.row(bond);
        const double rest_length = library.gradients()[bond].rest_length_m;
        double axial = 0.0;
        for (std::size_t mode = 0; mode < m; ++mode) axial += std::abs(row[mode]) * amplitude_bound[mode];
        work.axial[bond] = axial * rest_length;

        const BondRest &rest = matter.asset->bonds[bond];
        const double *left[3] = {nullptr, nullptr, nullptr};
        const double *right[3] = {nullptr, nullptr, nullptr};
        for (unsigned axis = 0; axis < 3U; ++axis) {
            const std::uint32_t a = free_of[3U * rest.node_a + axis];
            const std::uint32_t b = free_of[3U * rest.node_b + axis];
            left[axis] = a == kFixedDof ? nullptr : phi.row(a);
            right[axis] = b == kFixedDof ? nullptr : phi.row(b);
        }
        double relative = 0.0;
        for (std::size_t mode = 0; mode < m; ++mode) {
            double squared = 0.0;
            for (unsigned axis = 0; axis < 3U; ++axis) {
                const double difference = (right[axis] ? right[axis][mode] : 0.0) -
                                          (left[axis] ? left[axis][mode] : 0.0);
                squared += difference * difference;
            }
            relative += std::sqrt(squared) * amplitude_bound[mode];
        }
        work.relative[bond] = relative;
    }

    // Nonlocal strain: grad u = (sum_b w_b du_b x dx_b) R^-1, so its norm is
    // bounded by (sum_b |du_b| / |dx_b|) * ||R^-1||_F, and the Green-Lagrange
    // measure adds half its square.
    for (std::size_t node = 0; node < nodes; ++node) {
        Mat3 covariance{};
        double accumulated = 0.0;
        std::size_t live = 0;
        const std::uint32_t begin = matter.asset->adjacency_offsets[node];
        const std::uint32_t end = matter.asset->adjacency_offsets[node + 1U];
        for (std::uint32_t adjacency = begin; adjacency < end; ++adjacency) {
            const std::uint32_t bond = matter.asset->adjacent_bond_indices[adjacency];
            if (!matter.bonds[bond].alive) continue;
            const BondRest &rest = matter.asset->bonds[bond];
            const std::uint32_t other = rest.node_a == node ? rest.node_b : rest.node_a;
            const Vec3 edge = matter.reference_positions_world_m[other] -
                              matter.reference_positions_world_m[node];
            const double squared = lengthSquared(edge);
            if (squared <= 1.0e-18) continue;
            const double weight = 1.0 / squared;
            const double component[3] = {edge.x, edge.y, edge.z};
            for (unsigned row = 0; row < 3U; ++row)
                for (unsigned column = 0; column < 3U; ++column)
                    covariance.m[row][column] += weight * component[row] * component[column];
            accumulated += work.relative[bond] / std::sqrt(squared);
            ++live;
        }
        if (live < 3U) continue;
        const auto inverse = covariance.inverse(1.0e-16);
        if (!inverse) continue;
        double frobenius = 0.0;
        for (unsigned row = 0; row < 3U; ++row)
            for (unsigned column = 0; column < 3U; ++column)
                frobenius += inverse->m[row][column] * inverse->m[row][column];
        const double gradient_bound = accumulated * std::sqrt(frobenius);
        work.node_gradient[node] = gradient_bound;
        work.node_bound[node] = gradient_bound + 0.5 * gradient_bound * gradient_bound;
    }

    for (std::size_t bond = 0; bond < bonds; ++bond) {
        if (!matter.bonds[bond].alive) continue;
        const BondRest &rest = matter.asset->bonds[bond];
        const double rest_length = library.gradients()[bond].rest_length_m;
        double own = work.relative[bond] / std::max(1.0e-12, rest_length);
        if (work.axial[bond] < rest_length) {
            // |sqrt((L+a)^2 + W^2) - L| <= |a| + W^2 / (2 (L - |a|))
            const double tighter = (work.axial[bond] +
                                    work.relative[bond] * work.relative[bond] /
                                        (2.0 * (rest_length - work.axial[bond]))) /
                                   rest_length;
            own = std::min(own, tighter);
        }
        work.criterion[bond] = std::max({own, work.node_bound[rest.node_a], work.node_bound[rest.node_b]});
    }
}

namespace {

struct ContactCandidate {
    std::uint32_t node{};
    Vec3 reference{};
};

} // namespace

CascadeResult runCrackCascade(ActiveMatter &matter, const ImpulseLibrary &library, Ball &ball,
                              const CascadeSettings &settings) {
    const auto total_start = Clock::now();
    CascadeResult result;
    const std::size_t modes = library.modes();
    const std::size_t dofs = library.dofs();
    const std::size_t nodes = matter.nodes.size();
    const std::size_t bonds = library.bondCount();
    const double dt = settings.sample_dt_s;
    const auto steps = static_cast<std::uint32_t>(std::llround(std::ceil(settings.window_s / dt)));

    Propagator propagator;
    propagator.build(library, dt, settings.damping_ratio);

    // ---- the cells the ball can reach in this window ------------------------
    const Ball initial_ball = ball;
    const double travel = std::abs(initial_ball.velocity_m_s.y) * settings.window_s +
                          0.5 * std::abs(settings.gravity_m_s2.y) * settings.window_s * settings.window_s;
    // The ball travels downward, so its horizontal reach is its own footprint
    // plus whatever the cells move sideways; two cells is a wide margin for a
    // displacement field that stays micrometres wide, and the largest node
    // displacement actually seen is reported so the margin can be checked.
    const double reach = initial_ball.contact_radius_m + 2.0 * settings.cell_m;
    std::vector<ContactCandidate> candidates;
    for (std::uint32_t node = 0; node < nodes; ++node) {
        bool any_free = false;
        for (unsigned axis = 0; axis < 3U; ++axis)
            any_free = any_free || library.freeDofOf()[3U * node + axis] != kFixedDof;
        if (!any_free) continue;
        const Vec3 rest = matter.reference_positions_world_m[node];
        const double dx = rest.x - initial_ball.center_m.x;
        const double dz = rest.z - initial_ball.center_m.z;
        if (dx * dx + dz * dz > reach * reach) continue;
        candidates.push_back({node, rest});
    }

    // ---- stage 1: contact ---------------------------------------------------
    const auto contact_start = Clock::now();
    std::vector<double> q(modes, 0.0), qdot(modes, 0.0);
    std::vector<ImpulseEvent> events;
    std::vector<Vec3> ball_track;
    ball_track.reserve(steps + 1U);
    Envelope envelope;
    envelope.reset(modes);
    Vec3 delivered{};
    double delivered_magnitude = 0.0;
    double largest_displacement = 0.0;
    std::vector<std::uint8_t> touched(nodes, 0U);
    double maximum_penetration = 0.0;
    double contact_end_s = 0.0;
    const Vec3 axis_direction = initial_ball.velocity_m_s * (1.0 / std::max(1.0e-12, length(initial_ball.velocity_m_s)));

    if (settings.contact == ContactModel::SingleImpulse) {
        // The plate's whole free mass takes part; the impulse is delivered to
        // the cells the ball's footprint covers at half a cell of penetration,
        // each along its own outward sphere normal, weighted by cell mass.
        double free_mass = 0.0;
        for (std::uint32_t node = 0; node < nodes; ++node) {
            bool any_free = false;
            for (unsigned axis = 0; axis < 3U; ++axis)
                any_free = any_free || library.freeDofOf()[3U * node + axis] != kFixedDof;
            if (any_free) free_mass += matter.nodes[node].mass_kg;
        }
        const double speed = length(initial_ball.velocity_m_s);
        const double total = (1.0 + settings.restitution) * initial_ball.mass_kg * free_mass * speed /
                             std::max(1.0e-12, initial_ball.mass_kg + free_mass);
        const Vec3 sunk = initial_ball.center_m + initial_ball.velocity_m_s *
                          (0.5 * settings.cell_m / std::max(1.0e-12, speed));
        std::vector<std::pair<std::uint32_t, Vec3>> patch;
        double axial_weight = 0.0;
        for (const ContactCandidate &candidate : candidates) {
            const Vec3 offset = candidate.reference - sunk;
            const double distance = length(offset);
            if (distance >= initial_ball.contact_radius_m || distance <= 1.0e-9) continue;
            const Vec3 normal = offset * (1.0 / distance);
            patch.emplace_back(candidate.node, normal);
            axial_weight += matter.nodes[candidate.node].mass_kg * std::max(0.0, dot(normal, axis_direction));
        }
        for (const auto &[node, normal] : patch) {
            const double weight = matter.nodes[node].mass_kg * total / std::max(1.0e-12, axial_weight);
            const Vec3 impulse = normal * weight;
            library.addNodeImpulse(qdot, node, impulse);
            events.push_back({0U, node, impulse});
            delivered += impulse;
            delivered_magnitude += weight;
            touched[node] = 1U;
        }
        ball.velocity_m_s = initial_ball.velocity_m_s - delivered * (1.0 / initial_ball.mass_kg);
        contact_end_s = 0.0;
        envelope.observe(library, q, qdot, 0.0);
        // Ball flies ballistically from here; the plate no longer feels it.
        Vec3 centre = initial_ball.center_m;
        Vec3 velocity = ball.velocity_m_s;
        for (std::uint32_t step = 0; step <= steps; ++step) {
            ball_track.push_back(centre);
            centre += velocity * dt + settings.gravity_m_s2 * (0.5 * dt * dt);
            velocity += settings.gravity_m_s2 * dt;
        }
        ball.center_m = centre;
        ball.velocity_m_s = velocity;
    } else {
        Vec3 centre = initial_ball.center_m;
        Vec3 velocity = initial_ball.velocity_m_s;
        std::vector<Vec3> position(candidates.size()), rate(candidates.size());
        const double margin = 2.0 * settings.cell_m;
        std::vector<std::uint32_t> engaged;
        std::vector<Vec3> normal;
        std::vector<double> lambda, approach;
        std::uint32_t quiet_steps = 0;
        ball_track.push_back(centre);
        envelope.observe(library, q, qdot, 0.0);
        for (std::uint32_t step = 1; step <= steps; ++step) {
            propagator.advance(q, qdot);
            centre += velocity * dt + settings.gravity_m_s2 * (0.5 * dt * dt);
            velocity += settings.gravity_m_s2 * dt;
            const double time = static_cast<double>(step) * dt;

            engaged.clear();
            normal.clear();
            approach.clear();
            for (std::size_t index = 0; index < candidates.size(); ++index) {
                const std::uint32_t node = candidates[index].node;
                // Skip the modal evaluation for a cell whose rest position is
                // further from the ball than the contact radius plus a margin
                // on the displacement field; `margin` is checked against the
                // largest displacement actually seen and reported.
                const Vec3 rest_offset = candidates[index].reference - centre;
                if (lengthSquared(rest_offset) > (initial_ball.contact_radius_m + margin) *
                                                 (initial_ball.contact_radius_m + margin))
                    continue;
                const Vec3 displacement = library.nodeDisplacement(q, node);
                largest_displacement = std::max(largest_displacement, length(displacement));
                position[index] = candidates[index].reference + displacement;
                const Vec3 offset = position[index] - centre;
                const double distance = length(offset);
                if (distance >= initial_ball.contact_radius_m || distance <= 1.0e-12) continue;
                rate[index] = library.nodeDisplacement(qdot, node);
                const Vec3 direction = offset * (1.0 / distance);
                const double penetration = initial_ball.contact_radius_m - distance;
                maximum_penetration = std::max(maximum_penetration, penetration);
                const double closing = dot(rate[index] - velocity, direction);
                const double target = settings.penetration_recovery * penetration / dt;
                if (closing >= target) continue;
                engaged.push_back(static_cast<std::uint32_t>(index));
                normal.push_back(direction);
                approach.push_back(closing - target);
            }
            if (engaged.empty()) {
                ball_track.push_back(centre);
                envelope.observe(library, q, qdot, time);
                if (contact_end_s > 0.0 && ++quiet_steps > 64U &&
                    (velocity.y > 0.0 || centre.y < ball_track.front().y - travel)) {
                    for (std::uint32_t rest_step = step + 1U; rest_step <= steps; ++rest_step) {
                        centre += velocity * dt + settings.gravity_m_s2 * (0.5 * dt * dt);
                        velocity += settings.gravity_m_s2 * dt;
                        ball_track.push_back(centre);
                    }
                    break;
                }
                continue;
            }
            quiet_steps = 0;
            // Projected Gauss-Seidel. The mass matrix is diagonal, so the only
            // coupling between two contacting cells is through the ball.
            lambda.assign(engaged.size(), 0.0);
            const double inverse_ball = 1.0 / initial_ball.mass_kg;
            Vec3 ball_change{};
            for (unsigned sweep = 0; sweep < settings.contact_sweeps; ++sweep) {
                double movement = 0.0;
                for (std::size_t entry = 0; entry < engaged.size(); ++entry) {
                    const std::uint32_t index = engaged[entry];
                    const double inverse_mass = 1.0 / matter.nodes[candidates[index].node].mass_kg;
                    const double diagonal = inverse_mass + inverse_ball;
                    const double current = approach[entry] + lambda[entry] * inverse_mass -
                                           dot(ball_change, normal[entry]);
                    const double delta = -current / diagonal;
                    const double updated = std::max(0.0, lambda[entry] + delta);
                    const double applied = updated - lambda[entry];
                    if (applied != 0.0) {
                        ball_change -= normal[entry] * (applied * inverse_ball);
                        lambda[entry] = updated;
                        movement = std::max(movement, std::abs(applied));
                    }
                }
                if (movement <= 1.0e-14) break;
            }
            for (std::size_t entry = 0; entry < engaged.size(); ++entry) {
                if (lambda[entry] <= 0.0) continue;
                const std::uint32_t node = candidates[engaged[entry]].node;
                const Vec3 impulse = normal[entry] * lambda[entry];
                library.addNodeImpulse(qdot, node, impulse);
                events.push_back({step, node, impulse});
                delivered += impulse;
                delivered_magnitude += lambda[entry];
                touched[node] = 1U;
            }
            velocity += ball_change;
            contact_end_s = time;
            ball_track.push_back(centre);
            envelope.observe(library, q, qdot, time);
        }
        ball.center_m = centre;
        ball.velocity_m_s = velocity;
    }
    result.contact.model = settings.contact == ContactModel::SingleImpulse
        ? "single impulse at t=0 over the ball's footprint, inelastic two-mass momentum transfer"
        : "frictionless normal contact resolved once per substep against the intact plate "
          "(diagonal-mass impulse response, projected Gauss-Seidel, penetration recovered per substep)";
    result.contact.impulse_n_s = length(delivered);
    result.contact.axial_impulse_n_s = std::abs(dot(delivered, axis_direction));
    result.contact.total_impulse_magnitude_n_s = delivered_magnitude;
    result.contact.events = events.size();
    result.contact.duration_s = contact_end_s;
    result.contact.maximum_penetration_m = maximum_penetration;
    result.contact.largest_node_displacement_m = largest_displacement;
    result.contact.ball_speed_end_m_s = length(ball.velocity_m_s);
    result.contact.contact_nodes = static_cast<std::size_t>(std::count(touched.begin(), touched.end(), 1U));
    result.contact.wall_s = since(contact_start);
    result.timings.contact_s = result.contact.wall_s;

    // ---- stage 2: the screen ------------------------------------------------
    const auto screen_start = Clock::now();
    StrainBounds work;
    std::vector<double> amplitude_bound;
    double earliest = -1.0;
    const unsigned grid = std::max(1U, settings.screen_grid);
    std::vector<std::uint8_t> candidate_bond(bonds, 0U);
    for (unsigned point = 1; point <= grid; ++point) {
        const double time = settings.window_s * static_cast<double>(point) / grid;
        envelope.bound(library, time, amplitude_bound);
        boundCriterionStrain(matter, library, amplitude_bound, work);
        bool any = false;
        for (std::size_t bond = 0; bond < bonds; ++bond) {
            if (!matter.bonds[bond].alive) continue;
            if (work.criterion[bond] >= library.gradients()[bond].break_strain) {
                any = true;
                candidate_bond[bond] = 1U;
            }
        }
        if (any && earliest < 0.0) earliest = settings.window_s * static_cast<double>(point - 1) / grid;
    }
    result.screen.bonds_screened = bonds;
    double largest_ratio = 0.0;
    std::size_t candidate_count = 0;
    for (std::size_t bond = 0; bond < bonds; ++bond) {
        if (!matter.bonds[bond].alive) continue;
        const double threshold = library.gradients()[bond].break_strain;
        if (threshold > 0.0) largest_ratio = std::max(largest_ratio, work.criterion[bond] / threshold);
        candidate_count += candidate_bond[bond];
    }
    result.screen.candidate_bonds = candidate_count;
    result.screen.largest_bound_ratio = largest_ratio;
    result.screen.anything_can_break = candidate_count > 0;
    result.screen.earliest_possible_failure_s = earliest;
    result.screen.wall_s = since(screen_start);
    result.timings.screen_s = result.screen.wall_s;

    // ---- stage 3: the cascade ----------------------------------------------
    Woodbury woodbury(library);
    std::vector<double> intact(dofs, 0.0), field(dofs, 0.0), rate_field(dofs, 0.0);
    std::vector<std::uint32_t> component(nodes, 0U);
    std::vector<std::uint32_t> removed;
    double last_failure = -1.0;
    double last_frame = -1.0;
    std::size_t event_cursor = 0;
    std::fill(q.begin(), q.end(), 0.0);
    std::fill(qdot.begin(), qdot.end(), 0.0);

    const auto writeField = [&](double time_s, bool with_correction) {
        const auto field_start = Clock::now();
        library.displacement(q, intact);
        field = intact;
        double largest = 0.0;
        if (with_correction && woodbury.size() > 0) {
            const auto woodbury_start = Clock::now();
            largest = woodbury.correct(intact, field);
            result.timings.woodbury_s += since(woodbury_start);
        }
        for (std::uint32_t node = 0; node < nodes; ++node) {
            const Vec3 displacement = library.nodeValue(field, node);
            matter.nodes[node].position_world_m = matter.reference_positions_world_m[node] + displacement;
        }
        result.timings.field_s += since(field_start);
        (void)time_s;
        return largest;
    };
    const auto writeVelocity = [&]() {
        library.displacement(qdot, rate_field);
        if (woodbury.size() > 0) {
            std::vector<double> corrected = rate_field;
            woodbury.correct(rate_field, corrected);
            rate_field = corrected;
        }
        for (std::uint32_t node = 0; node < nodes; ++node)
            matter.nodes[node].velocity_m_s = library.nodeValue(rate_field, node);
    };
    const auto labelComponents = [&]() {
        const auto components = findConnectedComponents(matter);
        for (const auto &entry : components)
            for (const std::uint32_t node : entry.node_indices) component[node] = entry.id;
        return components.size();
    };
    const auto capture = [&](double time_s, std::size_t broken) {
        if (result.frames.size() >= settings.maximum_frames) return;
        const auto frame_start = Clock::now();
        CascadeFrame frame;
        frame.time_s = time_s;
        frame.positions.resize(nodes);
        for (std::uint32_t node = 0; node < nodes; ++node) frame.positions[node] = matter.nodes[node].position_world_m;
        frame.component = component;
        const std::uint32_t index = std::min<std::uint32_t>(
            static_cast<std::uint32_t>(ball_track.size() ? ball_track.size() - 1U : 0U),
            static_cast<std::uint32_t>(std::llround(time_s / dt)));
        frame.ball_center = ball_track.empty() ? ball.center_m : ball_track[index];
        frame.bond_alive.resize(bonds);
        frame.bond_damage.resize(bonds);
        for (std::size_t bond = 0; bond < bonds; ++bond) {
            frame.bond_alive[bond] = matter.bonds[bond].alive ? 1U : 0U;
            frame.bond_damage[bond] = static_cast<float>(matter.bonds[bond].damage);
        }
        frame.broken = broken;
        result.frames.push_back(std::move(frame));
        result.timings.frames_s += since(frame_start);
    };

    labelComponents();
    const double start_time = result.screen.anything_can_break ? std::max(0.0, earliest) : settings.window_s;
    std::size_t broken_total = 0;
    double stop_time = settings.window_s;
    resetBondStrainPeaks(matter);
    for (std::uint32_t step = 1; step <= steps; ++step) {
        propagator.advance(q, qdot);
        while (event_cursor < events.size() && events[event_cursor].step == step) {
            library.addNodeImpulse(qdot, events[event_cursor].node, events[event_cursor].impulse);
            ++event_cursor;
        }
        const double time = static_cast<double>(step) * dt;
        if (time < start_time) {
            ++result.skipped_samples;
            continue;
        }
        ++result.samples;
        const double correction = writeField(time, true);
        const auto criterion_start = Clock::now();
        resetBondStrainPeaks(matter);
        accumulateBondStrainPeaks(matter);
        removed.clear();
        const BondFailureSummary summary = applyBondFailure(matter, &removed);
        result.timings.criterion_s += since(criterion_start);
        result.maximum_tensile_stretch = std::max(result.maximum_tensile_stretch, summary.maximum_tensile_stretch);
        result.maximum_compressive_strain = std::max(result.maximum_compressive_strain, summary.maximum_compressive_strain);
        result.maximum_shear_strain = std::max(result.maximum_shear_strain, summary.maximum_shear_strain);
        if (!removed.empty()) {
            const auto update_start = Clock::now();
            for (const std::uint32_t bond : removed) woodbury.add(bond, settings.schur_floor);
            const double update_wall = since(update_start);
            result.timings.woodbury_s += update_wall;
            broken_total += removed.size();
            result.removed_energy_j += summary.removed_elastic_energy_j;
            const std::size_t components_after = labelComponents();
            CascadeRound round;
            round.time_s = time;
            round.bonds = removed;
            round.removed_energy_j = summary.removed_elastic_energy_j;
            round.released_total = woodbury.size();
            round.components_after = components_after;
            round.update_wall_s = update_wall;
            round.largest_correction_m = correction;
            round.singular_releases = woodbury.singular();
            result.rounds.push_back(std::move(round));
            if (result.first_failure_time_s < 0.0) {
                result.first_failure_time_s = time;
                result.first_failure_bonds = removed;
            }
            last_failure = time;
            capture(time, broken_total);
            last_frame = time;
            if (result.rounds.size() >= settings.maximum_rounds) { stop_time = time; break; }
        } else if (time - last_frame >= settings.frame_interval_s) {
            capture(time, broken_total);
            last_frame = time;
        }
        stop_time = time;
        if (last_failure >= 0.0 && time - last_failure > settings.quiet_s && time > contact_end_s) break;
    }
    if (result.samples == 0) {
        // Nothing could break: one field evaluation puts the plate where the
        // window leaves it and the whole window costs one matrix-vector product.
        std::fill(q.begin(), q.end(), 0.0);
        std::fill(qdot.begin(), qdot.end(), 0.0);
        for (const ImpulseEvent &event : events) library.addNodeImpulse(qdot, event.node, event.impulse);
        Propagator whole;
        whole.build(library, settings.window_s, settings.damping_ratio);
        whole.advance(q, qdot);
        writeField(settings.window_s, false);
        stop_time = settings.window_s;
    }
    writeVelocity();
    result.components = labelComponents();
    capture(stop_time, broken_total);

    const auto components = findConnectedComponents(matter);
    result.largest_component_cells = components.empty() ? 0 : components.front().node_indices.size();
    result.largest_component_mass_kg = 0.0;
    if (!components.empty())
        for (const std::uint32_t node : components.front().node_indices)
            result.largest_component_mass_kg += matter.nodes[node].mass_kg;
    result.broken_bonds = broken_total;
    result.last_failure_time_s = last_failure;
    result.simulated_s = stop_time;
    result.singular_releases = woodbury.singular();
    result.ball = ball;
    result.timings.sample_s = result.timings.field_s + result.timings.criterion_s + result.timings.woodbury_s;
    result.timings.total_s = since(total_start);
    return result;
}

} // namespace banjo::algo1
