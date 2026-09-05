#include "thermal/EnthalpyLaw.hpp"

#include <cmath>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <iterator>
#include <limits>
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
