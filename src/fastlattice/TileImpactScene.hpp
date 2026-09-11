#pragma once

// The scene the fast-gpu lane is judged on: a uniform-cube tile struck by a
// rigid ball, fracturing on the explicit lattice, the pieces handed to Jolt to
// fall and settle, the whole thing recorded as banjo.playback.v1.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/Refracture.hpp"
#include "fracture/ActiveMatter.hpp"
#include "material/Material.hpp"
#include "material/MaterialCatalog.hpp"
#include "matter/BoxLattice.hpp"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace banjo::fastlattice {

enum class SceneLayout : std::uint8_t {
    Flat,   // tile lying on the ground (one support plane; BrittleBondSolver can express it)
    Bridge, // tile resting on two ledges above the ground; middle pieces fall
};
enum class BackendKind : std::uint8_t { Cpu, Cuda, CpuParallel };
// Node-to-node contact inside the lattice phase. Off reproduces the lane before
// the contact existed, bit for bit; Measure runs the broad and narrow phases and
// records the worst overlap without applying any response, which is how the
// "before" interpenetration is measured on the same scene; On applies it.
enum class NodeContactMode : std::uint8_t { Off, Measure, On };

// One lattice object in a many-object scene.
//
// The solver never asks what material it is stepping: node mass is per node,
// and compliance and all six damage thresholds are per bond. So one lattice can
// hold a glass plate, an oak block and an iron ball at once. What keeps them
// separate objects is that no bond crosses between them; what makes them meet
// is node-to-node contact, which acts on any pair no live bond joins.
//
// Every body in a scene shares the request's cell size, because the solver's
// contact radius and support offset are one number for the whole lattice.
// Box, ball, and a round shape whose width changes with height: dimensions are
// the top diameter, the height and the bottom diameter, so one shape covers a
// cone, a funnel, a cylinder and everything between. A bowl shaped like an
// upside-down cone is one of these with a narrower one cut out of it.
enum class BodyShape : std::uint8_t { Box, Sphere, Cone };

struct SceneBody {
    std::string name{"body"};
    BodyShape shape{BodyShape::Box};
    MaterialPreset material{MaterialPreset::Glass};
    // Box: the three extents. Sphere: x is the diameter, y and z are ignored.
    // Cone: x is the diameter at the top, y the height, z the diameter at the
    // bottom.
    Vec3 dimensions_m{0.1, 0.1, 0.1};
    Vec3 center_m{};      // where its centre of mass sits at t = 0
    Vec3 velocity_m_s{};  // what it is already doing at t = 0
    // Spin at t = 0, radians per second, about the body's own centre.
    // Nothing in either phase turns sliding into rolling: friction slows a
    // body and applies no torque to it, so a ball given only a linear
    // velocity slides the whole way without ever turning. A ball that is
    // meant to roll has to be given the spin that goes with its speed,
    // which for rolling without slipping along +x is -v/radius about z.
    Vec3 spin_rad_s{};
    // Rotation about the body's own centre at t = 0, degrees, applied x then y
    // then z. Without it every object is axis aligned and a ramp has to be
    // built as a staircase of boxes, which collide with each other and with
    // whatever stands on them. A tilted body is voxelised through its rotation
    // and collides as a rotated box rather than as the staircase its cells make.
    Vec3 rotation_deg{};
    // Held in place: scenery rather than an object. A ramp, a table or a
    // wall has nothing under it and otherwise simply falls to the ground,
    // taking whatever was resting on it. An anchored body still collides
    // and can still be broken; it just does not move.
    bool anchored{false};
    // Cut this shape out of its join group instead of adding it. A bowl is a
    // sphere with a smaller sphere and a box taken out of it; a pipe is a
    // cylinder of boxes with a hole down the middle. Union alone can only make
    // shapes that bulge, and a bowl is the first thing anyone asks for that
    // does not. A subtracted body contributes no material and no mass; it only
    // says which cells are not there.
    bool subtract{false};
    std::uint32_t color_rgba{0x9fd3ffffU};
    // Bodies sharing a non-empty join name become one object. Their shapes are
    // voxelised onto the shared cell grid and unioned, so a cell both claim is
    // built once, and bonds are generated across the whole union: a handle
    // joined to a blade is one knife, not two touching pieces. A join takes one
    // material, the first body's.
    std::string join;
};

struct TileImpactRequest {
    // Many objects instead of one tile and one rigid striker. Empty means the
    // single-tile scene this lane has always run, bit for bit: nothing about a
    // body is read unless this is non-empty.
    std::vector<SceneBody> bodies;
    MaterialPreset tile_material{MaterialPreset::Glass};
    MaterialPreset ball_material{MaterialPreset::Iron};
    MaterialPreset ground_material{MaterialPreset::Concrete};
    Vec3 tile_dimensions_m{0.24, 0.04, 0.16}; // x, y (thickness), z
    double cell_size_m{0.02};
    unsigned neighbor_horizon_cells{2};
    double ball_radius_m{0.04};
    double ball_speed_m_s{4.0};  // downward at t = 0
    double ball_gap_m{0.002};    // clearance between ball and tile top at t = 0
    double ball_offset_x_m{};
    double ball_offset_z_m{};
    SceneLayout layout{SceneLayout::Bridge};
    double ledge_width_m{0.04};
    double ledge_height_m{0.12};
    // Substep as a fraction of the lattice's explicit substep limit (2/omega).
    double dt_factor{0.5};
    unsigned constraint_iterations{1};
    std::uint64_t material_seed{971};
    // Glass only: the catalog BrittleBond route (strength variation, damping)
    // instead of the strength-derived elastic reference shared by all presets.
    bool catalog_material{false};
    // Which rule sets the bond damage thresholds (material/Material.hpp).
    // StrainThreshold is the lane's original criterion, bit for bit;
    // EnergyScaled derives the removal stretch from Gc, the horizon and the
    // cell size (docs/criterion-energy-scaled-checkpoint.md).
    BondFailureLaw failure_law{BondFailureLaw::StrainThreshold};
    // Axial plastic flow in the bond solve, compiled from the tile material's
    // declared yield strength (material/MaterialCompiler.hpp withPlasticFlow;
    // fastlattice/LatticePhysics.hpp bondPlasticReturn).
    //
    // OFF BY DEFAULT, deliberately. With it off no bond can take a permanent
    // extension whatever the material declares, and the lane reproduces
    // b778517 bit for bit for every preset -- including oak and rubber, which
    // declare a yield strength the elastic-plus-damage lane has always ignored.
    // Turning it on is a change of constitutive model, so it is asked for.
    bool plasticity{false};
    // Linear isotropic hardening, tangent modulus over Young modulus. Negative
    // keeps what the material declares, which is 0 (perfect plasticity) for
    // every catalog preset and the only value the network lane admits.
    double hardening_ratio{-1.0};
    // Unloaded-shape probe. The reference material route compiles no bond
    // damping, so a plate that is struck and does not break rings for the whole
    // lattice phase and never settles: the permanent set cannot be read off a
    // frame. This runs the SAME solver on the state the lattice phase ended in,
    // with the striker removed, gravity zero, the supports removed and a strong
    // radial bond damping, until the plate stops moving. What is left is the
    // shape the material holds with nothing loading it -- the dent.
    //
    // It is a measurement of the state, not part of the simulated history: the
    // relaxed configuration is reported, never recorded as a frame and never fed
    // to the rigid handoff. 0 substeps (the default) skips it entirely.
    std::uint64_t relax_steps{0};
    double relax_damping_fraction{0.5};
    double node_contact_radius_factor{0.5}; // node contact radius = factor * cell
    NodeContactMode node_contact{NodeContactMode::On};
    // Extra height of the tile above its support at t = 0.
    double tile_drop_m{0.0};
    // Remove every bond after the lattice is generated, leaving a heap of loose
    // cells that only contact can hold apart. This is a CONTACT scene, not a
    // fracture one: nothing is precut to stand in for a fracture outcome, no
    // fracture claim is made from it, and the criterion never runs (a bondless
    // node has no strain). It exists so node contact can be measured on its own,
    // and with tile_drop_m it is the pile that must hold.
    bool loose_cells{false};
    // Verlet skin of the pair list, as a fraction of the cell size. The list
    // holds every pair within (2 * radius + skin) and is rebuilt when a node has
    // drifted more than half the skin since it was built.
    double node_contact_skin_factor{0.25};
    // Bracket the damping sweep and the striker passes with a serial kinetic
    // energy reduction, so their dissipation can be reported separately from the
    // node contact's. Two extra passes over the nodes per substep.
    bool audit_energy{false};
    double quiet_ms{10.0};
    double min_ms{5.0};
    double max_ms{200.0};
    double no_failure_ms{20.0};
    // Stop once the removed bond energy has grown by less than
    // energy_flat_fraction of its running total for this long. 0 disables,
    // which is this lane exactly as it was. Measured on a 250 x 200 x 20 mm
    // glass plate, energy is within 0.8% of its final value five to ten times
    // earlier than the piece count settles, and the piece count does not
    // converge in cell size, time step, sweep order or precision anyway.
    double energy_flat_ms{0.0};
    double energy_flat_fraction{1.0e-3};
    // Stop once nothing has failed and the worst-stressed bond has sat below
    // calm_damage_margin of the way to failing for this long. 0 disables.
    // A scene that was never going to break otherwise pays the full
    // no_failure_ms window to prove it, which is most of a run's compute.
    double calm_ms{0.0};
    double calm_damage_margin{0.5};
    double settle_limit_s{6.0};
    // ---- Re-fracture after the handoff (fastlattice/Refracture.hpp) --------
    //
    // OFF BY DEFAULT, deliberately, exactly as the plastic law is. With it off
    // not one line of the re-entry path runs: no impact observation is turned
    // on in the rigid world, no trigger is evaluated and no lattice is rebuilt,
    // so every scene reproduces 078ae24 bit for bit. Turning it on changes what
    // the rigid phase is allowed to do, so it is asked for.
    bool refracture{false};
    // The budget. A re-entry is refused -- and counted, never silently dropped
    // -- when either cap is spent, when the fragment is larger than the lattice
    // budget allows, or when the contact partner is one the lattice phase
    // cannot express (another fragment; the lattice has bonds and one striker,
    // not piece-piece collision).
    unsigned refracture_max_events{8};
    std::uint64_t refracture_max_steps{600000};
    // The window a re-entry may occupy, counted in RIGID steps so the lattice
    // clock and the rigid clock stay aligned: the lattice runs one rigid step's
    // worth of substeps, the rigid world (with the island removed) takes one
    // step, and both advance together.
    unsigned refracture_window_steps{6};
    // End a window early once no bond has failed for this many rigid steps.
    // 0 runs the whole window.
    unsigned refracture_quiet_steps{2};
    std::size_t refracture_max_cells{4000};
    // Print every contact above 5 m/s to stderr while the rigid phase runs.
    // Observation only; it changes nothing the run computes.
    bool refracture_trace{false};
    // ---- The second striker ----------------------------------------------
    // A second ball, dropped on the debris of the first strike. Radius 0 (the
    // default) means there is no second strike and nothing about the scene
    // changes. It is placed directly above the highest cell under its axis and
    // given a downward speed, exactly as the first ball is placed above the
    // tile: no fragment is ever given a velocity and no impulse is authored.
    double second_ball_radius_m{0.0};
    MaterialPreset second_ball_material{MaterialPreset::Iron};
    double second_ball_speed_m_s{0.0};
    double second_ball_offset_x_m{}, second_ball_offset_z_m{};
    double second_ball_gap_m{0.002};
    // Rigid-phase time at which the second ball appears. Negative: as soon as
    // the pieces of the first strike are at rest, or at second_strike_wait_s.
    double second_strike_at_s{-1.0};
    double second_strike_wait_s{1.0};
    double rest_speed_m_s{0.01};
    double rest_angular_rad_s{0.1};
    double rest_hold_s{0.3};
    double rigid_step_s{1.0 / 240.0};
    BackendKind backend{BackendKind::Cuda};
    // CpuParallel only; 0 asks for the hardware concurrency.
    unsigned cpu_threads{0};
    Precision precision{Precision::Float};
    unsigned blocks{1};
    unsigned threads_per_block{512};
    // Substeps per persistent-kernel launch. Windows' display watchdog (TDR)
    // kills a kernel that runs longer than about two seconds, so a launch is
    // kept well under that; the cost of a launch is measured, not assumed.
    std::uint64_t steps_per_launch{10000};
    unsigned lattice_frames{50};
    unsigned rigid_frames{72};
    Vec3 gravity_m_s2{0.0, -9.81, 0.0};
};

struct StaticBox {
    Vec3 center_m{};
    Vec3 dimensions_m{};
};

// Everything derived from a request before any step is taken. Owns the asset
// the ActiveMatter points to, so it is not copyable.
struct TileImpactSetup {
    TileImpactRequest request{};
    MaterialDefinition tile_material{}, ball_material{}, ground_material{};
    CompiledBrittleMaterial compiled{};
    // Many-object scenes only. The merged asset below owns the geometry; these
    // keep what each part was, so mass, colour and material survive the merge.
    bool multi_body{false};
    std::vector<LatticeAsset> part_assets;
    std::vector<MaterialDefinition> part_definitions;
    std::vector<CompiledBrittleMaterial> part_materials;
    std::vector<std::uint32_t> part_of_node;
    std::vector<double> node_mass_kg;
    // Which bodies each part was built from. One entry for a plain body,
    // several for a joined group, whose first body names and colours it.
    std::vector<std::vector<std::size_t>> part_bodies;
    LatticeAsset asset{};
    BoxLatticeLayout layout{};
    ActiveMatter matter{};
    LatticeResolutionLimit limit{};
    double dt_s{};
    Vec3 origin{};
    double tile_bottom_y{}, tile_top_y{}, ground_y{};
    // Height of the surface the tile is dropped onto: the ground in the flat
    // layout, the ledge tops in the bridge one. Equal to tile_bottom_y unless
    // the request asks for a drop.
    double support_y{};
    std::vector<StaticBox> ledges;
    CombinedContactMaterial ball_tile{}, tile_ground{}, ball_ground{}, tile_tile{};
    SphereState<double> sphere_world{};
    StepSettings<double> settings_scene{};   // origin-relative
    StepSettings<double> settings_world{};   // world frame (for the CPU comparison)
    LatticeSchedule schedule{};
    std::uint64_t quiet_steps{}, min_steps{}, max_steps{}, no_failure_steps{},
        energy_flat_steps{}, calm_steps{};

    TileImpactSetup() = default;
    TileImpactSetup(const TileImpactSetup &) = delete;
    TileImpactSetup &operator=(const TileImpactSetup &) = delete;
};

// A body's authored rotation_deg as a quaternion, w first. Shared because the
// batch lane and the live world both have to turn a body the same way; two
// copies of this convention would mean a ramp tilting differently in each.
void rotationQuaternion(const Vec3 &degrees, double out[4]);

// The bodies of a scene file: a JSON array, or an object with a "bodies"
// array. Every lane that runs a scene reads it through here, so the batch
// lane and the live one can never disagree about what a scene file means.
// The material names a scene file and a command line may use.
[[nodiscard]] MaterialPreset presetFromName(std::string_view name);

[[nodiscard]] std::vector<SceneBody> readSceneFile(const std::string &path);
// The same reader, given the text rather than a path. A host that is not a
// command line has its scene in memory and should not have to write it to a
// file to be allowed to use it.
[[nodiscard]] std::vector<SceneBody> readSceneJson(const std::string &text);
// The settings a scene may carry alongside its bodies, applied to `request`.
// Only the ones a host has any business choosing: everything else about how the
// solver runs is the engine's own affair.
//
//   {"bodies": [...], "plasticity": true, "hardening_ratio": 0.0}
//
// Plasticity is OFF unless asked for, which is why a dent is something a scene
// opts into. With it off every bond springs back to its rest length and nothing
// can hold a shape it was pushed into.
void readSceneSettings(const std::string &text, TileImpactRequest &request);

// The substep settings for a scene, in a frame with the given origin, and the
// backend a request asks for. Shared for the same reason as the rotation above:
// the batch lane and the live lane have to solve the same physics, and two
// copies of how the settings are assembled is two ways for that to stop being
// true without anyone noticing.
[[nodiscard]] StepSettings<double> buildSettings(const TileImpactSetup &setup, const Vec3 &origin);
[[nodiscard]] std::unique_ptr<LatticeBackend> makeBackend(const TileImpactRequest &request,
                                                          const LatticeSchedule &schedule);

[[nodiscard]] std::unique_ptr<TileImpactSetup> buildTileImpactSetup(const TileImpactRequest &request);

struct RecordedFrame {
    double time_s{};
    std::string phase; // "lattice" or "rigid"
    std::vector<Vec3> cell_positions;
    std::vector<Quat> cell_orientations;
    Vec3 ball_center{};
    Quat ball_orientation{};
    std::vector<std::uint32_t> component_ids;
    std::vector<std::uint8_t> bond_alive; // asset bond order
    std::vector<float> bond_damage;
    std::size_t fracture_count{};
};

// One admitted re-entry: what triggered it, what the lattice did with it, and
// whether the round trip closed.
struct RefractureEventReport {
    double time_s{};                 // scene time at which the window opened
    std::uint64_t body_id{};
    std::string partner;             // "striker", "second-striker", "support"
    std::size_t cells{}, live_bonds_in{};
    // The trigger, as evaluated (Refracture.hpp).
    double closing_speed_m_s{}, threshold_speed_m_s{};
    double peak_stretch{}, minimum_removal_stretch{};
    double available_energy_j{}, minimum_removal_energy_j{};
    // The window.
    std::uint64_t substeps{};
    unsigned rigid_steps{};
    double window_s{}, wall_s{}, clock_residual_s{};
    std::uint32_t broken_bonds{};
    std::size_t pieces_out{};
    double removed_energy_j{}, plastic_work_j{};
    double contact_dissipated_j{}, node_contact_dissipated_j{}, damping_dissipated_j{};
    double elastic_in_j{}, elastic_out_j{};
    // The ledger. Entry: the lattice built from the rigid pose against the same
    // cell set read back through the engine's own fragment mass properties.
    // Exit: the lattice against the pieces it becomes. Window: what is left
    // after gravity, the removals, the plastic work and the dissipation, which
    // is the supports' contribution and is zero when no support engaged.
    double entry_momentum_residual_kg_m_s{}, entry_angular_residual_kg_m2_s{}, entry_energy_residual_j{};
    double exit_momentum_residual_kg_m_s{}, exit_angular_residual_kg_m2_s{};
    double exit_coarsening_loss_j{}, exit_energy_residual_j{};
    // Over the window: what is left of the momentum balance after gravity, and
    // of the energy balance after gravity, the removals, the plastic work and
    // the measured dissipation. Both are the supports' contribution -- the
    // impulse is exactly zero when no support engaged -- plus, for the energy,
    // the solver's own numerical change (the XPBD position projections and the
    // velocity reconstruction), which nothing in this lane measures directly.
    double window_external_impulse_n_s{}, window_energy_residual_j{};
    // How far the rigid representation had let this piece sink into a support
    // plane when the window opened; the conversion lifts it out by exactly this
    // much before building the lattice. The lattice's support projection is
    // unconditional on an infinite plane, so a cell that starts below the floor
    // is teleported up through its bonds; this says by how much.
    double entry_support_penetration_m{}, entry_max_displacement_m{};
    // Gap between the striker's surface and the nearest cell's contact sphere
    // when the window opens, AFTER the back-off below; zero when no striker is
    // in the island. `entry_striker_backoff_m` is how far the striker had to be
    // moved back along the contact normal to reach it, which is how far the
    // rigid solver had already driven it into the piece.
    double entry_striker_gap_m{}, entry_striker_backoff_m{};
    bool striker_in_island{};
};

struct RefractureReport {
    bool enabled{};
    // Every contact the trigger saw, and where each went.
    std::size_t contacts_tested{}, admitted{};
    std::size_t rejected_no_bond{}, rejected_stress{}, rejected_energy{};
    // The hardest contact the trigger ever saw on a fragment that still has
    // bonds, and how close it came to the bound: a refusal is then a number,
    // not a silence. `max_margin` is the estimated peak stretch over the
    // smallest removal threshold, so 1.0 is the admission line.
    double max_closing_speed_m_s{}, max_margin{};
    // The hardest contact on ANY piece, bondless debris included: the
    // difference between this and max_closing_speed_m_s is how much of a
    // strike the debris took.
    double max_closing_speed_any_m_s{};
    std::size_t refused_budget_events{}, refused_budget_steps{}, refused_unsupported{}, refused_too_large{};
    // A re-entry the lane declines for a reason of its own, counted so that a
    // refusal is visible: the rigid world had sunk the piece too far into the
    // floor to convert without teleporting it, or the world holds too many
    // bodies for the reversible step the re-entry needs.
    std::size_t refused_support_penetration{}, refused_no_rollback{}, refused_striker_overlap{};
    // Rigid steps replayed in the lattice instead of in Jolt, and steps that
    // paid for a rollback that was then committed anyway.
    std::size_t rollbacks{}, trial_steps{};
    std::uint64_t substeps{};
    double wall_s{}, simulated_s{};
    std::uint32_t broken_bonds{};
    std::size_t pieces_created{};
    double removed_energy_j{}, plastic_work_j{};
    // Worst residual over every event, so one number says whether it closed.
    double worst_entry_momentum_residual_kg_m_s{}, worst_entry_energy_residual_j{};
    double worst_exit_momentum_residual_kg_m_s{}, worst_exit_energy_residual_j{};
    std::vector<RefractureEventReport> events;
};

struct TileImpactMeasurements {
    std::string backend_name;
    std::size_t cells{}, bonds{}, colors{}, blocks{}, boundary_bonds{};
    double cell_size_m{}, tile_mass_kg{}, ball_mass_kg{};
    double dt_s{}, substep_limit_s{}, fastest_period_s{};
    std::uint64_t lattice_steps{};
    double lattice_simulated_s{}, lattice_wall_s{}, lattice_kernel_s{};
    unsigned launches{}, exit_reason{};
    std::uint32_t failure_rounds{}, broken_bonds{};
    double first_failure_s{-1.0}, last_failure_s{-1.0}, removed_energy_j{};
    double bond_updates_per_s{};
    // The failure law and its thresholds as compiled for this cell size and
    // horizon: the tensile removal stretch in use, the Gc-derived stretch
    // (zero under the strain-threshold law), the strength-derived one, and
    // the energy a {100} lattice crack plane costs per unit area under the
    // thresholds in use (N_100 E h s_end^2 / (2 m); equals Gc when the
    // energy-scaled law is unbounded by strength).
    std::string failure_law;
    double critical_stretch{}, energy_scaled_stretch{}, strength_stretch{};
    bool strength_bound_active{};
    double lattice_crack_energy_j_m2{};
    // Failure modes of the removed bonds at handoff.
    std::size_t tensile_failures{}, compressive_failures{}, shear_failures{};
    // The first failure round: how many bonds, where (centroid of their rest
    // midpoints, world frame), how deep below the tile top and how far from
    // the strike axis. Only backends that record the set report it.
    std::size_t first_failure_bonds{};
    Vec3 first_failure_centroid_m{};
    double first_failure_depth_m{-1.0}, first_failure_radius_m{-1.0};
    // Resolution-independent piece statistics: pieces at least 1% / 5% of the
    // tile mass, and the mass fraction in pieces below 1%.
    std::size_t pieces_over_1pct{}, pieces_over_5pct{};
    double mass_fraction_under_1pct{};
    double phase_seconds[kPhaseCount]{};
    bool shared_memory_positions{};
    std::size_t shared_memory_bytes{};
    float max_tensile_stretch{}, max_compressive_strain{}, max_shear_strain{};
    // The worst bond's progress toward failing, 0 to 1. Exit reason 5 stops a
    // run when this stays low, so a run that stopped early can be checked.
    double max_damage{};
    std::uint32_t rank_deficient_nodes{};
    ContactAccumulators contact{};
    NodeContactAccumulators node_contact{};
    double damping_dissipated_j{}, striker_dissipated_j{};
    bool energy_audited{};
    // Plasticity: the compiled law, the work it dissipated and what it left.
    bool plasticity_enabled{};
    double yield_stretch{}, plastic_hardening_ratio{}, yield_strength_pa{};
    double plastic_work_j{};
    float max_plastic_stretch{};
    std::size_t plastic_bonds{};      // bonds carrying a permanent extension
    double plastic_extension_total_m{}; // sum of |permanent extension|
    // Energy at the end of the lattice phase: what the bonds still store
    // elastically (plastic work is not in it), and the lattice's kinetic
    // energy, both from the downloaded state.
    double elastic_energy_j{}, lattice_kinetic_j{}, initial_kinetic_j{};
    // Permanent deformation, measured over the last third of the lattice-phase
    // frames because the reference route has no bond damping and an undamped
    // plate rings for the whole phase. Deflections are signed, downward
    // negative, against each node's own t = 0 height.
    //   strike_*        : the node nearest the strike axis
    //   plate_*         : the mean over every node
    //   dent_depth_m    : plate mean minus strike mean, positive when the strike
    //                     point sits below the plate as a whole
    double strike_deflection_mean_m{}, strike_deflection_amplitude_m{};
    double plate_deflection_mean_m{}, dent_depth_m{};
    std::size_t dent_frames{};
    // The unloaded-shape probe (TileImpactRequest::relax_steps). Heights are
    // measured against each node's own reference height and referred to the mean
    // of the plate's two end columns, so a rigid drift of the free plate does not
    // enter. permanent_dent_m is positive when the strike point sits below that
    // reference; permanent_max_dip_m is the deepest point anywhere.
    std::uint64_t relax_steps{};
    std::uint32_t relax_broken_bonds{};
    double relax_plastic_work_j{}, relax_elastic_energy_j{}, relax_kinetic_j{};
    double permanent_dent_m{}, permanent_max_dip_m{};
    // The same measurement on the plate BEFORE the probe (the loaded, ringing
    // configuration), so the probe's effect is visible rather than assumed.
    double loaded_dent_m{};
    std::size_t components{}, rigid_fragments{}, debris_particles{};
    double largest_piece_mass_kg{};
    std::size_t largest_piece_cells{};
    // Re-fracture. `pieces_at_end` and `broken_bonds_total` count the whole run
    // (first strike plus every re-entry); `components` above stays the first
    // strike's answer so every earlier measurement keeps its meaning.
    RefractureReport refracture{};
    std::size_t pieces_at_end{};
    std::uint32_t broken_bonds_total{};
    double second_strike_time_s{-1.0}, second_ball_mass_kg{}, second_ball_speed_m_s{};
    double second_ball_start_y_m{};
    double handoff_wall_s{};
    double rigid_simulated_s{}, rigid_wall_s{};
    std::uint64_t rigid_steps{};
    bool came_to_rest{};
    double rest_time_s{-1.0};
    double ball_speed_at_end_m_s{};
    double ball_height_at_end_m{};
    double simulated_total_s{}, wall_total_s{}, realtime_ratio{};
    bool rule_met{};
    double recording_wall_s{};
};

// Two objects that touched during the rigid phase, aggregated over the run.
// Jolt reports a contact for every manifold it adds, and a settled pile adds and
// drops them constantly, so a per-event list would be both enormous and useless.
// What answers "did the ball reach the pins, and how hard" is the first touch and
// the hardest one, which is what this keeps.
struct ContactPair {
    std::string a, b;
    double first_time_s{};
    double peak_closing_speed_m_s{};
    double peak_impulse_n_s{};
    double peak_energy_j{};
    std::uint64_t events{};
};

struct TileImpactResult {
    TileImpactMeasurements measurements{};
    std::vector<RecordedFrame> frames;
    // Static description for the recording.
    Vec3 tile_dimensions_m{};
    double cell_size_m{};
    double ball_radius_m{};
    std::string tile_material_name, ball_material_name, ground_material_name;
    std::vector<StaticBox> ledges;
    double ground_y{};
    std::vector<std::pair<std::uint32_t, std::uint32_t>> bond_nodes;
    // Many-object scenes: which body each cell belongs to, and what those
    // bodies were, so the recording can name and colour them separately
    // instead of calling every cell one tile material.
    std::vector<SceneBody> bodies;
    std::vector<std::uint32_t> part_of_node;
    std::vector<std::vector<std::size_t>> part_bodies; // asset order
    // Who touched whom during the rigid phase, in the names the request used.
    std::vector<ContactPair> contacts;
};

// Runs impact through rest. Throws on backend errors.
[[nodiscard]] TileImpactResult runTileImpact(const TileImpactRequest &request, std::string *log = nullptr);

[[nodiscard]] std::string measurementsJson(const TileImpactMeasurements &m);
// report_json, when given, replaces the recording's `report` object: a lane
// built on this scene reports its own contract, not this one's measurements.
void writePlayback(const TileImpactResult &result, const std::filesystem::path &path,
                   const std::string *report_json = nullptr);

// The same scene stepped by BrittleBondSolver (index-order Gauss-Seidel) and
// by this lane's CPU backend (colour-order) for a fixed number of substeps,
// Flat layout only. Both are driven by one protocol: sphere kick, material
// substep, sphere drift, ball/support contact.
struct SolverComparison {
    std::uint64_t steps{};
    double dt_s{};
    // Per lane: first failure step (-1 none), broken bonds, components,
    // largest piece cells, removed energy, wall seconds, max node speed.
    struct Lane {
        std::string name;
        std::int64_t first_failure_step{-1};
        std::vector<std::uint32_t> first_failure_bonds; // asset indices
        std::uint32_t broken_bonds{};
        std::size_t components{};
        std::size_t largest_piece_cells{};
        double largest_piece_mass_kg{};
        double removed_energy_j{};
        double wall_s{};
        double bond_updates_per_s{};
        std::vector<std::uint32_t> broken_history; // broken bonds after each history stride
    };
    Lane reference, fast;
    std::uint64_t history_stride{};
    double max_position_difference_m{};
    double max_velocity_difference_m_s{};
    std::size_t alive_mismatches{};
    std::size_t first_failure_set_symmetric_difference{};
};

// permuted_reference runs BrittleBondSolver on a copy of the lattice whose
// bonds are stored in this lane's schedule order, so its index-order sweep
// becomes the colour-order sweep: any remaining difference is arithmetic, not
// physics. With it false the reference sweeps the asset's own bond order and
// the difference measures the Gauss-Seidel ordering effect.
[[nodiscard]] SolverComparison compareWithBrittleBondSolver(
    const TileImpactRequest &request, std::uint64_t steps, Precision fast_precision,
    BackendKind fast_backend, bool permuted_reference = false, std::string *log = nullptr);

[[nodiscard]] std::string comparisonJson(const SolverComparison &c);

} // namespace banjo::fastlattice
