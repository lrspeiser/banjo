#pragma once

// The thermochemical network: matter inventories on bodies, gas regions, heat
// paths, heaters and pressure-driven boundaries, with one energy ledger.
//
// It owns no geometry and no motion. The host (LiveWorld) says where bodies are
// and how they moved; this says what heat, chemistry and pressure did about it
// and which forces the mechanics must apply. Everything it holds is a value, so
// a copy is a save and assigning it back is a restore -- which is what lets a
// rejected rigid step take its chemistry back with it.
//
// THE LEDGER'S INVARIANT
//
//     change in stored energy = energy crossing the boundary + reported residual
//
// Stored energy is the internal energy of every parcel in the network (whose
// reference and sensible parts are shown separately but are one number).
// Crossings are: heater work in; heat to the surroundings (convection,
// radiation, the floor); enthalpy carried in and out by matter exchanged with
// the surroundings; boundary work delivered to bodies and to the atmosphere;
// and matter joining or leaving the network with a body. Every one of those is
// added up where it happens, so the residual measures the arithmetic and
// nothing else.
#include "core/Math.hpp"
#include "thermo/ThermalMechanics.hpp"
#include "thermo/Thermochemistry.hpp"

#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace banjo::thermo {

struct Ambient {
    double temperature_k{293.15};
    double pressure_pa{101325.0};
    // By substance, gases only, summing to one. Empty means dry air.
    std::vector<double> mass_fraction;
    // Declared: convection from a surface into still air, and conduction from
    // a body resting on the floor into the floor, per m2 and per kelvin.
    double film_coefficient_w_m2_k{10.0};
    double floor_conductance_w_m2_k{25.0};
    // Declared: contact between two touching bodies, per m2 and per kelvin.
    double contact_conductance_w_m2_k{300.0};
};

// One body as the host sees it right now. Refreshed as things move.
struct BodyShape {
    std::string name;
    std::string material;
    Vec3 center_m{};
    // Half extents of the body's world-aligned bounding box as it is turned now.
    Vec3 half_extent_m{};
    double area_m2{};
    double volume_m3{};
    double mass_kg{};
    bool anchored{};
};

// A force the mechanics must apply at a body's centre for the step about to
// be taken, and how that body actually moved over the step that was accepted.
struct Push {
    std::string body;
    Vec3 force_n{};
};
struct Moved {
    std::string body;
    Vec3 displacement_m{};
};

struct ContentsDeclaration {
    std::string body;
    // By mass fraction of the body's own mass. Empty means what its material
    // is made of.
    std::vector<std::pair<std::string, double>> mass_fraction;
    double temperature_k{};        // 0: the surroundings' temperature
    double layer_depth_m{-1.0};    // < 0: the model's default for its material
    std::string environment;       // "" the open air; otherwise a gas region
};

struct GasRegionDeclaration {
    std::string name;
    std::vector<std::pair<std::string, double>> mass_fraction;
    double temperature_k{};        // 0: the surroundings' temperature
    double pressure_pa{};          // 0 with `balance`: whatever holds the piston up
    bool balance{};
    double volume_m3{};            // one of these two
    double height_m{};
    std::string piston;            // the body the gas pushes on
    std::string container;         // "" if the cylinder is fixed in the world
    Vec3 axis{0.0, 1.0, 0.0};      // the way the region grows as the piston moves
    double area_m2{};              // 0: the piston's cross-section across the axis
    double wall_conductance_w_k{-1.0}; // < 0: from the column's own surface
    double vent_area_m2{};         // an opening to the surroundings; 0 is sealed
    bool vent_open{true};
    // A NOZZLE: the body the region is held in, and the way gas leaves the
    // vent. Name a vessel and the momentum of what leaves pushes it the other
    // way -- which is a rocket. Leave it empty and the gas still leaves, it
    // just pushes nothing, which is a safety valve.
    std::string vessel;
    Vec3 vent_axis{0.0, -1.0, 0.0};
};

// What a body CARRIES, as against what it is made of: the water in a kettle,
// the sand in a pail.
//
// It is not the same thing as contents and must not be declared as them.
// Contents say what the body IS -- by fraction of its own mass, load-bearing,
// deciding its strength, and gone from its shape when they burn away. A
// kettle's water is none of that: pour it out and the kettle is the same
// kettle. But it is really there. It has to be warmed, it weighs something the
// mechanics has to carry, and it can boil -- and when it does, the steam goes
// into the gas region the body stands in, exactly as a reaction's would.
//
// Poured IN. Call it again and it pours more in; `release` pours out.
struct CargoDeclaration {
    std::string body;
    // Absolute kilograms, not fractions of anything.
    std::vector<std::pair<std::string, double>> kg;
    double temperature_k{};          // 0: the surroundings' temperature
    // Between what it holds and the body holding it. < 0: worked out from the
    // body's own surface, which is what a vessel's wall is.
    double conductance_w_k{-1.0};
};

struct HeaterDeclaration {
    std::string target;            // a body or a gas region
    double power_w{};
    double start_s{};              // on the network's clock
    double seconds{};
    std::string label{"heater"};
};

struct Lump {
    std::string body;
    std::string material;
    // The layer that meets the world -- it is heated, radiates, reacts -- and
    // the rest of the body behind it. A body that conducts well enough to be
    // one temperature throughout has everything in `surface` and nothing here.
    Parcel surface;
    Parcel core;
    // What it carries rather than what it is (CargoDeclaration): its own
    // parcel at its own temperature, in contact with the surface through
    // `cargo_conductance_w_k`. Kept apart from the two above so that a
    // kettle's water is never mistaken for the kettle: it is not in
    // `initial_kg`, it bears no load, and it does not shrink the body when it
    // boils away.
    Parcel cargo;
    double cargo_conductance_w_k{};
    double layer_depth_m{};
    // How much fuel the burning front keeps in the layer: when the layer's fuel
    // falls below this, the front advances into the core and brings its matter.
    double layer_fuel_kg{};
    // The same for melting: how much of what melts (ice) the melting front
    // keeps in the layer. As the layer's melts away, the core comes to the
    // surface to take its place.
    double layer_melt_kg{};
    double area_m2{};
    double exposed_area_m2{};
    double volume_m3{};
    double emissivity{0.9};
    double conductivity_w_m_k{};
    double core_conductance_w_k{};
    bool declared{};
    bool anchored{};
    int environment{-1};           // index of a gas region, or -1 for the open air
    double mirrored_mass_kg{};
    // What the body held when it joined the network, substance by substance.
    // How much of its load-bearing matter has been used is measured against
    // this (thermo/ThermalMechanics.hpp), so it is shared out by share when the
    // body breaks, like everything else it holds.
    std::vector<double> initial_kg;
    // The hottest each zone has ever been. What heat does to a material that
    // does not come back when it cools -- char, what pyrolysis takes -- is
    // decided by these. They only go up, and they are part of the state a
    // refused step takes back.
    double peak_surface_k{};
    double peak_core_k{};
    // What happened over the last accepted step, for reporting.
    double heat_release_w{};
    double fuel_use_kg_s{};
    double heater_w{};
    double gained_w{};             // from other bodies, conduction and radiation
    double lost_w{};               // to the surroundings
    double melt_kg_s{};            // solid melted
    double boil_kg_s{};            // liquid boiled away into gas
    // Meltwater that has run off this body and that the host has not yet
    // taken to put somewhere (ThermoWorld::takeMeltwater). It has left the
    // network already -- counted as matter out when it melted -- so this is
    // only where it went, not what it holds. In the state, so a refused step
    // takes back the water it would have made.
    double meltwater_kg{};
    // Set aside with its body (ThermoWorld::park): out of the world, so no heat
    // path reaches it, nothing in it reacts and no heater warms it. Kept exactly
    // as it was put away, and still the network's -- on its ledger, not left it.
    bool parked{};
};

struct PistonBoundary {
    std::string body;
    std::string container;
    Vec3 axis{0.0, 1.0, 0.0};
    double area_m2{};
    double stroke_m{};             // how far it has moved since it was declared
    double base_volume_m3{};
    double minimum_volume_m3{};
    Vec3 base_m{};                 // where the column starts, for drawing
    double pushed_pressure_pa{};   // the pressure the force of this step was made from
    Vec3 pushed_force_n{};
    double work_to_bodies_j{};
    double work_to_atmosphere_j{};
};

struct GasRegion {
    std::string name;
    Parcel gas;
    double volume_m3{};
    std::optional<PistonBoundary> piston;
    double wall_conductance_w_k{};
    double vent_area_m2{};
    bool vent_open{};
    double heater_w{};
    double wall_loss_w{};
    double vent_flow_kg_s{};
    // The nozzle. `thrust_force_n` is made in pushes() from the pressure then,
    // and advance() charges it over the displacement that actually happened --
    // the same bargain the piston makes.
    std::string vessel;
    Vec3 vent_axis{0.0, -1.0, 0.0};
    Vec3 thrust_force_n{};
    double thrust_work_j{};
};

struct Heater {
    unsigned id{};
    HeaterDeclaration what;
};

// Heat and matter paths, worked out from geometry when the host refreshes it.
struct Contact {
    std::size_t a{}, b{};          // lump indices
    double area_m2{};
    double conductance_w_k{};
};
struct Sight {
    std::size_t a{}, b{};          // lump indices
    double exchange_area_m2{};     // A_a F_ab, the same seen from either end
    double emissivity{};           // the pair's effective emissivity
};

struct Ledger {
    // Now: the views of the one stored total.
    double reference_j{};
    double sensible_j{};
    double mass_kg{};
    // When the network started, and every crossing since (positive is IN).
    double initial_j{};
    double initial_mass_kg{};
    double heater_in_j{};
    double heat_to_surroundings_j{};
    double matter_in_j{}, matter_in_kg{};
    double matter_out_j{}, matter_out_kg{};
    double joined_j{}, joined_kg{};
    double left_j{}, left_kg{};
    double work_to_bodies_j{};
    double work_to_atmosphere_j{};
    // Energy the mechanical side handed the network as heat: the elastic energy
    // a spring stops holding when its matter softens at a fixed stretch -- and,
    // negative, what one takes back when it stiffens again as it cools. A
    // crossing like any other, so the ledger closes across a change of property.
    double mechanical_in_j{};
    // Energy the arithmetic itself had to add to keep a parcel physical (a gas
    // expanded past absolute zero in one step, say). Not a crossing: an
    // explicitly REPORTED numerical error, and zero in every run so far.
    double numerical_j{};
    // Steps spent with some parcel outside the model's declared range.
    unsigned long long out_of_range_steps{};

    [[nodiscard]] double storedJ() const { return reference_j + sensible_j; }
    [[nodiscard]] double netInJ() const {
        return heater_in_j - heat_to_surroundings_j + matter_in_j - matter_out_j + joined_j -
               left_j - work_to_bodies_j - work_to_atmosphere_j + mechanical_in_j;
    }
    // What is left once every crossing and every reported correction is
    // accounted for: rounding, and nothing else.
    [[nodiscard]] double residualJ() const {
        return storedJ() - initial_j - netInJ() - numerical_j;
    }
    [[nodiscard]] double massResidualKg() const {
        return mass_kg - initial_mass_kg - (matter_in_kg - matter_out_kg + joined_kg - left_kg);
    }
};

struct BodyHeat {
    std::string body;
    std::string material;
    double temperature_k{};
    double core_temperature_k{};
    double mass_kg{};
    double fuel_kg{};
    double heat_release_w{};
    double fuel_use_kg_s{};
    // Remaining fuel over the rate it is being used now: what the fire would
    // last if nothing about it changed. Infinite when nothing is burning.
    double remaining_s{std::numeric_limits<double>::infinity()};
    double heater_w{};
    double gained_w{};
    double lost_w{};
    bool reacting{};
    bool declared{};
    // Melting: how fast now, and how much of what it started with has melted
    // and run off.
    double melt_kg_s{};
    double melted_kg{};
    bool melting{};
    // Boiling: how fast now, and how much of what it started with has boiled
    // away. Where the body stands in a gas region the steam went into it and
    // is pressing; otherwise it went to the surroundings.
    double boil_kg_s{};
    double boiled_kg{};
    bool boiling{};
    // What it CARRIES (CargoDeclaration), and how warm that is. Empty and zero
    // for a body carrying nothing. `carrying_k` is the cargo's own temperature,
    // which is not the body's: a kettle of cold water on a hot plate is two
    // temperatures, and which one a person is asking about is the water.
    std::vector<std::pair<std::string, double>> carrying_kg;
    double carrying_k{};
    // Of what it was given, how much has boiled away.
    double carried_boiled_kg{};
    std::vector<std::pair<std::string, double>> contents_kg;
    // Set aside (ThermoWorld::park): held as it was put away, out of the world.
    bool parked{};
};

struct RegionState {
    std::string name;
    double temperature_k{};
    double pressure_pa{};
    double volume_m3{};
    double mass_kg{};
    double moles{};
    std::vector<std::pair<std::string, double>> contents_kg;
    std::string piston;
    Vec3 axis{};
    Vec3 base_m{};
    double area_m2{};
    double height_m{};
    double stroke_m{};
    double force_n{};
    double work_to_bodies_j{};
    double work_to_atmosphere_j{};
    double heater_w{};
    double wall_loss_w{};
    bool vent_open{};
    double vent_flow_kg_s{};
    // The nozzle: what it pushes, which way the jet goes, what it is pushing
    // with now and what that push has done in total. Empty and zero unless the
    // region names a vessel.
    std::string vessel;
    Vec3 vent_axis{};
    double thrust_n{};
    double thrust_work_j{};
};

// Everything that changes as the network runs. Copy to save; assign to restore.
struct ThermoState {
    double time_s{};
    std::vector<Lump> lumps;
    std::vector<GasRegion> regions;
    std::vector<Heater> heaters;
    std::vector<Contact> contacts;
    std::vector<Sight> sights;
    // Per lump: conductance to the surroundings by radiation's share of view
    // (the rest of its sky), and to the floor.
    std::vector<double> sky_fraction;
    std::vector<double> floor_conductance_w_k;
    Ledger ledger;
    unsigned next_heater{1};
    bool opened{};
};

class ThermoWorld {
public:
    explicit ThermoWorld(Model model = demonstrationModel());
    ~ThermoWorld();
    ThermoWorld(const ThermoWorld &) = delete;
    ThermoWorld &operator=(const ThermoWorld &) = delete;

    [[nodiscard]] const Model &model() const;
    // Before anything is declared.
    void setAmbient(Ambient ambient);
    [[nodiscard]] const Ambient &ambient() const;

    // Every body in the world, where it is now. The first call opens the
    // ledger; later calls rework the heat paths from the new positions, and a
    // body the network holds that is no longer there has left it. A body of
    // something that melts below the surroundings' temperature -- ice in a
    // warm room -- joins at once, at its melting point, however far it is from
    // anything hot: it can never be at the room's temperature.
    void refresh(const std::vector<BodyShape> &bodies, double floor_y_m);

    void declareContents(const ContentsDeclaration &declaration);
    void declareGasRegion(const GasRegionDeclaration &declaration);
    // Pour matter INTO a body that is not part of it (CargoDeclaration). The
    // body is drawn into the network if it is not already. Between steps.
    void carry(const CargoDeclaration &declaration);
    // And pour it out: takes up to `kg` of `substance`, and answers what it
    // actually had and the temperature that left at, so a caller pouring from
    // one vessel into another can put it in at the heat it came out at. What
    // leaves is matter out of the network until it is carried somewhere else.
    [[nodiscard]] std::pair<double, double> release(const std::string &body,
                                                    const std::string &substance, double kg);
    unsigned heat(const HeaterDeclaration &declaration);
    // Draw a body into the network now, as heat() would on its first heater:
    // for a coil wound on it that will warm it from some later step.
    void enroll(const std::string &body);
    void setVent(const std::string &region, bool open);

    // The forces for the step about to be taken, from the state as accepted.
    // Must be called inside the step's reversible trial: it records the
    // pressure the force was made from, and advance() charges the gas for
    // exactly that pressure over exactly the displacement that happened.
    [[nodiscard]] std::vector<Push> pushes();
    // The step that was accepted: `moved` is how far each pushed body went.
    void advance(double dt_s, const std::vector<Moved> &moved);

    // A body replaced by pieces: `pieces` are names and the share of its
    // matter each holds (by cells), summing to one. A share that names the
    // body itself means it came through whole.
    void split(const std::string &body, const std::vector<std::pair<std::string, double>> &pieces);
    // A body gone from the world with whatever it held.
    void remove(const std::string &body);
    // A body set aside -- out of the world, not gone (LiveWorld::park) -- and
    // brought back. While it is away its lump is kept exactly as it was put
    // away: no heat path reaches it, nothing in it reacts, no heater warms it,
    // its surface and core do not even out, and the host's refreshes do not
    // count it as having left. Time stands still for it (a September 20 change
    // that let its surface and core even out was taken back on September 21:
    // docs/material-collection-contract.md). It is on the ledger the whole
    // time, because it never left the network. A body the network does not
    // hold has nothing to keep and is only forgotten as a shape. Between
    // steps, like refresh().
    void park(const std::string &body);
    // Back: coupled again by the host's next refresh, from where it is put.
    void unpark(const std::string &body);

    [[nodiscard]] const ThermoState &state() const;
    void restore(const ThermoState &state);

    [[nodiscard]] double timeS() const;
    // Whether there is anything here at all.
    [[nodiscard]] bool active() const;
    [[nodiscard]] bool holds(const std::string &body) const;
    [[nodiscard]] std::vector<BodyHeat> bodies() const;
    [[nodiscard]] std::vector<RegionState> regions() const;
    [[nodiscard]] Ledger ledger() const;
    // What decides a body's strength (thermo/ThermalMechanics.hpp): its zones'
    // temperatures now and at their hottest, its layer, how much of its
    // load-bearing matter is gone, and its load-bearing share when it was
    // declared. Empty when the network does not hold the body: nothing has
    // heated it, so it is as it was.
    [[nodiscard]] std::optional<MatterState> matter(const std::string &body) const;
    // Heat handed to a body's matter by the mechanical side, counted as a
    // crossing (Ledger::mechanical_in_j); negative takes it back out. A body the
    // network does not hold is drawn in first. Between steps, like refresh().
    void receiveMechanicalWork(const std::string &body, double joules);
    // Bodies whose matter has changed by more than `relative` since the host
    // last set their mass. Marks them set.
    [[nodiscard]] std::vector<std::pair<std::string, double>> massesToMirror(double relative = 1.0e-3);
    // Meltwater that has run off each body since this was last asked, in
    // kilograms, for the host to put where it goes -- into the room's water,
    // or off across the floor. Asking takes it: each kilogram is handed over
    // once. Between steps, and only after a step has been accepted.
    [[nodiscard]] std::vector<std::pair<std::string, double>> takeMeltwater();
    // What is modelled and what is not, in words, for anyone reporting on it.
    [[nodiscard]] static std::vector<std::string> limitations();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo::thermo
