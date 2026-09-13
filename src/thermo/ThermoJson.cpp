#include "thermo/ThermoJson.hpp"

#include "thermo/ThermalMechanics.hpp"

#include <nlohmann/json.hpp>

#include <cmath>
#include <initializer_list>
#include <stdexcept>
#include <string>

namespace banjo::thermo {
namespace {

using json = nlohmann::json;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::invalid_argument(message);
}

// Text that is not JSON is the caller's mistake, said as one.
json parse(const std::string &text, const char *what) {
    try {
        return json::parse(text);
    } catch (const json::exception &error) {
        throw std::invalid_argument(std::string(what) + " is not JSON: " + error.what());
    }
}

// Anything a declaration does not understand is refused by name. A misspelt
// "tempreature_k" silently ignored is a log at room temperature that somebody
// believes is alight.
void onlyKeys(const json &node, std::initializer_list<const char *> allowed, const std::string &where) {
    require(node.is_object(), where + " must be an object");
    for (auto it = node.begin(); it != node.end(); ++it) {
        bool known = false;
        for (const char *key : allowed) known = known || it.key() == key;
        require(known, where + ": \"" + it.key() + "\" is not something it can say");
    }
}

double number(const json &node, const char *key, double fallback, const std::string &where) {
    if (!node.contains(key) || node.at(key).is_null()) return fallback;
    const json &value = node.at(key);
    require(value.is_number(), where + ": " + key + " must be a number");
    const double out = value.get<double>();
    require(std::isfinite(out), where + ": " + key + " must be finite");
    return out;
}

std::string text(const json &node, const char *key, const std::string &fallback, const std::string &where) {
    if (!node.contains(key) || node.at(key).is_null()) return fallback;
    require(node.at(key).is_string(), where + ": " + key + " must be a name");
    return node.at(key).get<std::string>();
}

bool flag(const json &node, const char *key, bool fallback, const std::string &where) {
    if (!node.contains(key) || node.at(key).is_null()) return fallback;
    require(node.at(key).is_boolean(), where + ": " + key + " is true or false");
    return node.at(key).get<bool>();
}

Vec3 vector3(const json &node, const char *key, Vec3 fallback, const std::string &where) {
    if (!node.contains(key) || node.at(key).is_null()) return fallback;
    const json &v = node.at(key);
    require(v.is_array() && v.size() == 3 && v[0].is_number() && v[1].is_number() && v[2].is_number(),
            where + ": " + key + " needs three numbers");
    return {v[0].get<double>(), v[1].get<double>(), v[2].get<double>()};
}

std::vector<std::pair<std::string, double>> fractions(const json &node, const std::string &where) {
    require(node.is_object(), where + ": contents are an object of substance to mass fraction, "
                                      "like {\"dry wood\": 0.8, \"moisture\": 0.2}");
    std::vector<std::pair<std::string, double>> out;
    for (auto it = node.begin(); it != node.end(); ++it) {
        require(it.value().is_number(), where + ": the fraction of " + it.key() + " must be a number");
        out.emplace_back(it.key(), it.value().get<double>());
    }
    return out;
}

Ambient readAmbient(const json &node) {
    onlyKeys(node, {"temperature_k", "pressure_pa", "film_coefficient_w_m2_k", "floor_conductance_w_m2_k",
                    "contact_conductance_w_m2_k"},
             "ambient");
    Ambient a;
    a.temperature_k = number(node, "temperature_k", a.temperature_k, "ambient");
    a.pressure_pa = number(node, "pressure_pa", a.pressure_pa, "ambient");
    a.film_coefficient_w_m2_k = number(node, "film_coefficient_w_m2_k", a.film_coefficient_w_m2_k, "ambient");
    a.floor_conductance_w_m2_k = number(node, "floor_conductance_w_m2_k", a.floor_conductance_w_m2_k, "ambient");
    a.contact_conductance_w_m2_k =
        number(node, "contact_conductance_w_m2_k", a.contact_conductance_w_m2_k, "ambient");
    return a;
}

GasRegionDeclaration readRegion(const json &node) {
    require(node.is_object(), "a gas region must be an object");
    const std::string where = "gas region \"" + node.value("name", std::string("?")) + "\"";
    onlyKeys(node, {"name", "contents", "temperature_k", "pressure_pa", "balance", "volume_m3", "height_m",
                    "piston", "container", "axis", "area_m2", "wall_conductance_w_k", "vent_area_m2",
                    "vent_open"},
             where);
    GasRegionDeclaration d;
    d.name = text(node, "name", "", where);
    if (node.contains("contents")) d.mass_fraction = fractions(node.at("contents"), where);
    d.temperature_k = number(node, "temperature_k", 0.0, where);
    d.pressure_pa = number(node, "pressure_pa", 0.0, where);
    d.balance = flag(node, "balance", false, where);
    d.volume_m3 = number(node, "volume_m3", 0.0, where);
    d.height_m = number(node, "height_m", 0.0, where);
    d.piston = text(node, "piston", "", where);
    d.container = text(node, "container", "", where);
    d.axis = vector3(node, "axis", d.axis, where);
    d.area_m2 = number(node, "area_m2", 0.0, where);
    d.wall_conductance_w_k = number(node, "wall_conductance_w_k", -1.0, where);
    d.vent_area_m2 = number(node, "vent_area_m2", 0.0, where);
    d.vent_open = flag(node, "vent_open", true, where);
    return d;
}

HeaterDeclaration readHeater(const json &node) {
    onlyKeys(node, {"target", "power_w", "start_s", "seconds", "label"}, "heater");
    HeaterDeclaration d;
    d.target = text(node, "target", "", "heater");
    require(!d.target.empty(), "a heater needs a target: a body or a gas region");
    d.power_w = number(node, "power_w", 0.0, "heater");
    d.start_s = number(node, "start_s", 0.0, "heater");
    d.seconds = number(node, "seconds", 0.0, "heater");
    d.label = text(node, "label", d.label, "heater");
    return d;
}

ContentsDeclaration readContentsEntry(const json &node) {
    onlyKeys(node, {"body", "contents", "temperature_k", "layer_depth_m", "environment"}, "contents");
    ContentsDeclaration d;
    d.body = text(node, "body", "", "contents");
    require(!d.body.empty(), "contents need the body they are in");
    if (node.contains("contents")) d.mass_fraction = fractions(node.at("contents"), d.body);
    d.temperature_k = number(node, "temperature_k", 0.0, d.body);
    d.layer_depth_m = number(node, "layer_depth_m", -1.0, d.body);
    d.environment = text(node, "environment", "", d.body);
    return d;
}

void readBlock(const json &block, Declarations &out, const std::string &where) {
    onlyKeys(block, {"ambient", "gas_regions", "heaters", "contents"}, where);
    if (block.contains("ambient")) out.ambient = readAmbient(block.at("ambient"));
    const auto list = [&](const char *key) -> const json & {
        const json &node = block.at(key);
        require(node.is_array(), where + ": " + key + " must be a list");
        return node;
    };
    if (block.contains("gas_regions"))
        for (const json &node : list("gas_regions")) out.regions.push_back(readRegion(node));
    if (block.contains("heaters"))
        for (const json &node : list("heaters")) out.heaters.push_back(readHeater(node));
    if (block.contains("contents"))
        for (const json &node : list("contents")) out.contents.push_back(readContentsEntry(node));
}

json finiteOrNull(double value) { return std::isfinite(value) ? json(value) : json(nullptr); }

json vec(const Vec3 &v) { return json::array({v.x, v.y, v.z}); }

json contentsOf(const std::vector<std::pair<std::string, double>> &kg) {
    json out = json::object();
    for (const auto &[id, mass] : kg) out[id] = mass;
    return out;
}

json curveOf(const ReductionCurve &curve) {
    json out = json::array();
    for (const auto &[k, factor] : curve.points) out.push_back(json::array({k, factor}));
    return out;
}

} // namespace

std::string mechanicalLawsJson() {
    json laws = json::array();
    for (const MechanicalLaw &law : mechanicalLaws())
        laws.push_back({{"material", law.material},
                        {"id", law.id},
                        {"version", law.version},
                        {"provenance", std::string(provenanceName(law.provenance))},
                        {"source", law.source},
                        {"load_bearing", law.load_bearing},
                        {"reference_fraction", law.reference_fraction},
                        {"factor_by_temperature_k", {{"stiffness", curveOf(law.stiffness)},
                                                     {"tension", curveOf(law.tension)},
                                                     {"compression", curveOf(law.compression)},
                                                     {"shear", curveOf(law.shear)}}},
                        {"char_k", law.char_k},
                        {"lasting_by_peak_k", curveOf(law.permanent)},
                        {"lasting_source", law.permanent_source},
                        {"recovers_on_cooling", law.recovers},
                        {"supported_k", json::array({law.supported_from_k, law.supported_to_k})},
                        {"recovery_modelled_to_k", law.recovery_to_k},
                        {"not_modelled", law.not_modelled}});
    return laws.dump();
}

Declarations readSceneDeclarations(const std::string &scene_json) {
    const json document = parse(scene_json, "the scene");
    Declarations out;
    if (!document.is_object()) return out;
    if (document.contains("bodies") && document.at("bodies").is_array()) {
        for (const json &body : document.at("bodies")) {
            if (!body.is_object()) continue;
            const bool declares = body.contains("contents") || body.contains("temperature_k") ||
                                  body.contains("layer_depth_m") || body.contains("environment");
            if (!declares) continue;
            ContentsDeclaration d;
            d.body = body.value("name", std::string("body"));
            if (body.contains("contents") && !body.at("contents").is_null())
                d.mass_fraction = fractions(body.at("contents"), d.body);
            d.temperature_k = number(body, "temperature_k", 0.0, d.body);
            d.layer_depth_m = number(body, "layer_depth_m", -1.0, d.body);
            d.environment = text(body, "environment", "", d.body);
            out.contents.push_back(std::move(d));
        }
    }
    if (document.contains("thermo") && !document.at("thermo").is_null())
        readBlock(document.at("thermo"), out, "thermo");
    return out;
}

Declarations readDeclarations(const std::string &text_json) {
    Declarations out;
    readBlock(parse(text_json, "the declaration"), out, "a thermochemical declaration");
    return out;
}

void apply(ThermoWorld &world, const Declarations &declarations) {
    if (declarations.ambient) world.setAmbient(*declarations.ambient);
    for (const GasRegionDeclaration &region : declarations.regions) world.declareGasRegion(region);
    for (const ContentsDeclaration &contents : declarations.contents) world.declareContents(contents);
    for (const HeaterDeclaration &heater : declarations.heaters) world.heat(heater);
}

std::string reportJson(const ThermoWorld &world, bool with_model) {
    json bodies = json::array();
    for (const BodyHeat &b : world.bodies())
        bodies.push_back({{"name", b.body},
                          {"material", b.material},
                          {"temperature_k", b.temperature_k},
                          {"core_temperature_k", b.core_temperature_k},
                          {"mass_kg", b.mass_kg},
                          {"fuel_kg", b.fuel_kg},
                          {"heat_release_w", b.heat_release_w},
                          {"fuel_use_kg_s", b.fuel_use_kg_s},
                          {"remaining_s", finiteOrNull(b.remaining_s)},
                          {"heater_w", b.heater_w},
                          {"gained_w", b.gained_w},
                          {"lost_w", b.lost_w},
                          {"reacting", b.reacting},
                          {"declared", b.declared},
                          {"contents_kg", contentsOf(b.contents_kg)}});
    json regions = json::array();
    for (const RegionState &r : world.regions())
        regions.push_back({{"name", r.name},
                           {"temperature_k", r.temperature_k},
                           {"pressure_pa", r.pressure_pa},
                           {"volume_m3", r.volume_m3},
                           {"mass_kg", r.mass_kg},
                           {"moles", r.moles},
                           {"contents_kg", contentsOf(r.contents_kg)},
                           {"piston", r.piston},
                           {"axis", vec(r.axis)},
                           {"base_m", vec(r.base_m)},
                           {"area_m2", r.area_m2},
                           {"height_m", r.height_m},
                           {"stroke_m", r.stroke_m},
                           {"force_n", r.force_n},
                           {"work_to_bodies_j", r.work_to_bodies_j},
                           {"work_to_atmosphere_j", r.work_to_atmosphere_j},
                           {"heater_w", r.heater_w},
                           {"wall_loss_w", r.wall_loss_w},
                           {"vent_open", r.vent_open},
                           {"vent_flow_kg_s", r.vent_flow_kg_s}});
    const Ledger l = world.ledger();
    json ledger = {{"stored_j", l.storedJ()},
                   {"chemical_j", l.reference_j},
                   {"thermal_j", l.sensible_j},
                   {"mass_kg", l.mass_kg},
                   {"initial_j", l.initial_j},
                   {"initial_mass_kg", l.initial_mass_kg},
                   {"heater_in_j", l.heater_in_j},
                   {"heat_to_surroundings_j", l.heat_to_surroundings_j},
                   {"matter_in_j", l.matter_in_j},
                   {"matter_in_kg", l.matter_in_kg},
                   {"matter_out_j", l.matter_out_j},
                   {"matter_out_kg", l.matter_out_kg},
                   {"joined_j", l.joined_j},
                   {"joined_kg", l.joined_kg},
                   {"left_j", l.left_j},
                   {"left_kg", l.left_kg},
                   {"work_to_bodies_j", l.work_to_bodies_j},
                   {"work_to_atmosphere_j", l.work_to_atmosphere_j},
                   {"mechanical_in_j", l.mechanical_in_j},
                   {"numerical_j", l.numerical_j},
                   {"residual_j", l.residualJ()},
                   {"mass_residual_kg", l.massResidualKg()},
                   {"out_of_range_steps", l.out_of_range_steps}};
    json report = {{"time_s", world.timeS()},
                   {"ambient", {{"temperature_k", world.ambient().temperature_k},
                                {"pressure_pa", world.ambient().pressure_pa}}},
                   {"bodies", std::move(bodies)},
                   {"regions", std::move(regions)},
                   {"ledger", std::move(ledger)}};
    if (with_model) {
        const Model &model = world.model();
        json substances = json::array();
        for (const Substance &s : model.substances)
            substances.push_back({{"id", s.id},
                                  {"phase", std::string(phaseName(s.phase))},
                                  {"molar_mass_kg_mol", s.molar_mass_kg_mol},
                                  {"cv_j_kg_k", s.cv_j_kg_k},
                                  {"cp_j_kg_k", cpJKgK(s)},
                                  {"reference_energy_j_kg", s.reference_energy_j_kg},
                                  {"conductivity_w_m_k", s.conductivity_w_m_k},
                                  {"emissivity", s.emissivity},
                                  {"provenance", std::string(provenanceName(s.provenance))},
                                  {"note", s.note}});
        json reactions = json::array();
        for (const Reaction &r : model.reactions) {
            json in = json::array(), out = json::array();
            for (const Term &t : r.reactants)
                in.push_back({{"substance", model[t.substance].id},
                              {"kg_per_kg", t.kg_per_kg},
                              {"from", t.supply == Supply::Material ? "the material" : "the surroundings"}});
            for (const Term &t : r.products)
                out.push_back({{"substance", model[t.substance].id},
                               {"kg_per_kg", t.kg_per_kg},
                               {"goes", t.fate == Fate::Retained ? "stays in the material" : "leaves it"}});
            reactions.push_back({{"id", r.id},
                                 {"version", r.version},
                                 {"provenance", std::string(provenanceName(r.provenance))},
                                 {"description", r.description},
                                 {"reactants", std::move(in)},
                                 {"products", std::move(out)},
                                 {"rate", {{"kind", r.rate.kind == RateKind::Surface ? "surface" : "volume"},
                                           {"pre_exponential", r.rate.pre_exponential},
                                           {"activation_temperature_k", r.rate.activation_temperature_k},
                                           {"minimum_temperature_k", r.rate.minimum_temperature_k},
                                           {"maximum_temperature_k", r.rate.maximum_temperature_k},
                                           {"supply_coefficient_m_s", r.rate.supply_coefficient_m_s}}},
                                 {"heat_released_j_per_kg_at_298k",
                                  model.heatOfReactionJPerKg(r, kQuotedTemperatureK)}});
        }
        json compositions = json::object();
        for (const auto &[material, parts] : model.composition_of) {
            json mix = json::object();
            for (const auto &[substance, fraction] : parts) mix[model[substance].id] = fraction;
            compositions[material] = std::move(mix);
        }
        report["model"] = {{"id", model.id},
                           {"version", model.version},
                           {"valid_from_k", model.minimum_temperature_k},
                           {"valid_to_k", model.maximum_temperature_k},
                           {"energy_convention",
                            "u = u0 + cv T per substance, from 0 K; chemical and thermal are the "
                            "reference and sensible parts of one internal energy"},
                           {"substances", std::move(substances)},
                           {"reactions", std::move(reactions)},
                           {"compositions", std::move(compositions)},
                           // What heat does to what each material can carry,
                           // and where every number came from.
                           {"mechanical_laws", json::parse(mechanicalLawsJson())}};
        report["limitations"] = ThermoWorld::limitations();
    }
    return report.dump();
}

} // namespace banjo::thermo
