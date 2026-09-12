#include "thermo/Thermochemistry.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace banjo::thermo {
namespace {

void require(bool ok, const std::string &message) {
    if (!ok) throw std::invalid_argument(message);
}

bool finite(double value) { return std::isfinite(value); }

} // namespace

std::string_view provenanceName(Provenance provenance) {
    switch (provenance) {
    case Provenance::Demonstration: return "demonstration";
    case Provenance::ReferenceDerived: return "reference-derived";
    case Provenance::ExperimentallyValidated: return "experimentally validated";
    }
    return "unknown";
}

std::string_view phaseName(Phase phase) {
    switch (phase) {
    case Phase::Solid: return "solid";
    case Phase::Liquid: return "liquid";
    case Phase::Gas: return "gas";
    }
    return "unknown";
}

double gasConstantJKgK(const Substance &substance) {
    return substance.phase == Phase::Gas && substance.molar_mass_kg_mol > 0.0
               ? kGasConstantJMolK / substance.molar_mass_kg_mol
               : 0.0;
}

double cpJKgK(const Substance &substance) {
    return substance.cv_j_kg_k + gasConstantJKgK(substance);
}

double specificEnergyJKg(const Substance &substance, double temperature_k) {
    return substance.reference_energy_j_kg + substance.cv_j_kg_k * temperature_k;
}

double specificEnthalpyJKg(const Substance &substance, double temperature_k) {
    return specificEnergyJKg(substance, temperature_k) + gasConstantJKgK(substance) * temperature_k;
}

std::size_t Model::add(Substance substance) {
    require(!substance.id.empty(), "a substance needs a name");
    require(!has(substance.id), "there is already a substance called " + substance.id);
    require(finite(substance.cv_j_kg_k) && substance.cv_j_kg_k > 0.0,
            substance.id + ": cv must be finite and positive");
    require(finite(substance.reference_energy_j_kg),
            substance.id + ": the reference energy must be finite");
    require(substance.phase != Phase::Gas ||
                (finite(substance.molar_mass_kg_mol) && substance.molar_mass_kg_mol > 0.0),
            substance.id + ": a gas needs its molar mass");
    require(finite(substance.conductivity_w_m_k) && substance.conductivity_w_m_k >= 0.0,
            substance.id + ": conductivity must be finite and not negative");
    require(finite(substance.emissivity) && substance.emissivity >= 0.0 &&
                substance.emissivity <= 1.0,
            substance.id + ": emissivity is between 0 and 1");
    substances.push_back(std::move(substance));
    return substances.size() - 1;
}

void Model::addReaction(Reaction reaction) {
    reactions.push_back(std::move(reaction));
    try {
        validate();
    } catch (...) {
        reactions.pop_back();
        throw;
    }
}

void Model::setComposition(const std::string &material,
                           const std::vector<std::pair<std::string, double>> &fractions) {
    require(!fractions.empty(), material + ": a composition needs at least one substance");
    std::vector<std::pair<std::size_t, double>> resolved;
    double sum = 0.0;
    for (const auto &[name, fraction] : fractions) {
        require(finite(fraction) && fraction > 0.0,
                material + ": every fraction in a composition is positive");
        resolved.emplace_back(index(name), fraction);
        sum += fraction;
    }
    for (auto &entry : resolved) entry.second /= sum;
    composition_of[material] = std::move(resolved);
}

std::size_t Model::index(std::string_view name) const {
    for (std::size_t i = 0; i < substances.size(); ++i)
        if (substances[i].id == name) return i;
    throw std::invalid_argument("there is no substance called \"" + std::string(name) +
                                "\" in the model " + this->id);
}

bool Model::has(std::string_view name) const {
    return std::any_of(substances.begin(), substances.end(),
                       [&](const Substance &s) { return s.id == name; });
}

void Model::validate() const {
    for (std::size_t r = 0; r < reactions.size(); ++r) {
        const Reaction &reaction = reactions[r];
        const std::string who = "reaction \"" + reaction.id + "\"";
        require(!reaction.id.empty(), "a reaction needs a name");
        for (std::size_t other = 0; other < r; ++other)
            require(reactions[other].id != reaction.id, who + " is declared twice");
        require(!reaction.reactants.empty() && !reaction.products.empty(),
                who + " needs reactants and products");
        const Term &basis = reaction.reactants.front();
        require(basis.supply == Supply::Material,
                who + ": the first reactant is the basis and must be in the material");
        require(basis.kg_per_kg == 1.0, who + ": the basis reactant is 1 kg per kg");
        double in = 0.0, out = 0.0;
        for (const Term &term : reaction.reactants) {
            require(term.substance < substances.size(), who + " names a missing substance");
            require(finite(term.kg_per_kg) && term.kg_per_kg > 0.0,
                    who + ": every coefficient is positive");
            if (term.supply == Supply::Environment)
                require(substances[term.substance].phase == Phase::Gas,
                        who + ": only a gas can be supplied by the surroundings");
            in += term.kg_per_kg;
        }
        for (const Term &term : reaction.products) {
            require(term.substance < substances.size(), who + " names a missing substance");
            require(finite(term.kg_per_kg) && term.kg_per_kg > 0.0,
                    who + ": every coefficient is positive");
            out += term.kg_per_kg;
        }
        // The one rule a reaction may never break: what goes in comes out.
        require(std::abs(in - out) <= 1.0e-9 * in,
                who + " does not balance: " + std::to_string(in) + " kg in, " +
                    std::to_string(out) + " kg out");
        const RateLaw &rate = reaction.rate;
        require(finite(rate.pre_exponential) && rate.pre_exponential >= 0.0,
                who + ": the pre-exponential factor is finite and not negative");
        require(finite(rate.activation_temperature_k) && rate.activation_temperature_k >= 0.0,
                who + ": the activation temperature is finite and not negative");
        require(finite(rate.minimum_temperature_k) && finite(rate.maximum_temperature_k) &&
                    rate.minimum_temperature_k >= 0.0 &&
                    rate.maximum_temperature_k > rate.minimum_temperature_k,
                who + ": the supported temperature range is empty");
        require(finite(rate.supply_coefficient_m_s) && rate.supply_coefficient_m_s >= 0.0,
                who + ": the supply coefficient is finite and not negative");
    }
    for (const auto &[material, parts] : composition_of) {
        double sum = 0.0;
        for (const auto &[substance, fraction] : parts) {
            require(substance < substances.size(), material + ": composition names a missing substance");
            sum += fraction;
        }
        require(std::abs(sum - 1.0) <= 1.0e-9, material + ": composition does not sum to one");
    }
}

double Model::heatOfReactionJPerKg(const Reaction &reaction, double temperature_k) const {
    double released = 0.0;
    for (const Term &term : reaction.reactants)
        released += term.kg_per_kg * specificEnthalpyJKg(substances.at(term.substance), temperature_k);
    for (const Term &term : reaction.products)
        released -= term.kg_per_kg * specificEnthalpyJKg(substances.at(term.substance), temperature_k);
    return released;
}

bool Model::isFuel(std::size_t substance) const {
    for (const Reaction &reaction : reactions)
        if (reaction.reactants.front().substance == substance &&
            heatOfReactionJPerKg(reaction, kQuotedTemperatureK) > 0.0)
            return true;
    return false;
}

Model demonstrationModel() {
    Model model;
    model.id = "banjo-demonstration";
    model.version = "1";

    // Gases. cp at 300 K from ideal-gas tables; cv is cp less R/M, held
    // constant. Argon's is exact: a monatomic ideal gas has cv = 3R/2M.
    const auto gas = [&](const char *id, double molar_mass, double cp_300, const char *note) {
        Substance s;
        s.id = id;
        s.phase = Phase::Gas;
        s.molar_mass_kg_mol = molar_mass;
        s.cv_j_kg_k = cp_300 - kGasConstantJMolK / molar_mass;
        s.provenance = Provenance::ReferenceDerived;
        s.note = note;
        return model.add(std::move(s));
    };
    const std::size_t oxygen = gas("oxygen", 0.031998, 918.0, "cp 918 J/kg K at 300 K");
    gas("nitrogen", 0.028014, 1040.0, "cp 1040 J/kg K at 300 K");
    {
        Substance argon;
        argon.id = "argon";
        argon.phase = Phase::Gas;
        argon.molar_mass_kg_mol = 0.039948;
        argon.cv_j_kg_k = 1.5 * kGasConstantJMolK / argon.molar_mass_kg_mol;
        argon.provenance = Provenance::ReferenceDerived;
        argon.note = "monatomic ideal gas: cv = 3R/2M exactly";
        model.add(std::move(argon));
    }
    const std::size_t carbon_dioxide =
        gas("carbon dioxide", 0.044009, 846.0, "cp 846 J/kg K at 300 K; rises to 1.2 kJ/kg K by 1000 K, held constant here");

    // Liquid water held in a material, and the vapour it becomes. The vapour's
    // reference energy is set so that turning the liquid into vapour at
    // 373.15 K takes the latent heat of vaporisation, 2.257 MJ/kg, with the
    // constant heat capacities used everywhere else.
    Substance moisture;
    moisture.id = "moisture";
    moisture.phase = Phase::Liquid;
    moisture.cv_j_kg_k = 4186.0;
    moisture.conductivity_w_m_k = 0.6;
    moisture.provenance = Provenance::ReferenceDerived;
    moisture.note = "liquid water held in a material";
    const double liquid_cv = moisture.cv_j_kg_k;
    const std::size_t water = model.add(std::move(moisture));
    Substance vapour;
    vapour.id = "water vapour";
    vapour.phase = Phase::Gas;
    vapour.molar_mass_kg_mol = 0.018015;
    vapour.cv_j_kg_k = 1872.0 - kGasConstantJMolK / vapour.molar_mass_kg_mol;
    constexpr double kBoilingK = 373.15;
    constexpr double kLatentJKg = 2.257e6;
    vapour.reference_energy_j_kg = kLatentJKg + (liquid_cv - 1872.0) * kBoilingK;
    vapour.provenance = Provenance::ReferenceDerived;
    vapour.note = "latent heat 2.257 MJ/kg at 373.15 K with cp 1872 J/kg K";
    const std::size_t steam = model.add(std::move(vapour));

    // Inert solids: what the catalogue's materials are made of when nothing in
    // them reacts. Room-temperature handbook values.
    const auto solid = [&](const char *id, double cv, double conductivity, double emissivity,
                           Provenance provenance, const char *note) {
        Substance s;
        s.id = id;
        s.phase = Phase::Solid;
        s.cv_j_kg_k = cv;
        s.conductivity_w_m_k = conductivity;
        s.emissivity = emissivity;
        s.provenance = provenance;
        s.note = note;
        return model.add(std::move(s));
    };
    solid("iron", 449.0, 80.2, 0.7, Provenance::ReferenceDerived, "oxidised surface");
    solid("aluminium", 897.0, 237.0, 0.2, Provenance::ReferenceDerived, "lightly oxidised surface");
    solid("soda-lime glass", 840.0, 1.0, 0.92, Provenance::ReferenceDerived, "");
    solid("alumina", 880.0, 30.0, 0.8, Provenance::ReferenceDerived, "");
    solid("rubber", 2000.0, 0.16, 0.9, Provenance::ReferenceDerived,
          "no reaction is declared for rubber: it heats and does not burn here");
    solid("ice", 2100.0, 2.2, 0.97, Provenance::ReferenceDerived,
          "melting is not modelled in this model");
    solid("concrete", 880.0, 1.4, 0.9, Provenance::ReferenceDerived, "");
    const std::size_t ash = solid("ash", 800.0, 0.1, 0.9, Provenance::Demonstration,
                                  "the incombustible residue of wood");

    // Dry wood. Its reference energy is set so the combustion below releases a
    // lower heating value of 16.0 MJ/kg at 298.15 K -- a demonstration value
    // inside the 15-18 MJ/kg range quoted for dry hardwoods.
    constexpr double kWoodHeatingValueJKg = 16.0e6;
    constexpr double kWoodCv = 1500.0;
    // Cellulose, C6H10O5, burned completely: per kg, 1.18408 kg of oxygen in
    // and 1.62855 kg of carbon dioxide and 0.55553 kg of water vapour out.
    constexpr double kOxygenPerWood = 1.18408;
    constexpr double kCarbonDioxidePerWood = 1.62855;
    constexpr double kVapourPerWood = 0.55553;
    const double t0 = kQuotedTemperatureK;
    const double others = kOxygenPerWood * specificEnthalpyJKg(model[oxygen], t0) -
                          kCarbonDioxidePerWood * specificEnthalpyJKg(model[carbon_dioxide], t0) -
                          kVapourPerWood * specificEnthalpyJKg(model[steam], t0);
    Substance wood;
    wood.id = "dry wood";
    wood.phase = Phase::Solid;
    wood.cv_j_kg_k = kWoodCv;
    wood.conductivity_w_m_k = 0.16;
    wood.emissivity = 0.9;
    wood.reference_energy_j_kg = kWoodHeatingValueJKg - kWoodCv * t0 - others;
    wood.provenance = Provenance::Demonstration;
    wood.note = "heating value 16.0 MJ/kg at 298.15 K, declared";
    const std::size_t dry_wood = model.add(std::move(wood));

    // An abstract finite-inventory rapid reaction: a stand-in for a propellant,
    // NOT a model of gunpowder. It carries its own oxidiser (nothing comes from
    // the surroundings), releases 2.8 MJ/kg at 298.15 K, and turns 56% of its
    // mass into gas. Everything about it is a demonstration value.
    Substance residue;
    residue.id = "propellant residue";
    residue.phase = Phase::Solid;
    residue.cv_j_kg_k = 900.0;
    residue.conductivity_w_m_k = 0.3;
    residue.provenance = Provenance::Demonstration;
    const std::size_t propellant_residue = model.add(std::move(residue));
    Substance propellant_gas;
    propellant_gas.id = "propellant gas";
    propellant_gas.phase = Phase::Gas;
    propellant_gas.molar_mass_kg_mol = 0.030;
    propellant_gas.cv_j_kg_k = 1300.0 - kGasConstantJMolK / 0.030;
    propellant_gas.provenance = Provenance::Demonstration;
    const std::size_t product_gas = model.add(std::move(propellant_gas));
    constexpr double kPropellantJKg = 2.8e6;
    Substance propellant;
    propellant.id = "propellant";
    propellant.phase = Phase::Solid;
    propellant.cv_j_kg_k = 1200.0;
    propellant.conductivity_w_m_k = 0.3;
    propellant.provenance = Provenance::Demonstration;
    propellant.reference_energy_j_kg =
        kPropellantJKg - propellant.cv_j_kg_k * t0 +
        0.44 * specificEnthalpyJKg(model[propellant_residue], t0) +
        0.56 * specificEnthalpyJKg(model[product_gas], t0);
    propellant.note = "abstract rapid reaction, 2.8 MJ/kg, declared";
    const std::size_t charge = model.add(std::move(propellant));

    {
        Reaction burn;
        burn.id = "wood combustion";
        burn.version = "1";
        burn.provenance = Provenance::Demonstration;
        burn.description =
            "declared simplified wood model: one-step combustion of dry wood at its exposed "
            "surface, Arrhenius kinetics in series with the oxygen the surrounding air can "
            "deliver. Stoichiometry is cellulose's; the kinetic and transport numbers are "
            "demonstration values, not validated against ventilation, moisture or geometry";
        burn.reactants = {{dry_wood, 1.0, Supply::Material, Fate::Retained},
                          {oxygen, kOxygenPerWood, Supply::Environment, Fate::Retained}};
        burn.products = {{carbon_dioxide, kCarbonDioxidePerWood, Supply::Material, Fate::Released},
                         {steam, kVapourPerWood, Supply::Material, Fate::Released}};
        burn.rate = {RateKind::Surface, 2000.0, 10000.0, 500.0, 2000.0, 0.02};
        model.addReaction(std::move(burn));
    }
    {
        Reaction dry;
        dry.id = "drying";
        dry.version = "1";
        dry.provenance = Provenance::Demonstration;
        dry.description =
            "held moisture evaporating from the exposed surface: 0.015 kg/m2 s at 373.15 K, "
            "Arrhenius in temperature, nothing below 300 K. The latent heat comes from the "
            "reference energies, so drying cools what it dries";
        dry.reactants = {{water, 1.0, Supply::Material, Fate::Retained}};
        dry.products = {{steam, 1.0, Supply::Material, Fate::Released}};
        constexpr double kDryingTa = 4800.0;
        dry.rate = {RateKind::Surface, 0.015 * std::exp(kDryingTa / kBoilingK), kDryingTa, 300.0,
                    700.0, 0.0};
        model.addReaction(std::move(dry));
    }
    {
        Reaction flash;
        flash.id = "rapid reaction";
        flash.version = "1";
        flash.provenance = Provenance::Demonstration;
        flash.description =
            "an abstract finite-inventory rapid reaction carrying its own oxidiser, first order "
            "throughout the material. A stand-in for a propellant, not a model of one";
        flash.reactants = {{charge, 1.0, Supply::Material, Fate::Retained}};
        flash.products = {{product_gas, 0.56, Supply::Material, Fate::Released},
                          {propellant_residue, 0.44, Supply::Material, Fate::Retained}};
        flash.rate = {RateKind::Volume, 2.0e9, 15000.0, 450.0, 4000.0, 0.0};
        model.addReaction(std::move(flash));
    }

    model.setComposition("iron", {{"iron", 1.0}});
    model.setComposition("aluminum", {{"aluminium", 1.0}});
    model.setComposition("glass", {{"soda-lime glass", 1.0}});
    model.setComposition("alumina ceramic", {{"alumina", 1.0}});
    model.setComposition("rubber", {{"rubber", 1.0}});
    model.setComposition("ice", {{"ice", 1.0}});
    model.setComposition("concrete", {{"concrete", 1.0}});
    // Seasoned oak, on a demonstration basis: mostly dry wood, a tenth water,
    // a little ash. This is what makes an oak log able to burn.
    model.setComposition("oak", {{"dry wood", 0.88}, {"moisture", 0.10}, {"ash", 0.02}});
    (void)ash;
    model.validate();
    return model;
}

Parcel emptyParcel(const Model &model) {
    return {std::vector<double>(model.size(), 0.0), 0.0};
}

Parcel parcelAt(const Model &model, std::vector<double> kg, double temperature_k) {
    require(kg.size() == model.size(), "a parcel has one mass per substance in its model");
    require(finite(temperature_k) && temperature_k >= 0.0, "a temperature is finite and not negative");
    Parcel parcel{std::move(kg), 0.0};
    for (std::size_t i = 0; i < parcel.kg.size(); ++i) {
        require(finite(parcel.kg[i]) && parcel.kg[i] >= 0.0, "a mass is finite and not negative");
        parcel.internal_energy_j += parcel.kg[i] * specificEnergyJKg(model[i], temperature_k);
    }
    return parcel;
}

double massKg(const Parcel &parcel) {
    double total = 0.0;
    for (const double kg : parcel.kg) total += kg;
    return total;
}

double heatCapacityJK(const Model &model, const Parcel &parcel) {
    double total = 0.0;
    for (std::size_t i = 0; i < parcel.kg.size(); ++i) total += parcel.kg[i] * model[i].cv_j_kg_k;
    return total;
}

double referenceEnergyJ(const Model &model, const Parcel &parcel) {
    double total = 0.0;
    for (std::size_t i = 0; i < parcel.kg.size(); ++i)
        total += parcel.kg[i] * model[i].reference_energy_j_kg;
    return total;
}

double temperatureK(const Model &model, const Parcel &parcel) {
    const double capacity = heatCapacityJK(model, parcel);
    if (!(capacity > 0.0)) return 0.0;
    return (parcel.internal_energy_j - referenceEnergyJ(model, parcel)) / capacity;
}

double gasMoles(const Model &model, const Parcel &parcel) {
    double moles = 0.0;
    for (std::size_t i = 0; i < parcel.kg.size(); ++i)
        if (model[i].phase == Phase::Gas) moles += parcel.kg[i] / model[i].molar_mass_kg_mol;
    return moles;
}

double pressurePa(const Model &model, const Parcel &parcel, double volume_m3) {
    require(volume_m3 > 0.0, "a gas needs a volume to have a pressure");
    return gasMoles(model, parcel) * kGasConstantJMolK * temperatureK(model, parcel) / volume_m3;
}

Parcel takeShare(Parcel &from, double fraction) {
    const double f = std::clamp(fraction, 0.0, 1.0);
    Parcel taken{std::vector<double>(from.kg.size(), 0.0), 0.0};
    if (f == 1.0) {
        std::swap(taken, from);
        from.kg.assign(taken.kg.size(), 0.0);
        from.internal_energy_j = 0.0;
        return taken;
    }
    for (std::size_t i = 0; i < from.kg.size(); ++i) {
        taken.kg[i] = from.kg[i] * f;
        from.kg[i] -= taken.kg[i];
    }
    taken.internal_energy_j = from.internal_energy_j * f;
    from.internal_energy_j -= taken.internal_energy_j;
    return taken;
}

void pour(Parcel &into, const Parcel &from) {
    if (into.kg.size() < from.kg.size()) into.kg.resize(from.kg.size(), 0.0);
    for (std::size_t i = 0; i < from.kg.size(); ++i) into.kg[i] += from.kg[i];
    into.internal_energy_j += from.internal_energy_j;
}

} // namespace banjo::thermo
