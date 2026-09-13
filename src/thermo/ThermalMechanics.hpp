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
    // What each zone holds now, in kilograms: the surface layer (everything,
    // for a body that is one lump) and the core. Where that matter IS in the
    // body is the MaterialField's to say; how much there is, the network's.
    double surface_kg{};
    double core_kg{};
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
    // The compression side of the same bending, by the compression curve. A
    // beam gives on whichever side reaches its strength first: oak's declared
    // 52 MPa in compression is below its 90 MPa in tension, and its compression
    // curve falls faster (0.25 at 100 degC against 0.65), so for oak this side
    // governs -- in the lattice, which applies all three strengths, and in the
    // survey, which asks about both.
    double bending_compression{1.0};
    // The zones themselves.
    ZoneFactors surface;
    ZoneFactors core;
    // What the section would keep if it cooled to the reference temperature
    // now: what burned away, the char and any permanent loss stay.
    double stiffness_if_cooled{1.0};
    double tension_if_cooled{1.0};
    double shear_if_cooled{1.0};
    double bending_if_cooled{1.0};
    double bending_compression_if_cooled{1.0};
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

// ---- One material state (docs/thermal-mechanics.md, "One material state") ----
//
// Where, in a body, the matter the thermal network describes actually is. The
// network says how much has burned, how hot each zone is and has been, and how
// much each zone holds; this says which part of the body each of those is:
//
//     depth below the body's box    zone
//     less than consumed_m          burned away: no matter, no volume, gone
//     then layer_m more             the surface layer, at the surface's state
//     deeper                        the core, at the core's state
//
// Depth is measured to the nearest face of the body's REFERENCE box (the box
// it was authored as, or the cells' box a piece broke off as), and radially for
// a sphere. Every face recedes alike -- the declared approximation the section
// has always used. Everything that needs the state reads it from here, once:
//
//   * a cross-section is this field integrated over a rectangle (evaluateSection);
//   * a lattice cell is this field averaged over its own cube (cellShare), which
//     sets the cell's mass and its bonds' stiffness and strengths;
//   * the collision shape and the drawn shape are the part of the box that is
//     not burned away (remainingBox);
//   * mass, centre of mass and inertia are the zones' matter spread over the
//     zones' volumes (massProperties).
//
// So a factor is applied exactly once: a burned-away zone contributes nothing
// because it is not there, and every factor is against the SAME matter cold,
// never against a section that has already been reduced.
struct MaterialField {
    Vec3 box_m{};                 // the reference box
    bool round{};                 // a sphere of diameter box_m.x: depth runs radially
    bool has_law{};               // false: heat changes nothing about this matter
    double consumed_m{};          // burned away from every face
    double layer_m{};             // the surface layer inside that, when layered
    bool layered{};
    ZoneFactors surface, core;    // now, against the same matter cold (zero once char)
    ZoneFactors surface_cooled, core_cooled;   // if it cooled to the reference now
    bool surface_char{}, core_char{};
    double surface_kg{}, core_kg{};
};

[[nodiscard]] MaterialField materialField(const MechanicalLaw *law, const MatterState &matter,
                                          const Vec3 &box_m, bool round = false);

// The part of the reference box that is not burned away: the collision shape
// and the drawn shape of an authored box (for a sphere, x is its diameter).
[[nodiscard]] Vec3 remainingBox(const MaterialField &field);
// Volumes of what is left and of its core (zero when the body is one lump).
[[nodiscard]] double remainingVolumeM3(const MaterialField &field);
[[nodiscard]] double coreVolumeM3(const MaterialField &field);

// A lattice cell, a cube of side `cell_m` centred at `at_m` in the reference
// box's own frame (its centre at the origin, its axes the box's): the share of
// the cube's volume in each zone. `surface + core` is what is left of it; the
// rest burned away.
struct CellShare {
    double surface{};
    double core{};
    [[nodiscard]] double remaining() const { return surface + core; }
};
[[nodiscard]] CellShare cellShare(const MaterialField &field, const Vec3 &at_m, double cell_m);

// A cell's factors against the same cell cold and whole: each zone's factor
// times its share of the cell, added (a rule of mixtures, declared). What
// burned away and what is char contribute nothing.
[[nodiscard]] ZoneFactors cellFactors(const MaterialField &field, const CellShare &share);
// A cell's mass: each zone's matter, spread evenly over that zone's volume.
[[nodiscard]] double cellMassKg(const MaterialField &field, const CellShare &share, double cell_m);

// A bond joins two cells, half in each. Its stiffness is the two halves in
// series (the harmonic mean of the cells' stiffness factors); each strength is
// the lesser cell's -- a bond is as strong as its weaker end. Declared.
[[nodiscard]] ZoneFactors bondFactors(const ZoneFactors &a, const ZoneFactors &b);

// What is left, as a rigid body: mass, and the principal inertia about the
// centre of the reference box, which is where the centre of mass stays while
// every face recedes alike. The zones' matter spread over their volumes.
struct FieldMassProperties {
    double mass_kg{};
    Vec3 inertia_kg_m2{};   // about the box's own axes
};
[[nodiscard]] FieldMassProperties massProperties(const MaterialField &field);

// How far a point (in the reference box's frame) lies outside what is left,
// and outside the box as it was; zero when inside.
[[nodiscard]] double outsideRemainingM(const MaterialField &field, const Vec3 &at_m);
[[nodiscard]] double outsideReferenceM(const MaterialField &field, const Vec3 &at_m);

}  // namespace banjo::thermo
