#include "thermal/EnthalpyLaw.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace {
using namespace banjo::thermal;
struct Failure : std::runtime_error { using std::runtime_error::runtime_error; };
void require(bool ok, std::string_view message) { if (!ok) throw Failure(std::string(message)); }
void near(double a, double b, double tolerance, std::string_view message) {
    if (std::abs(a - b) > tolerance) throw Failure(std::string(message));
}

const EnthalpyMaterial ice{2100.0, 4200.0, 273.15, 334000.0};

double temperature(const EnthalpyMaterial &material, double enthalpy) {
    return stateFromEnthalpy(material, enthalpy).temperature_k;
}

EnthalpyPairResult bisectionOracle(const EnthalpyMaterial &first_material,
    const EnthalpyLump &first, const EnthalpyMaterial &second_material,
    const EnthalpyLump &second, double conductance, double dt) {
    EnthalpyPairResult result{first, second, 0.0};
    if (conductance == 0.0 || dt == 0.0 ||
        temperature(first_material, first.enthalpy_j_kg) ==
            temperature(second_material, second.enthalpy_j_kg))
        return result;
    const double scale = conductance * dt;
    const double first_energy = first.mass_kg * first.enthalpy_j_kg;
    const double second_energy = second.mass_kg * second.enthalpy_j_kg;
    double lo = -first_energy;
    double hi = second_energy;
    auto residual = [&](double q) {
        const double first_enthalpy = (first_energy + q) / first.mass_kg;
        const double second_enthalpy = (second_energy - q) / second.mass_kg;
        return q / scale - (temperature(second_material, second_enthalpy) -
                            temperature(first_material, first_enthalpy));
    };
    for (unsigned iteration = 0; iteration < 128; ++iteration) {
        const double mid = lo * 0.5 + hi * 0.5;
        if (residual(mid) > 0.0) hi = mid; else lo = mid;
    }
    const double q = lo * 0.5 + hi * 0.5;
    result.first.enthalpy_j_kg += q / first.mass_kg;
    result.second.enthalpy_j_kg -= q / second.mass_kg;
    result.energy_to_first_j = q;
    return result;
}

void iceWarmsMeltsAndRefreezes() {
    const double below = enthalpyFromTemperaturePhase(ice, 263.15, 0.0);
    const auto cold = stateFromEnthalpy(ice, below);
    near(cold.temperature_k, 263.15, 1e-12, "ice sensible temperature");
    require(cold.liquid_fraction == 0.0, "cold ice is solid");

    const double half = enthalpyFromTemperaturePhase(ice, 273.15, .5);
    const auto meltedHalf = stateFromEnthalpy(ice, half);
    near(meltedHalf.temperature_k, 273.15, 1e-12, "melt plateau temperature");
    near(meltedHalf.liquid_fraction, .5, 1e-12, "melt plateau fraction");

    const double liquid = enthalpyFromTemperaturePhase(ice, 283.15, 1.0);
    const auto warm = stateFromEnthalpy(ice, liquid);
    near(warm.temperature_k, 283.15, 1e-12, "liquid temperature");
    require(warm.liquid_fraction == 1.0, "warm water is liquid");

    const auto refrozen = stateFromEnthalpy(ice, enthalpyFromTemperaturePhase(ice, 273.15, .1));
    near(refrozen.temperature_k, 273.15, 1e-12, "refreezing remains isothermal");
    near(refrozen.liquid_fraction, .1, 1e-12, "refreezing fraction is reversible");
}

void constantCpIdentityAndPhaseBounds() {
    const EnthalpyMaterial water{4180.0, 4180.0, 273.15, 0.0};
    const auto cold = stateFromEnthalpy(water, enthalpyFromTemperaturePhase(water, 250.0, 0.0));
    const auto hot = stateFromEnthalpy(water, enthalpyFromTemperaturePhase(water, 300.0, 1.0));
    near(cold.temperature_k, 250.0, 1e-12, "constant cp cold identity");
    near(hot.temperature_k, 300.0, 1e-12, "constant cp hot identity");
    require(cold.liquid_fraction == 0.0 && hot.liquid_fraction == 1.0,
            "zero latent heat has threshold phase identity");
}

void conductionIsConservativeAndBackwardEuler() {
    const EnthalpyMaterial a{1000.0, 1000.0, 300.0, 0.0};
    const EnthalpyMaterial b{2000.0, 2000.0, 300.0, 0.0};
    const EnthalpyLump first{2.0, 400000.0};
    const EnthalpyLump second{1.0, 100000.0};
    constexpr double conductance = 5.0;
    constexpr double dt = .2;
    const auto result = exchangePairBackwardEuler(a, first, b, second, conductance, dt);
    near(result.first.mass_kg * result.first.enthalpy_j_kg +
         result.second.mass_kg * result.second.enthalpy_j_kg,
         first.mass_kg * first.enthalpy_j_kg + second.mass_kg * second.enthalpy_j_kg,
         1e-8, "pair conduction conserves energy");
    const double c1 = first.mass_kg * a.solid_heat_capacity_j_kg_k;
    const double c2 = second.mass_kg * b.solid_heat_capacity_j_kg_k;
    const double alpha = conductance * dt;
    const double expectedQ = alpha * (second.enthalpy_j_kg / b.solid_heat_capacity_j_kg_k -
                                      first.enthalpy_j_kg / a.solid_heat_capacity_j_kg_k) /
                             (1.0 + alpha * (1.0 / c1 + 1.0 / c2));
    near(result.energy_to_first_j, expectedQ, 1e-8, "backward Euler pair solve");

    const auto equal = exchangePairBackwardEuler(a, {1.0, 300000.0}, b, {1.0, 600000.0}, conductance, dt);
    require(equal.energy_to_first_j == 0.0, "equal-temperature pair has no heat flow");

    auto coarse = exchangePairBackwardEuler(a, first, b, second, conductance, .2);
    auto fineFirst = first, fineSecond = second;
    for (unsigned i = 0; i < 10; ++i) {
        const auto fineStep = exchangePairBackwardEuler(a, fineFirst, b, fineSecond, conductance, .02);
        fineFirst = fineStep.first; fineSecond = fineStep.second;
    }
    const double exactQ = (second.enthalpy_j_kg / b.solid_heat_capacity_j_kg_k -
                           first.enthalpy_j_kg / a.solid_heat_capacity_j_kg_k) /
                          (1.0 / c1 + 1.0 / c2) *
                          (1.0 - std::exp(-conductance * .2 * (1.0 / c1 + 1.0 / c2)));
    const double fineQ = fineFirst.mass_kg * (fineFirst.enthalpy_j_kg - first.enthalpy_j_kg);
    require(std::abs(fineQ - exactQ) < std::abs(coarse.energy_to_first_j - exactQ),
            "smaller backward Euler step converges toward transient solution");
}

void phasePairMeltsAndFreezesWithoutOvershoot() {
    const EnthalpyLump partly_melted{1.0,
        enthalpyFromTemperaturePhase(ice, ice.melting_temperature_k, 0.25)};
    const EnthalpyLump hot_water{1.0,
        enthalpyFromTemperaturePhase(ice, 320.0, 1.0)};
    const auto melting = exchangePairBackwardEuler(
        ice, partly_melted, ice, hot_water, 2000.0, 100.0);
    const auto melted_state = stateFromEnthalpy(ice, melting.first.enthalpy_j_kg);
    const auto cooled_state = stateFromEnthalpy(ice, melting.second.enthalpy_j_kg);
    require(melted_state.liquid_fraction > 0.25 && melted_state.liquid_fraction < 1.0,
            "finite hot lump partially melts the phase-change lump");
    near(melted_state.temperature_k, ice.melting_temperature_k, 1e-12,
         "melting remains on latent plateau");
    require(cooled_state.temperature_k >= melted_state.temperature_k,
            "implicit melting exchange does not overshoot thermal equilibrium");

    const EnthalpyLump mostly_melted{1.0,
        enthalpyFromTemperaturePhase(ice, ice.melting_temperature_k, 0.75)};
    const EnthalpyLump cold_ice{1.0,
        enthalpyFromTemperaturePhase(ice, 240.0, 0.0)};
    const auto freezing = exchangePairBackwardEuler(
        ice, mostly_melted, ice, cold_ice, 2000.0, 100.0);
    const auto frozen_state = stateFromEnthalpy(ice, freezing.first.enthalpy_j_kg);
    const auto warmed_state = stateFromEnthalpy(ice, freezing.second.enthalpy_j_kg);
    require(frozen_state.liquid_fraction < 0.75 && frozen_state.liquid_fraction > 0.0,
            "finite cold lump partially freezes the phase-change lump");
    near(frozen_state.temperature_k, ice.melting_temperature_k, 1e-12,
         "freezing remains on latent plateau");
    require(frozen_state.temperature_k >= warmed_state.temperature_k,
            "implicit freezing exchange does not overshoot thermal equilibrium");
}

void phasePairMatchesIndependentBisectionOracle() {
    const EnthalpyMaterial salt{850.0, 1250.0, 1074.0, 492000.0};
    std::mt19937_64 random(0x50484153454c4157ULL);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    std::uniform_real_distribution<double> mass_exponent(-9.0, 9.0);
    std::uniform_real_distribution<double> conductance_exponent(-4.0, 8.0);
    std::uniform_real_distribution<double> time_exponent(-6.0, 4.0);
    auto branchEnthalpy = [&](const EnthalpyMaterial &material, unsigned branch,
                              unsigned sample) {
        const double solid = material.solid_heat_capacity_j_kg_k *
                             material.melting_temperature_k;
        const double liquid = solid + material.latent_heat_j_kg;
        double u = unit(random);
        if (sample % 16 == 0) u = 0.0;
        if (sample % 16 == 1) u = 1.0;
        if (branch == 0) return solid * u;
        if (branch == 1) return solid + material.latent_heat_j_kg * u;
        return liquid + material.liquid_heat_capacity_j_kg_k * (1.0 + 800.0 * u);
    };

    for (unsigned first_branch = 0; first_branch < 3; ++first_branch) {
        for (unsigned second_branch = 0; second_branch < 3; ++second_branch) {
            for (unsigned sample = 0; sample < 48; ++sample) {
                double first_mass = std::pow(10.0, mass_exponent(random));
                double second_mass = std::pow(10.0, mass_exponent(random));
                if (sample % 12 == 0) { first_mass = 1e-9; second_mass = 1e9; }
                if (sample % 12 == 1) { first_mass = 1e9; second_mass = 1e-9; }
                const EnthalpyLump first{first_mass,
                    branchEnthalpy(ice, first_branch, sample)};
                const EnthalpyLump second{second_mass,
                    branchEnthalpy(salt, second_branch, sample + 3)};
                const double conductance = std::pow(10.0, conductance_exponent(random));
                const double dt = std::pow(10.0, time_exponent(random));
                const auto actual = exchangePairBackwardEuler(
                    ice, first, salt, second, conductance, dt);
                const auto expected = bisectionOracle(
                    ice, first, salt, second, conductance, dt);
                require(std::isfinite(actual.energy_to_first_j),
                        "piecewise-affine phase solve returns finite heat transfer");
                const double tolerance = 1e-7 + 1e-10 * std::abs(expected.energy_to_first_j);
                if (std::abs(actual.energy_to_first_j - expected.energy_to_first_j) > tolerance) {
                    std::ostringstream message;
                    message.precision(17);
                    message << "piecewise-affine phase solve matches 128-step bisection oracle"
                            << " (branches " << first_branch << ',' << second_branch
                            << ", sample " << sample << ", actual "
                            << actual.energy_to_first_j << ", oracle "
                            << expected.energy_to_first_j << ", tolerance " << tolerance
                            << ", masses " << first.mass_kg << ',' << second.mass_kg
                            << ", enthalpies " << first.enthalpy_j_kg << ','
                            << second.enthalpy_j_kg << ", conductance " << conductance
                            << ", dt " << dt << ')';
                    throw Failure(message.str());
                }
                require(actual.first.enthalpy_j_kg >= 0.0 &&
                        actual.second.enthalpy_j_kg >= 0.0,
                        "phase exchange preserves non-negative enthalpy");
                const double initial_energy =
                    first.mass_kg * first.enthalpy_j_kg +
                    second.mass_kg * second.enthalpy_j_kg;
                const double final_energy =
                    actual.first.mass_kg * actual.first.enthalpy_j_kg +
                    actual.second.mass_kg * actual.second.enthalpy_j_kg;
                const double energy_tolerance = std::max(
                    1e-12, 64.0 * std::numeric_limits<double>::epsilon() *
                               std::abs(initial_energy));
                near(final_energy, initial_energy, energy_tolerance,
                     "phase exchange conserves total energy");
                const double initial_difference =
                    temperature(salt, second.enthalpy_j_kg) -
                    temperature(ice, first.enthalpy_j_kg);
                const double final_difference =
                    temperature(salt, actual.second.enthalpy_j_kg) -
                    temperature(ice, actual.first.enthalpy_j_kg);
                require(actual.energy_to_first_j * initial_difference >= 0.0,
                        "heat follows the initial temperature difference");
                constexpr double temperature_tolerance = 1e-9;
                if (actual.energy_to_first_j > 0.0)
                    require(final_difference >= -temperature_tolerance,
                            "positive phase exchange does not overshoot equilibrium");
                if (actual.energy_to_first_j < 0.0)
                    require(final_difference <= temperature_tolerance,
                            "negative phase exchange does not overshoot equilibrium");
            }
        }
    }
}

void phasePairMatchedTimeConvergence() {
    const EnthalpyLump cold{1.0, enthalpyFromTemperaturePhase(ice, 250.0, 0.0)};
    const EnthalpyLump hot{1.0, enthalpyFromTemperaturePhase(ice, 500.0, 1.0)};
    constexpr double conductance = 10.0;
    constexpr double elapsed = 100.0;
    auto advance = [&](unsigned steps) {
        auto first = cold;
        auto second = hot;
        for (unsigned i = 0; i < steps; ++i) {
            const auto update = exchangePairBackwardEuler(
                ice, first, ice, second, conductance, elapsed / steps);
            first = update.first;
            second = update.second;
        }
        return first.mass_kg * (first.enthalpy_j_kg - cold.enthalpy_j_kg);
    };
    const double coarse = advance(10);
    const double fine = advance(100);
    const double reference = advance(10000);
    require(std::abs(fine - reference) < std::abs(coarse - reference),
            "phase exchange converges under matched-time refinement");
}

void largeDtAndBounds() {
    const EnthalpyMaterial material{1000.0, 1000.0, 300.0, 0.0};
    const EnthalpyLump hot{1.0, 800000.0}, cold{1.0, 100000.0};
    constexpr double conductance = 1.0, dt = 1e12;
    const auto result = exchangePairBackwardEuler(material, hot, material, cold, conductance, dt);
    const double capacity = material.solid_heat_capacity_j_kg_k;
    const double expectedQ = conductance * dt * (cold.enthalpy_j_kg - hot.enthalpy_j_kg) / capacity /
        (1.0 + conductance * dt * (1.0 / capacity + 1.0 / capacity));
    near(result.energy_to_first_j, expectedQ, 1e-6,
         "large backward Euler step follows its implicit equilibrium limit");
    require(result.first.enthalpy_j_kg >= 0.0 && result.second.enthalpy_j_kg >= 0.0,
            "conduction cannot create negative enthalpy");
    require(std::isfinite(result.energy_to_first_j), "large step result is finite");
}

void rejectsInvalidInputs() {
    bool rejected = false;
    try { (void)stateFromEnthalpy(ice, -1.0); } catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "negative enthalpy rejected");
    rejected = false;
    try { (void)stateFromEnthalpy(ice, std::numeric_limits<double>::quiet_NaN()); } catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "nonfinite enthalpy rejected");
    rejected = false;
    try { (void)enthalpyFromTemperaturePhase(ice, 273.15, 1.1); } catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "invalid phase fraction rejected");
    rejected = false;
    try { (void)exchangePairBackwardEuler(ice, {0.0, 1.0}, ice, {1.0, 1.0}, 1.0, .1); } catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "nonpositive mass rejected");
    rejected = false;
    try { (void)exchangePairBackwardEuler(ice, {1.0, 1.0}, ice, {1.0, 1.0}, 1.0, -1.0); } catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "negative time rejected");
    rejected = false;
    try { const EnthalpyMaterial bad{std::numeric_limits<double>::max(), 1.0, 2.0, 1.0}; validateEnthalpyMaterial(bad); }
    catch (const std::overflow_error &) { rejected = true; }
    require(rejected, "nonfinite phase threshold rejected");
    rejected = false;
    try { (void)stateFromEnthalpy({1.0e-300, 1.0e-300, 1.0, 0.0}, 1.0e308); }
    catch (const std::overflow_error &) { rejected = true; }
    require(rejected, "nonfinite derived temperature rejected");
    rejected = false;
    try { validateEnthalpyMaterial({1.0, 2.0, 273.15, 0.0}); }
    catch (const std::invalid_argument &) { rejected = true; }
    require(rejected, "zero-latent unequal capacities rejected");
}
}

int main() {
    const std::pair<std::string_view, std::function<void()>> tests[] = {
        {"ice warming/melting/refreezing", iceWarmsMeltsAndRefreezes},
        {"constant cp phase identity", constantCpIdentityAndPhaseBounds},
        {"conservative backward Euler conduction", conductionIsConservativeAndBackwardEuler},
        {"phase pair melting and freezing", phasePairMeltsAndFreezesWithoutOvershoot},
        {"phase pair bisection oracle", phasePairMatchesIndependentBisectionOracle},
        {"phase pair matched-time convergence", phasePairMatchedTimeConvergence},
        {"large dt and bounds", largeDtAndBounds},
        {"invalid inputs", rejectsInvalidInputs},
    };
    std::size_t failures = 0;
    for (const auto &[name, test] : tests) {
        try { test(); std::cout << "[PASS] " << name << '\n'; }
        catch (const std::exception &error) { ++failures; std::cerr << "[FAIL] " << name << ": " << error.what() << '\n'; }
    }
    std::cout << (std::size(tests) - failures) << '/' << std::size(tests) << " tests passed\n";
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
