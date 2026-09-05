#pragma once
#include "material/MaterialCatalog.hpp"
#include "core/Math.hpp"
#include <array>
#include <vector>
namespace banjo {
struct BowlSettings {
    double radius_m{1.2},depth_m{.55},tilt_degrees{};
    MaterialPreset surface{MaterialPreset::Concrete};
    unsigned rings{24},sectors{96};
    bool experimental_fracture{true};
    bool impact_trial{};
};
// Parabolic finite open bowl, upward-facing triangles, shared by renderer/solver.
std::vector<std::array<Vec3,3>> compileBowl(const BowlSettings &settings);
Vec3 bowlPoint(const BowlSettings &settings,double x,double z);
}
