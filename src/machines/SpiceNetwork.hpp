#pragma once
#include <cstddef>
#include <vector>

namespace banjo::machines {
// A reversible electrical trial, expressed as resistors and series EMFs.
// Capacitor companion states and mechanical back EMFs are supplied by Circuit;
// this function owns no accepted time, charge, heat, or mechanical state.
struct SpiceBranch {
    std::size_t a{}, b{};
    double conductance_s{}, emf_v{};
};
[[nodiscard]] std::vector<double> solveSpiceNetwork(
    std::size_t nodes, const std::vector<SpiceBranch> &branches,
    std::size_t positive, std::size_t negative, double resistance_ohm,
    double voltage_v, bool current_limited, double current_a);
[[nodiscard]] const char *spiceVersion();
}
