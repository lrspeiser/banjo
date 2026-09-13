#pragma once

// What heat, composition and burning do to what a body can carry.
//
// ThermoWorld says how hot each body's surface layer and core are, what they
// hold and how much of it has been used. This turns that into mechanical
// properties, per MATERIAL, by a declared law with its sources -- the same
// arrangement the reactions have. Nothing here says "hot means weak": oak has
// lost most of its shear strength by 200 degC while iron has lost none of its
// yield strength below 400 degC, because that is what the sources say, and a
// material with no law is not changed at all.
//
// A body is one surface layer over one core, or one lump when it conducts
// well enough to be one temperature. So a section across the direction a body
// carries load is at most three rings:
//
//     what burned away     gone -- worked out from the load-bearing matter used
//     the surface layer    at the surface's temperature; char, and carrying
//                          nothing, once its hottest passed the char point
//     the core             at the core's temperature
//
// each carrying its share at its own reduction factor. That is the resolution
// the thermal model has, and it is said everywhere the answer is used: a thick
// beam's char front creeping inwards is NOT resolved inside the core.
//
// docs/thermal-mechanics.md is the whole model: the laws and where their
// numbers come from, what is reversible, and how failure is decided.
#include "core/Math.hpp"
#include "thermo/Thermochemistry.hpp"

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace banjo::thermo {

// Every factor below is against the same matter at this temperature.
inline constexpr double kReferenceTemperatureK = 293.15;

// A reduction factor against temperature: straight lines between points, held
// at the first and the last value beyond them. Empty means 1 everywhere.
struct ReductionCurve {
    std::vector<std::pair<double, double>> points;   // (kelvin, factor), ascending
    [[nodiscard]] double at(double temperature_k) const;
    [[nodiscard]] bool empty() const { return points.empty(); }
};

struct MechanicalLaw {
    // The catalogue's name for the material this law is about: "oak", "iron".
    std::string material;
    std::string id;
    std::string version;
    Provenance provenance{Provenance::Demonstration};
    // Where the curves come from, in words a reader can look up.
    std::string source;
    // The substance whose inventory IS the load-bearing matter -- dry wood in
    // oak -- and its mass fraction in the material's reference composition.
    // A body declared with less of it carries less, in proportion; what burns
    // of it is taken out of the section.
    std::string load_bearing;
    double reference_fraction{1.0};

    // REVERSIBLE: the factor at the temperature a zone is at now. Stiffness is
    // the modulus; the strengths are the ones a failure is decided by.
    ReductionCurve stiffness, tension, compression, shear;

    // IRREVERSIBLE, decided by the hottest a zone has ever been.
    //   char_k     a zone whose peak reached this is char and carries nothing,
    //              for good. Zero: the material does not char.
    //   permanent  the most a zone can have once its peak has reached T,
    //              whatever it cools to. Empty: nothing is lost for good.
    //   recovers   false: the peak governs outright -- the material keeps the
    //              factor its hottest moment gave it and nothing comes back.
    double char_k{};
    ReductionCurve permanent;
    std::string permanent_source;
    bool recovers{true};

    // Where the curves are supported, and the hottest a body may have been for
    // its recovery on cooling to be modelled. Outside these the answer is
    // still given -- and said to be outside.
    double supported_from_k{kReferenceTemperatureK};
    double supported_to_k{};
    double recovery_to_k{};
    std::vector<std::string> not_modelled;
};

// The laws the playground runs. Every curve says where it came from.
[[nodiscard]] const std::vector<MechanicalLaw> &mechanicalLaws();
// Null when this material has no law: heat then changes nothing about what it
// can carry, and every report says so rather than implying it was checked.
[[nodiscard]] const MechanicalLaw *lawFor(std::string_view material);

// What the thermal network knows about one body's matter that decides its
// strength. See ThermoWorld::matter.
struct MatterState {
    std::string body;
    std::string material;
    double surface_k{kReferenceTemperatureK};
    double core_k{kReferenceTemperatureK};
    double peak_surface_k{kReferenceTemperatureK};
    double peak_core_k{kReferenceTemperatureK};
    // A surface layer over a core, and how deep the layer is. A body that
    // conducts well enough to be one temperature has no core.
    bool layered{};
    double layer_depth_m{};
    // Of the load-bearing substance the body started with, the share that is
    // gone -- burned, and left as gas.
    double consumed_fraction{};
    // Its load-bearing share when it was declared, against the material's
    // reference: 1 for a catalogue body, less for one declared with less.
    double composition_factor{1.0};
};

// One zone's factors against the same matter cold.
struct ZoneFactors {
    double stiffness{1.0};
    double tension{1.0};
    double compression{1.0};
    double shear{1.0};
};

// A section of one body across the direction it carries load.
struct SectionState {
    // As authored.
    double breadth_m{};
    double depth_m{};
    // How far burning has eaten in from every face, the char under that, and
    // the surface layer's depth.
    double consumed_m{};
    double char_m{};
    double layer_m{};
    // What still carries anything: the section inside the char.
    double sound_breadth_m{};
    double sound_depth_m{};
    // Against the same section cold and whole; 1 is as it was.
    double axial_stiffness{1.0};   // E A
    double tension{1.0};
    double compression{1.0};
    double shear{1.0};
    double bending{1.0};           // the tension side: M = f Z
    // The zones themselves.
    ZoneFactors surface;
    ZoneFactors core;
    // What the section would keep if it cooled to the reference temperature
    // now: what burned away, the char and any permanent loss stay.
    double stiffness_if_cooled{1.0};
    double tension_if_cooled{1.0};
    double shear_if_cooled{1.0};
    double bending_if_cooled{1.0};
    bool supported{true};
    std::string outside;           // why not, when not
};

// `box_m` is the body's own box, and `length_axis` (0, 1, 2) the axis of that
// box the load runs along: the section is the other two. For bending,
// `depth_axis` is the one of those two it bends about -- the other is its
// breadth -- and -1 takes the larger. Burning eats in from every face of the
// box alike: a DECLARED approximation (docs/thermal-mechanics.md).
[[nodiscard]] SectionState evaluateSection(const MechanicalLaw &law, const MatterState &matter,
                                           const Vec3 &box_m, int length_axis,
                                           int depth_axis = -1);

// How far a box has burned in from every face when this share of it is gone.
[[nodiscard]] double recessionDepthM(const Vec3 &box_m, double consumed_fraction);

}  // namespace banjo::thermo
