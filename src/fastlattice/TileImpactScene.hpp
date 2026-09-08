#pragma once

// The scene the fast-gpu lane is judged on: a uniform-cube tile struck by a
// rigid ball, fracturing on the explicit lattice, the pieces handed to Jolt to
// fall and settle, the whole thing recorded as banjo.playback.v1.

#include "fastlattice/FastLattice.hpp"
#include "fracture/ActiveMatter.hpp"
#include "material/Material.hpp"
#include "material/MaterialCatalog.hpp"
#include "matter/BoxLattice.hpp"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
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

struct TileImpactRequest {
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
    double settle_limit_s{6.0};
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
    std::uint64_t quiet_steps{}, min_steps{}, max_steps{}, no_failure_steps{};

    TileImpactSetup() = default;
    TileImpactSetup(const TileImpactSetup &) = delete;
    TileImpactSetup &operator=(const TileImpactSetup &) = delete;
};

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
    std::vector<std::pair<std::uint32_t, std::uint32_t>> bond_nodes; // asset order
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
