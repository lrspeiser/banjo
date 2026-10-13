#pragma once

// Bounded DC/RC networks. Construction and collision geometry stay
// with the product; this value owns only electrical and lumped thermal state.
// Default builds use ngspice operating points for reversible DC/BE trials;
// accepted capacitor/thermal/energy state remains here, not in SPICE history.
// See docs/electronics-expansion.md for the laws and numerical boundary.
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
    // Joule heat of branches that warm a world body (heats_body) rather than
    // one of the circuit's own lumped nodes. Not in heat_j: it leaves the
    // circuit, and the host hands it to that body's thermal parcel.
    double exported_j{}, emitted_j{};
    double storage_delta_j{}, numerical_loss_j{};
    bool limited{};
    std::vector<double> voltage_v, current_a, motor_current_a, torque_n_m;
    std::vector<double> heat_j, branch_heat_j, shaft_j, light_j;
    std::vector<double> capacitor_voltage_v;
};

// A switch worked by a hinge in the world: closed while the pin's measured
// angle is at or beyond a declared reading. The host reads the angle at each
// accepted step boundary; the circuit never moves the pin.
struct CircuitHingeSwitch {
    std::string branch;
    unsigned joint{};
    double closed_rad{};
    int sense{};            // +1: closed at or above; -1: closed at or below
};

// A switch worked by light (docs/optics-checkpoint.md): closed while the light
// a named light sensor in the world reads is at or beyond a declared power. The
// host sets it from the sensor's last reading before each solve; the circuit
// never makes light.
struct CircuitLightSwitch {
    std::string branch;
    std::string sensor;
    double closed_w{};
    int sense{};            // +1: closed at or above; -1: closed at or below
};

// A switch worked by contact: closed while two named bodies in the world touch
// -- a contact on a lever pressed against a plate, a ball lying across two
// rails. The host sets it from the contacts of the last step before each
// solve; the circuit never moves anything. Which bodies can carry current is
// the host's to say (docs/machine-circuits.md).
struct CircuitContactSwitch {
    std::string branch;
    std::string a, b;
};

// One branch's Joule heat for one step, owed to a named world body.
struct CircuitBodyHeat {
    std::string branch, body;
    double joules{};
};

class Circuit {
public:
    static Circuit read(const nlohmann::json &doc, bool restore = false);
    [[nodiscard]] static const char *solverName();
    [[nodiscard]] static const char *solverVersion();
    [[nodiscard]] const std::string &id() const { return id_; }
    [[nodiscard]] std::vector<CircuitHingeSwitch> hingeSwitches() const;
    [[nodiscard]] std::vector<CircuitLightSwitch> lightSwitches() const;
    [[nodiscard]] std::vector<CircuitContactSwitch> contactSwitches() const;
    [[nodiscard]] std::vector<std::string> heatedBodies() const;
    [[nodiscard]] std::vector<CircuitBodyHeat> bodyHeat(const CircuitStep &step) const;
    // The world has no such body to warm this step (it burned away, say): the
    // branch's heat stays in its declared lumped node instead, so it is still
    // on this circuit's ledger rather than lost.
    void keepHeat(CircuitStep &step, const std::string &branch) const;
    [[nodiscard]] nlohmann::json saved() const;
    [[nodiscard]] CircuitStep solve(double dt_s, double voltage_v, double charge_j,
                                    double max_power_w,
                                    const std::vector<CircuitMotorInput> &motors) const;
    // Only after the host accepts its mechanical step. A refused trial changes
    // neither charge nor thermal/fuse/damage state.
    void commit(const CircuitStep &step, double actual_shaft_work_j);
    void addFrictionHeat(CircuitStep &step, std::size_t branch, double joules) const;
    void setSwitch(const std::string &id, bool closed);
    void setPresent(std::size_t branch, bool present);
    [[nodiscard]] unsigned store() const { return store_; }
    [[nodiscard]] std::vector<unsigned> motors() const;
    [[nodiscard]] unsigned motor(std::size_t branch) const;
    [[nodiscard]] unsigned lamp(std::size_t branch) const;
    [[nodiscard]] std::vector<unsigned> lamps() const;
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
        double capacitance{}, capacitor_voltage{};
        unsigned motor{}, lamp{};
        double efficiency{};
        bool closed{true}, failed{}, present{true};
        std::string body;                 // heats_body: a world body, not a lumped node
        unsigned follow_joint{};          // follows_hinge: 0 for a hand-worked switch
        double follow_rad{};
        int follow_sense{};
        std::string follow_sensor;        // follows_light: "" for a switch not worked by light
        double follow_w{};
        std::string touch_a, touch_b;     // follows_contact: "" for a switch not worked by contact
    };
    std::string id_;
    unsigned store_{};
    std::vector<std::string> nodes_;
    std::vector<Branch> branches_;
    std::vector<Heat> heat_;
    std::vector<HeatLink> heat_links_;
    std::size_t positive_{}, negative_{}, source_heat_{};
    double source_resistance_{}, ambient_k_{293.15};
    double elapsed_s_{}, source_j_{}, heat_j_{}, shaft_j_{}, ambient_j_{}, exported_j_{}, emitted_j_{};
    double electrical_residual_j_{}, thermal_residual_j_{}, coupling_residual_j_{};
    double storage_delta_j_{}, numerical_loss_j_{};
    CircuitStep last_;
};
}
