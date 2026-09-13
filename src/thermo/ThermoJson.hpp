#pragma once

// Declarations in, reports out: the thermochemical network as JSON.
//
// A scene declares what its bodies contain on the bodies themselves --
//
//     {"name": "log", "shape": "box", "material": "oak", ...,
//      "contents": {"dry wood": 0.8, "moisture": 0.18, "ash": 0.02},
//      "temperature_k": 293.15}
//
// -- and everything that is not a body in a "thermo" block beside them:
//
//     "thermo": {"ambient": {"temperature_k": 293.15, "pressure_pa": 101325},
//                "gas_regions": [{"name": "cylinder gas", "contents": {"argon": 1},
//                                 "piston": "piston", "axis": [0, 1, 0],
//                                 "height_m": 0.4, "balance": true}],
//                "heaters": [{"target": "log", "power_w": 10000, "seconds": 60}]}
//
// An oak body with no "contents" is still made of what oak is made of; the key
// is for saying something different (a wetter log, a propellant charge).
#include "thermo/ThermoWorld.hpp"

#include <optional>
#include <string>
#include <vector>

namespace banjo::thermo {

struct Declarations {
    std::optional<Ambient> ambient;
    std::vector<ContentsDeclaration> contents;
    std::vector<GasRegionDeclaration> regions;
    std::vector<HeaterDeclaration> heaters;
    [[nodiscard]] bool any() const {
        return ambient.has_value() || !contents.empty() || !regions.empty() || !heaters.empty();
    }
};

// Everything a scene document declares. Throws std::invalid_argument, naming
// the key, on anything it does not understand.
[[nodiscard]] Declarations readSceneDeclarations(const std::string &scene_json);
// A declaration document on its own, for declaring into a world that is already
// open: {"contents": [{"body": ...}], "gas_regions": [...], "heaters": [...]}.
[[nodiscard]] Declarations readDeclarations(const std::string &json);
// Regions first, because contents can be declared inside one; then contents;
// then heaters, which may be aimed at either.
void apply(ThermoWorld &world, const Declarations &declarations);

// Bodies, regions and the ledger; with `with_model`, also every substance and
// reaction with where its numbers came from, and what is not modelled.
[[nodiscard]] std::string reportJson(const ThermoWorld &world, bool with_model = false);

// Every mechanical law (thermo/ThermalMechanics.hpp) as a JSON array: its
// curves, what is irreversible, where it is supported, where its numbers came
// from and what it does not model.
[[nodiscard]] std::string mechanicalLawsJson();

} // namespace banjo::thermo
