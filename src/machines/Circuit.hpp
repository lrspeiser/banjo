#pragma once

// Bounded, quasi-static DC networks. Construction and collision geometry stay
// with the product; this value owns only electrical and lumped thermal state.
// See docs/machine-circuits.md for the laws, signs and numerical boundary.
#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace banjo::machines {

struct CircuitMotorInput {
    unsigned id{};
    double command{}, speed_rad_s{}, torque_constant{}, resistance_ohm{};
    bool present{true};
};

struct CircuitStep {
    double dt_s{}, source_current_a{}, source_j{}, electrical_residual_j{};
    double max_kcl_a{};
    bool limited{};
    std::vector<double> voltage_v, current_a, motor_current_a, torque_n_m;
    std::vector<double> heat_j, branch_heat_j, shaft_j;
};

class Circuit {
public:
    static Circuit read(const nlohmann::json &doc, bool restore = false);
    [[nodiscard]] nlohmann::json saved() const;
    [[nodiscard]] CircuitStep solve(double dt_s, double voltage_v, double charge_j,
                                    double max_power_w,
                                    const std::vector<CircuitMotorInput> &motors) const;
    // Only after the host accepts its mechanical step. A refused trial changes
    // neither charge nor thermal/fuse/damage state.
    void commit(const CircuitStep &step, double actual_shaft_work_j);
    void addFrictionHeat(CircuitStep &step, std::size_t branch, double joules) const;
    void setSwitch(const std::string &id, bool closed);
    [[nodiscard]] unsigned store() const { return store_; }
    [[nodiscard]] std::vector<unsigned> motors() const;
    [[nodiscard]] unsigned motor(std::size_t branch) const;
    [[nodiscard]] double ratio(std::size_t branch) const;
    [[nodiscard]] double resistanceFactor(std::size_t branch) const;
    [[nodiscard]] std::size_t size() const { return branches_.size(); }

private:
    struct Heat {
        std::string id, component;
        double capacity{}, temperature{}, ambient_conductance{};
    };
    struct HeatLink { std::size_t a{}, b{}; double conductance{}; };
    struct Branch {
        std::string id, kind, component;
        std::size_t a{}, b{}, thermal{};
        double resistance{}, alpha{}, reference_k{293.15}, trip_k{};
        double fuse_limit{}, fuse_used{}, ratio{1.0};
        unsigned motor{};
        bool closed{true}, failed{};
    };
    std::string id_;
    unsigned store_{};
    std::vector<std::string> nodes_;
    std::vector<Branch> branches_;
    std::vector<Heat> heat_;
    std::vector<HeatLink> heat_links_;
    std::size_t positive_{}, negative_{}, source_heat_{};
    double source_resistance_{}, ambient_k_{293.15};
    double elapsed_s_{}, source_j_{}, heat_j_{}, shaft_j_{}, ambient_j_{};
    double electrical_residual_j_{}, thermal_residual_j_{}, coupling_residual_j_{};
    CircuitStep last_;
};
}
