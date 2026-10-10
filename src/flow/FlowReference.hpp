#pragma once
#include <array>
#include <vector>
#include <cstdint>

namespace banjo::flow {
// Flat-bed, hydrostatic Saint-Venant finite volumes. No vertical momentum,
// viscosity, splashes, capillarity, phase changes or moving solid coupling.
struct Settings { int nx{48}, nz{24}; double dx{0.1}, density{1000}, gravity{9.81}, cfl{0.2}; };
struct Cell { double h{}, qx{}, qz{}; };
struct Account {
    double time{}, mass{}, px{}, pz{}, ly{}, energy{};
    double wall_px{}, wall_pz{}, wall_ly{}, numerical_ly{}, numerical_energy{};
    double mass_residual{}, px_residual{}, pz_residual{}, ly_residual{}, energy_residual{};
    std::uint64_t steps{};
};
class Reference {
public:
    struct State { Settings settings; std::vector<Cell> cells; Account initial, crossings; };
    Reference(Settings settings, std::vector<Cell> cells);
    void advance(double seconds, std::uint64_t max_steps=20000, std::uint64_t max_cell_updates=8000000); // atomic
    const Settings& settings() const { return settings_; }
    const std::vector<Cell>& cells() const { return cells_; }
    Account account() const;
    State state() const { return {settings_,cells_,initial_,crossings_}; }
    static Reference restore(const State& state);
private:
    void step(double dt);
    Account totals() const;
    Settings settings_; std::vector<Cell> cells_;
    Account initial_, crossings_;
};
}
