#include "material/NetworkMaterial.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace banjo;

namespace {
void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

void near(double a, double b, double tolerance, const char *message) {
    check(std::isfinite(a) && std::abs(a - b) <= tolerance, message);
}

void rejects(const std::function<void()> &operation) {
    bool rejected = false;
    try { operation(); } catch (const std::invalid_argument &) { rejected = true; }
    check(rejected, "invalid network input was accepted");
}

NetworkMaterial sample() {
    return {"directional-test", 700.0, {10.0e9, 2.0e9, 1.0e9},
            {50.0e6, 10.0e6, 5.0e6}, {30000.0, 200.0, 100.0},
            .04, .4, 0.0, 0.0, true};
}
}

int main() {
    try {
        const auto material = sample();
        const double area = .01;
        const double length = .1;
        const auto x = directionalNetworkParameters(material, {1, 0, 0}, area, length);
        near(x.stiffness_n_m, 1.0e9, 1e-3, "axis-x stiffness uses E A / L");
        near(x.strength_n, 500000.0, 1e-9, "axis-x strength uses area");
        near(x.fracture_work_j, 300.0, 1e-12, "axis-x fracture work uses area");

        const auto diagonal = directionalNetworkParameters(material, normalized({1, 1, 0}), area, length);
        const double expected_modulus = 1.0 / (.5 / 10.0e9 + .5 / 2.0e9);
        near(diagonal.stiffness_n_m, expected_modulus * area / length, 1e-6,
             "diagonal stiffness uses harmonic directional weighting");
        check(diagonal.stiffness_n_m < x.stiffness_n_m, "rotated direction changes stiffness");

        const auto params = directionalNetworkParameters(material, {1, 0, 0}, area, length);
        NetworkBondHistory history;
        auto elastic = advanceNetworkBond(material, params, history, .5 * params.strength_n / params.stiffness_n_m, length);
        check(elastic.history.damage == 0.0, "subcritical opening damages bond");
        near(elastic.elastic_energy_j, .5 * params.stiffness_n_m *
             std::pow(.5 * params.strength_n / params.stiffness_n_m, 2), 1e-12,
             "elastic energy is recoverable");
        auto damaged = advanceNetworkBond(material, params, elastic.history,
            1.5 * (2.0 * params.fracture_work_j / params.strength_n), length);
        check(damaged.history.damage > 0.0, "supercritical opening accumulates damage");
        const double damage_before = damaged.history.damage;
        const double d0 = params.strength_n / params.stiffness_n_m;
        const double df = 2.0 * params.fracture_work_j / params.strength_n;
        const double midpoint = .5 * (d0 + df);
        auto midpoint_state = advanceNetworkBond(material, params, {}, midpoint, length);
        const double expected_damage = 1.0 - d0 * (df - midpoint) / (midpoint * (df - d0));
        near(midpoint_state.history.damage, expected_damage, 1e-12,
             "midpoint damage is secant damage for bilinear traction");
        near(midpoint_state.stiffness_n_m, params.stiffness_n_m * (1.0 - expected_damage), 1e-6,
             "tension stiffness is softened by secant damage");
        auto closed = advanceNetworkBond(material, params, damaged.history, 0.0, length);
        near(closed.history.damage, damage_before, 0.0, "unloading does not heal damage");
        near(closed.fracture_increment_j, 0.0, 0.0, "unloading does not dissipate fracture work twice");
        auto reopened = advanceNetworkBond(material, params, closed.history,
            1.5 * (2.0 * params.fracture_work_j / params.strength_n), length);
        near(reopened.fracture_increment_j, 0.0, 0.0, "reopening below prior maximum does not damage twice");

        auto complete = advanceNetworkBond(material, params, reopened.history,
            2.0 * params.fracture_work_j / params.strength_n, length);
        check(complete.failed, "opening at the final cohesive displacement fails bond");
        near(complete.history.fracture_dissipation_j, params.fracture_work_j,
             params.fracture_work_j * 1e-12, "fracture dissipation equals Gc times area");

        double tensile_work = 0.0;
        NetworkBondHistory work_history;
        double previous_force = 0.0;
        constexpr unsigned work_steps = 4000;
        const double work_failure = 2.0 * params.fracture_work_j / params.strength_n;
        for (unsigned step = 1; step <= work_steps; ++step) {
            const double opening = work_failure * static_cast<double>(step) / work_steps;
            const auto update = advanceNetworkBond(material, params, work_history, opening, length);
            const double force = update.stiffness_n_m * opening;
            const double delta = work_failure / work_steps;
            tensile_work += .5 * (previous_force + force) * delta;
            previous_force = force;
            work_history = update.history;
        }
        near(tensile_work, params.fracture_work_j, params.fracture_work_j * 2e-4,
             "numerical tensile force work equals declared fracture work");
        auto compression = advanceNetworkBond(material, params, {}, -.5 * length, length);
        near(compression.stiffness_n_m, params.stiffness_n_m, 0.0,
             "compression retains base stiffness");
        const double compression_energy = .5 * params.stiffness_n_m * .25 * length * length;
        near(compression.elastic_energy_j, compression_energy, compression_energy * 1e-12,
             "compression energy remains recoverable");

        NetworkMaterial brittle = sample();
        brittle.failure_law = NetworkFailureLaw::Brittle;
        brittle.fracture_energy_j_m2 = {1.0, 1.0, 1.0};
        const auto brittle_params = directionalNetworkParameters(brittle, {1, 0, 0}, area, length);
        auto below = advanceNetworkBond(brittle, brittle_params, {},
            .5 * brittle_params.strength_n / brittle_params.stiffness_n_m, length);
        check(!below.failed, "brittle threshold does not fail below strength");
        auto brittle_compression = advanceNetworkBond(brittle, brittle_params, below.history,
            -.5 * brittle_params.strength_n / brittle_params.stiffness_n_m, length);
        check(!brittle_compression.failed, "brittle threshold does not fail in compression");
        const double brittle_opening = std::max(
            brittle_params.strength_n / brittle_params.stiffness_n_m,
            std::sqrt(2.0 * brittle_params.fracture_work_j / brittle_params.stiffness_n_m));
        auto brittle_fail = advanceNetworkBond(brittle, brittle_params, below.history,
            brittle_opening, length);
        check(brittle_fail.failed, "brittle threshold fails when strength and work gates pass");
        near(brittle_fail.history.fracture_dissipation_j + brittle_fail.history.unreleased_energy_j,
             .5 * brittle_params.stiffness_n_m * brittle_opening * brittle_opening,
             brittle_params.fracture_work_j * 1e-12,
             "brittle removed energy is split between Gc and unresolved release");
        auto brittle_again = advanceNetworkBond(brittle, brittle_params, brittle_fail.history,
            brittle_opening * 1.1, length);
        near(brittle_again.fracture_increment_j, 0.0, 0.0, "brittle fracture is not charged twice");
        auto brittle_closed = advanceNetworkBond(brittle, brittle_params, brittle_fail.history, -.001, length);
        check(brittle_closed.failed && brittle_closed.stiffness_n_m == 0,
              "failed links stay removed on closure; contact owns compression");
        brittle.fracture_energy_j_m2 = {1e8, 1e8, 1e8};
        const auto energy_limited = directionalNetworkParameters(brittle, {1,0,0}, area, length);
        auto strength_only = advanceNetworkBond(brittle, energy_limited, {},
            2 * energy_limited.strength_n / energy_limited.stiffness_n_m, length);
        check(!strength_only.failed && strength_only.history.damage == 0,
              "brittle law does not enter cohesive softening when work gate fails");

        NetworkMaterial plastic = material;
        plastic.yield_strength_pa = 10.0e6;
        plastic.fracture_enabled = false;
        const auto plastic_params = directionalNetworkParameters(plastic, {1, 0, 0}, area, length);
        const double yield_extension = plastic_params.yield_force_n / plastic_params.stiffness_n_m;
        auto yielded = advanceNetworkBond(plastic, plastic_params, {}, 3.0 * yield_extension, length);
        check(yielded.plastic_increment_j > 0.0, "yielding dissipates plastic work");
        check(yielded.history.plastic_extension_m > 0.0, "yielding leaves permanent extension");
        auto plastic_unload = advanceNetworkBond(plastic, plastic_params, yielded.history,
            yielded.history.plastic_extension_m, length);
        near(plastic_unload.elastic_energy_j, 0.0, 1e-12, "plastic permanent set unloads to zero elastic energy");
        near(yielded.history.plastic_dissipation_j, yielded.plastic_increment_j, 1e-12,
             "plastic work is retained in history");

        auto bad = material;
        bad.young_modulus_pa.x = std::numeric_limits<double>::quiet_NaN();
        rejects([&] { validateNetworkMaterial(bad); });
        bad = material; bad.hardening_ratio = .1;
        rejects([&] { validateNetworkMaterial(bad); });
        bad = material; bad.yield_strength_pa = 1.0e6;
        rejects([&] { validateNetworkMaterial(bad); });
        rejects([&] { (void)directionalNetworkParameters(material, {2, 0, 0}, area, length); });
        bad = material; bad.fracture_energy_j_m2.x = .001;
        const auto weak_work = directionalNetworkParameters(bad, {1, 0, 0}, area, length);
        rejects([&] { (void)advanceNetworkBond(bad, weak_work, {},
            weak_work.strength_n / weak_work.stiffness_n_m, length); });
        rejects([&] { (void)advanceNetworkBond(material, params, {},
            std::numeric_limits<double>::quiet_NaN(), length); });

        std::cout << "[PASS] directional network material law, damage, plasticity and bounds\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
