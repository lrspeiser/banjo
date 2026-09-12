#pragma once

// Substances, reactions and parcels of matter: the vocabulary of the
// thermochemical network.
//
// ONE ENERGY CONVENTION, used everywhere below and never mixed with another.
// Every substance has a specific internal energy
//
//     u(T) = u0 + cv * T            (J/kg, T in kelvin, measured from 0 K)
//
// where u0 is its REFERENCE energy on the model's scale and cv is constant over
// the model's declared validity range. A parcel's internal energy U is the one
// stored number; its temperature is DERIVED from it,
//
//     T = (U - sum m_i u0_i) / (sum m_i cv_i),
//
// and never assigned. "Chemical energy" and "thermal energy" are two views of
// that one U -- the reference part and the sensible part -- not two stores that
// are added together. A reaction that turns reactants into products at constant
// U raises the temperature because the products' reference energies are lower;
// nothing adds a separate "heat of reaction" on top, which is how a reacting
// model double-counts.
//
// A gas substance also carries flow work: its enthalpy is h = u0 + cp * T with
// cp = cv + R/M, and matter that crosses into or out of a parcel carries its
// enthalpy with it. The existing ThermalKernel measures sensible energy from 0 K
// in the same way, so the two agree where they overlap.
#include <cstddef>
#include <cstdint>
#include <functional>
#include <map>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace banjo::thermo {

inline constexpr double kGasConstantJMolK = 8.314462618;
inline constexpr double kStefanBoltzmannWM2K4 = 5.670374419e-8;
// The temperature a heating value is quoted at.
inline constexpr double kQuotedTemperatureK = 298.15;

enum class Phase : std::uint8_t { Solid, Liquid, Gas };

// Where a number came from. Printed next to every substance and reaction, so a
// demonstration parameter is never mistaken for a measurement.
enum class Provenance : std::uint8_t { Demonstration, ReferenceDerived, ExperimentallyValidated };

[[nodiscard]] std::string_view provenanceName(Provenance provenance);
[[nodiscard]] std::string_view phaseName(Phase phase);

struct Substance {
    std::string id;
    Phase phase{Phase::Solid};
    // Needed for anything that is, or can become, a gas.
    double molar_mass_kg_mol{};
    double cv_j_kg_k{};
    double reference_energy_j_kg{};
    // What a solid body made mostly of this conducts and radiates like.
    double conductivity_w_m_k{};
    double emissivity{0.9};
    Provenance provenance{Provenance::ReferenceDerived};
    std::string note;
};

// R/M for a gas; zero for anything condensed.
[[nodiscard]] double gasConstantJKgK(const Substance &substance);
[[nodiscard]] double cpJKgK(const Substance &substance);
[[nodiscard]] double specificEnergyJKg(const Substance &substance, double temperature_k);
// u for a condensed substance, u + RT/M for a gas.
[[nodiscard]] double specificEnthalpyJKg(const Substance &substance, double temperature_k);

// Where a reactant comes from. Oxygen for a fire comes from the air around it;
// the oxidiser in a propellant is already in the material. A reaction that
// needs the environment cannot run where there is none, and "requires oxygen"
// is a property of the reaction, never of the material.
enum class Supply : std::uint8_t { Material, Environment };
// Where a product goes: stays in the matter (ash, residue), or leaves it for
// the surroundings (flue gas, steam).
enum class Fate : std::uint8_t { Retained, Released };

struct Term {
    std::size_t substance{};
    double kg_per_kg{};
    Supply supply{Supply::Material};
    Fate fate{Fate::Retained};
};

// How fast. Surface: kg of the basis reactant per m2 of EXPOSED surface per
// second; Volume: the fraction of the basis reactant per second (first order).
// Either way multiplied by exp(-Ta / T). Below the minimum temperature the
// model declares the rate zero; above the maximum it is evaluated at the
// maximum and the step is counted as outside the supported range.
enum class RateKind : std::uint8_t { Surface, Volume };

struct RateLaw {
    RateKind kind{RateKind::Surface};
    double pre_exponential{};
    double activation_temperature_k{};
    double minimum_temperature_k{};
    double maximum_temperature_k{1.0e5};
    // A transport limit on the environment reactant, in series with the
    // kinetics: the most the surroundings can deliver is this coefficient
    // (m/s) times the reactant's density in them. Zero means unlimited.
    double supply_coefficient_m_s{};
};

struct Reaction {
    std::string id;
    std::string version;
    std::string description;
    Provenance provenance{Provenance::Demonstration};
    // reactants.front() is the BASIS: 1 kg of it per kg of extent, from the
    // material. Everything else is per kg of the basis.
    std::vector<Term> reactants;
    std::vector<Term> products;
    RateLaw rate;
};

struct Model {
    std::string id;
    std::string version;
    // Constant properties are declared valid in this range and no further.
    double minimum_temperature_k{150.0};
    double maximum_temperature_k{3000.0};
    std::vector<Substance> substances;
    std::vector<Reaction> reactions;
    // What a body of each catalogue material is made of, by mass fraction.
    // An oak block is combustible because of what it CONTAINS -- dry wood,
    // moisture and ash -- not because anything says oak burns.
    std::map<std::string, std::vector<std::pair<std::size_t, double>>, std::less<>> composition_of;

    std::size_t add(Substance substance);
    void addReaction(Reaction reaction);
    void setComposition(const std::string &material,
                        const std::vector<std::pair<std::string, double>> &fractions);
    [[nodiscard]] std::size_t index(std::string_view id) const;
    [[nodiscard]] bool has(std::string_view id) const;
    [[nodiscard]] std::size_t size() const { return substances.size(); }
    [[nodiscard]] const Substance &operator[](std::size_t i) const { return substances.at(i); }
    // Throws std::invalid_argument on anything a reaction could use to create
    // or destroy mass, or that names something that does not exist.
    void validate() const;
    // Energy released per kg of basis with reactants and products all at
    // `temperature_k` and released products as gas: the heating value the
    // reference energies imply. Reported; never added to anything.
    [[nodiscard]] double heatOfReactionJPerKg(const Reaction &reaction, double temperature_k) const;
    // Consumed by a reaction that releases heat at the quoted temperature.
    [[nodiscard]] bool isFuel(std::size_t substance) const;
};

// The model the playground runs. Every number in it says where it came from.
[[nodiscard]] Model demonstrationModel();

// A closed amount of matter: how much of each substance, and one internal energy.
struct Parcel {
    std::vector<double> kg;
    double internal_energy_j{};
};

[[nodiscard]] Parcel emptyParcel(const Model &model);
[[nodiscard]] Parcel parcelAt(const Model &model, std::vector<double> kg, double temperature_k);
[[nodiscard]] double massKg(const Parcel &parcel);
[[nodiscard]] double heatCapacityJK(const Model &model, const Parcel &parcel);
[[nodiscard]] double referenceEnergyJ(const Model &model, const Parcel &parcel);
// Zero for an empty parcel, which has no temperature to speak of.
[[nodiscard]] double temperatureK(const Model &model, const Parcel &parcel);
[[nodiscard]] double gasMoles(const Model &model, const Parcel &parcel);
[[nodiscard]] double pressurePa(const Model &model, const Parcel &parcel, double volume_m3);
// Moves `fraction` of everything in `from` -- each substance and the same share
// of its energy -- into the result. What is taken is exactly what is lost.
[[nodiscard]] Parcel takeShare(Parcel &from, double fraction);
void pour(Parcel &into, const Parcel &from);

} // namespace banjo::thermo
