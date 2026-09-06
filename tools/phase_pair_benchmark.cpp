#include "thermal/EnthalpyLaw.hpp"

#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>

namespace {
using namespace banjo::thermal;

double temperatureUnchecked(const EnthalpyMaterial &material, double enthalpy) {
    const double solid = material.solid_heat_capacity_j_kg_k * material.melting_temperature_k;
    const double liquid = solid + material.latent_heat_j_kg;
    if (enthalpy < solid || material.latent_heat_j_kg == 0.0)
        return enthalpy / material.solid_heat_capacity_j_kg_k;
    if (enthalpy <= liquid) return material.melting_temperature_k;
    return material.melting_temperature_k +
           (enthalpy - liquid) / material.liquid_heat_capacity_j_kg_k;
}

double legacy64(const EnthalpyMaterial &first_material, const EnthalpyLump &first,
    const EnthalpyMaterial &second_material, const EnthalpyLump &second,
    double conductance, double dt) {
    validateEnthalpyMaterial(first_material);
    validateEnthalpyMaterial(second_material);
    validateEnthalpyLump(first);
    validateEnthalpyLump(second);
    const double scale = conductance * dt;
    const double first_energy = first.mass_kg * first.enthalpy_j_kg;
    const double second_energy = second.mass_kg * second.enthalpy_j_kg;
    double lo = -first_energy;
    double hi = second_energy;
    auto residual = [&](double q) {
        return q / scale -
            (temperatureUnchecked(second_material,
                 second.enthalpy_j_kg - q / second.mass_kg) -
             temperatureUnchecked(first_material,
                 first.enthalpy_j_kg + q / first.mass_kg));
    };
    for (unsigned iteration = 0; iteration < 64; ++iteration) {
        const double mid = lo * 0.5 + hi * 0.5;
        if (residual(mid) > 0.0) hi = mid; else lo = mid;
    }
    return lo * 0.5 + hi * 0.5;
}

struct Case {
    EnthalpyMaterial first_material;
    EnthalpyLump first;
    EnthalpyMaterial second_material;
    EnthalpyLump second;
    double conductance;
    double dt;
};
}

int main(int argc, char **argv) {
    std::uint64_t repetitions = 200000;
    if (argc == 2) repetitions = std::stoull(argv[1]);
    const EnthalpyMaterial water{2100.0, 4200.0, 273.15, 334000.0};
    const EnthalpyMaterial salt{850.0, 1250.0, 1074.0, 492000.0};
    std::mt19937_64 random(0x504841534542454eULL);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    std::vector<Case> cases;
    cases.reserve(1024);
    for (unsigned i = 0; i < 1024; ++i) {
        auto enthalpy = [&](const EnthalpyMaterial &material) {
            const double solid = material.solid_heat_capacity_j_kg_k *
                                 material.melting_temperature_k;
            const double liquid = solid + material.latent_heat_j_kg;
            switch (i % 3) {
            case 0: return solid * unit(random);
            case 1: return solid + material.latent_heat_j_kg * unit(random);
            default: return liquid + material.liquid_heat_capacity_j_kg_k *
                                      (1.0 + 600.0 * unit(random));
            }
        };
        cases.push_back({water, {std::pow(10.0, 4.0 * unit(random) - 2.0), enthalpy(water)},
                         salt, {std::pow(10.0, 4.0 * unit(random) - 2.0), enthalpy(salt)},
                         std::pow(10.0, 6.0 * unit(random) - 2.0),
                         std::pow(10.0, 4.0 * unit(random) - 3.0)});
    }

    auto measure = [&](auto solve) {
        volatile double checksum = 0.0;
        const auto start = std::chrono::steady_clock::now();
        for (std::uint64_t i = 0; i < repetitions; ++i) {
            const auto &test = cases[static_cast<std::size_t>(i % cases.size())];
            checksum = checksum + solve(test);
        }
        const auto elapsed = std::chrono::steady_clock::now() - start;
        return std::pair{std::chrono::duration<double>(elapsed).count(), checksum};
    };
    const auto direct = measure([](const Case &test) {
        return exchangePairBackwardEuler(test.first_material, test.first,
            test.second_material, test.second, test.conductance, test.dt).energy_to_first_j;
    });
    const auto legacy = measure([](const Case &test) {
        return legacy64(test.first_material, test.first, test.second_material,
            test.second, test.conductance, test.dt);
    });
    std::cout << "cases=" << cases.size() << " repetitions=" << repetitions << '\n'
              << "piecewise_seconds=" << direct.first << " checksum=" << direct.second << '\n'
              << "legacy64_seconds=" << legacy.first << " checksum=" << legacy.second << '\n'
              << "speedup=" << legacy.first / direct.first << "x\n";
}
