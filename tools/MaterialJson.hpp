#pragma once

#include "material/SmallStrainLaw.hpp"

#include <algorithm>
#include <cmath>
#include <cctype>
#include <nlohmann/json.hpp>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace banjo::material_json {
using Json = nlohmann::json;

inline void require(bool condition, const char *message) {
    if (!condition) throw std::invalid_argument(message);
}

inline void exactKeys(const Json &value, std::initializer_list<const char *> names) {
    require(value.is_object() && value.size() == names.size(), "Unexpected object fields");
    for (const char *name : names) require(value.contains(name), "Missing required field");
}

inline double finiteNumber(const Json &value) {
    require(value.is_number(), "Expected numeric SI value");
    const double result = value.get<double>();
    require(std::isfinite(result), "Nonfinite SI value");
    return result;
}

inline std::array<double, 3> triple(const Json &value) {
    require(value.is_array() && value.size() == 3, "Expected three coefficients");
    return {finiteNumber(value[0]), finiteNumber(value[1]), finiteNumber(value[2])};
}

struct Material {
    Json descriptor;
    std::string id;
    SmallStrainLaw law;
    double density_kg_m3{};
};

inline Material parseMaterial(const Json &value) {
    exactKeys(value, {"material_id", "name", "units", "density_kg_m3",
                      "mechanical_law", "parameters", "required_capabilities",
                      "physical_hash"});
    require(value["material_id"].is_string() && value["name"].is_string() &&
                value["physical_hash"].is_string(),
            "Invalid material labels");
    const std::string id = value["material_id"].get<std::string>();
    const auto nonblank = [](const std::string &text) {
        return !text.empty() && std::any_of(text.begin(), text.end(), [](unsigned char c) {
            return !std::isspace(c);
        });
    };
    require(nonblank(id) && nonblank(value["name"].get<std::string>()) && id.size() <= 128 &&
                value["name"].get<std::string>().size() <= 256 &&
                value["physical_hash"].get<std::string>().size() <= 256,
            "Invalid material label length");
    require(value["units"] == "SI", "Only SI supported");
    const double density = finiteNumber(value["density_kg_m3"]);
    require(density > 0 && density <= 1.e9, "Invalid material density");
    require(value["required_capabilities"] == Json::array({"small_strain_reference"}),
            "Unsupported requested capability");
    const auto &parameters = value["parameters"];
    SmallStrainLaw law;
    if (value["mechanical_law"] == "isotropic_elastic") {
        exactKeys(parameters, {"young_modulus_pa", "poisson_ratio",
                               "maximum_total_strain_norm"});
        law.kind = SmallStrainLawKind::IsotropicElastic;
        law.young_modulus_pa[0] = finiteNumber(parameters["young_modulus_pa"]);
        law.poisson_xy_yz_zx[0] = finiteNumber(parameters["poisson_ratio"]);
        law.maximum_total_strain_norm = finiteNumber(parameters["maximum_total_strain_norm"]);
    } else if (value["mechanical_law"] == "orthotropic_elastic") {
        exactKeys(parameters, {"young_modulus_pa", "poisson_xy_yz_zx",
                               "shear_xy_yz_zx_pa", "maximum_total_strain_norm"});
        law.kind = SmallStrainLawKind::OrthotropicElastic;
        law.young_modulus_pa = triple(parameters["young_modulus_pa"]);
        law.poisson_xy_yz_zx = triple(parameters["poisson_xy_yz_zx"]);
        law.shear_xy_yz_zx_pa = triple(parameters["shear_xy_yz_zx_pa"]);
        law.maximum_total_strain_norm = finiteNumber(parameters["maximum_total_strain_norm"]);
    } else if (value["mechanical_law"] == "j2_plastic") {
        exactKeys(parameters, {"young_modulus_pa", "poisson_ratio",
                               "initial_yield_stress_pa", "isotropic_hardening_modulus_pa",
                               "maximum_total_strain_norm"});
        law.kind = SmallStrainLawKind::J2Plastic;
        law.j2.young_modulus_pa = finiteNumber(parameters["young_modulus_pa"]);
        law.j2.poisson_ratio = finiteNumber(parameters["poisson_ratio"]);
        law.j2.initial_yield_stress_pa =
            finiteNumber(parameters["initial_yield_stress_pa"]);
        law.j2.isotropic_hardening_modulus_pa =
            finiteNumber(parameters["isotropic_hardening_modulus_pa"]);
        law.j2.maximum_total_strain_norm =
            finiteNumber(parameters["maximum_total_strain_norm"]);
    } else {
        throw std::invalid_argument("Unsupported mechanical law");
    }
    validateSmallStrainLaw(law);
    return {value, id, law, density};
}

inline Json parseStrict(const std::string &input) {
    std::vector<std::set<std::string>> seen;
    auto callback = [&](int, Json::parse_event_t event, Json &value) {
        if (event == Json::parse_event_t::object_start) seen.emplace_back();
        if (event == Json::parse_event_t::key)
            require(seen.back().insert(value.get<std::string>()).second,
                    "Duplicate JSON field");
        if (event == Json::parse_event_t::object_end) seen.pop_back();
        return true;
    };
    return Json::parse(input, callback);
}

} // namespace banjo::material_json
