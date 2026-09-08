#pragma once

// Algorithm 2: an event-driven Griffith cascade on a precomputed crack-influence
// matrix. There is no time stepping anywhere in this lane.
//
// At object creation the plate is diagonalised once (src/modal), and three
// tables are built and cached:
//
//   1. the eigenpairs of the intact plate;
//   2. E[s][b], the peak dynamic strain of every bond b under a unit impulse
//      delivered through the ball's contact footprint centred on surface cell
//      s, evaluated from the closed-form modal impulse response (no stepping);
//   3. A[b][b'], the change in bond b's strain per newton of axial force
//      released when bond b' fails, from the compliance columns
//      c_b' = K^-1 g_b' with the exact Sherman-Morrison single-bond factor.
//
// An impact is then a table lookup and an event loop: the load is J * E[s][.],
// the Griffith drive is G_b / Gc, the largest drive above one breaks, its
// released force is added to every other bond through one precomputed column
// of A, and the loop repeats until nothing exceeds or the impact's energy
// budget is spent. Each event is O(bonds).
//
// What this lane is NOT: it has no wave arrival order, no inertial confinement,
// no contact history and no time. Superposing single-bond influences ignores
// the coupling between two broken bonds. Those are the measured errors, not
// hidden ones; docs/algo2-griffith-events-checkpoint.md carries the numbers.
//
// Nothing here precuts shards, animates a shatter, applies an explosion impulse
// or authors a fragment velocity, and the shared criterion in
// fracture/BondFailure.{hpp,cpp} is not modified by this lane.

#include "fracture/ActiveMatter.hpp"
#include "material/Material.hpp"
#include "material/MaterialCatalog.hpp"
#include "matter/BoxLattice.hpp"
#include "matter/Lattice.hpp"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace banjo::griffith {

enum class SupportKind : std::uint8_t {
    // Two rigid ledges under the ends of the long axis, as
    // src/fastlattice/TileImpactScene.cpp builds them for `--layout bridge`.
    Ledges,
    // The whole perimeter ring of cells held.
    Clamped,
};

enum class CriterionKind : std::uint8_t {
    // Energy release rate against the material's fracture_energy_j_m2.
    Griffith,
    // The strain threshold the shared criterion uses (compiled
    // damage_end_stretch), evaluated on the same field. Diagnostic: it exists
    // so the accuracy table can separate the criterion from the algorithm.
    Strain,
};

[[nodiscard]] const char *supportName(SupportKind support);
[[nodiscard]] const char *criterionName(CriterionKind criterion);

struct PlateRequest {
    double length_m{0.25};    // x
    double width_m{0.20};     // z
    double thickness_m{0.01}; // y
    double cell_m{0.01};
    double ball_diameter_m{0.06};
    SupportKind support{SupportKind::Ledges};
    MaterialPreset plate_material{MaterialPreset::Glass};
    MaterialPreset ball_material{MaterialPreset::Iron};
    unsigned horizon{2};
    double ledge_width_m{0.04};
    double ledge_height_m{0.12};
    std::uint64_t seed{971};
    // Peak-response sampling. The window is a multiple of the time the
    // longitudinal wave needs to cross the plate's longest side; the sample
    // step is a fraction of the lattice's own explicit substep limit. Neither
    // is a stability limit: the modal evolution between samples is exact, and
    // a strain excursion shorter than the step can be missed exactly as a
    // stepped lane misses one shorter than its step.
    double peak_window_transits{2.5};
    double peak_sample_fraction{0.25};
};

struct StaticBox {
    Vec3 center_m{};
    Vec3 dimensions_m{};
};

// The plate as geometry, material and topology. Owns the asset the ActiveMatter
// points at, so it is not copyable.
struct PlateModel {
    PlateRequest request{};
    MaterialDefinition plate_material{}, ball_material{};
    CompiledBrittleMaterial compiled{};
    LatticeAsset asset{};
    BoxLatticeLayout layout{};
    ActiveMatter matter{};
    LatticeResolutionLimit limit{};

    std::vector<char> fixed;                 // per node
    std::vector<std::uint32_t> free_nodes;   // node indices, ascending
    std::vector<std::uint32_t> free_index;   // node -> free slot, kNoIndex when held
    std::vector<std::uint32_t> strike_nodes; // top-layer cells, ascending
    std::vector<std::uint32_t> strike_row;   // node -> strike row, kNoIndex otherwise

    // Per bond, in asset order.
    std::vector<double> bond_stiffness_n_m;
    std::vector<double> bond_length_m;
    std::vector<double> bond_area_m2;   // crack area: sums to the cut area over a plane
    double area_normalisation{};        // bonds crossing a unit axis-aligned cut
    double young_modulus_pa{};

    Vec3 origin{};                      // plate centre in world
    double plate_bottom_y{}, plate_top_y{}, ground_y{};
    double free_mass_kg{}, total_mass_kg{};
    double ball_mass_kg{};
    std::vector<StaticBox> ledges;

    static constexpr std::uint32_t kNoIndex = 0xFFFFFFFFu;

    PlateModel() = default;
    PlateModel(const PlateModel &) = delete;
    PlateModel &operator=(const PlateModel &) = delete;
};

[[nodiscard]] std::unique_ptr<PlateModel> buildPlate(const PlateRequest &request);

struct PrecomputeStats {
    bool tables_cached{};       // the influence tables came from disk
    bool strike_cached{};       // the requested strike column was already there
    bool strikes_complete{};    // every strikeable cell has a column
    double eigen_s{}, influence_s{}, peak_s{}, cache_read_s{}, cache_write_s{}, total_s{};
    std::size_t bytes{};
    std::size_t modes{}, bonds{}, strike_cells{}, strike_cells_ready{};
    std::size_t peak_samples{};
    double peak_window_s{}, peak_sample_dt_s{};
    std::string path;
    std::string note;
};

// The cached tables. `influence` is column-major in the failing bond so one
// event touches one contiguous column.
struct InfluenceTables {
    std::size_t bonds{}, modes{}, strikes{};
    std::vector<float> influence;            // bonds * bonds, [b_prime * bonds + b], units 1/N
    std::vector<float> peak;                 // strikes * bonds, [s * bonds + b], strain per N s
    std::vector<std::uint8_t> peak_ready;    // per strike row
    std::vector<double> release_scale;       // per bond: 1 / (1 - k g^T K^-1 g)
    std::vector<std::uint8_t> release_singular; // removal disconnects: superposition invalid
    double sample_dt_s{}, window_s{};
    std::size_t samples{};
    PrecomputeStats stats{};
};

struct PrecomputeOptions {
    std::string cache_dir;
    // Fill every strikeable cell's column when the estimated cost is under
    // this many seconds; otherwise only the requested column is built and the
    // report says so.
    double all_strikes_budget_s{90.0};
    bool force_all_strikes{false};
    bool force_single_strike{false};
    // Refuse rather than allocate an influence matrix larger than this.
    std::size_t maximum_bytes{1500ull * 1024ull * 1024ull};
};

// Builds (or loads) the tables for `plate`. `strike_row` names the column that
// must be present on return; kNoIndex asks for none in particular.
[[nodiscard]] InfluenceTables precompute(const PlateModel &plate, const PrecomputeOptions &options,
                                         std::uint32_t strike_row);

// ---------------------------------------------------------------------------
// Impact
// ---------------------------------------------------------------------------

// The contact model, stated in full so the numbers it produces can be argued
// with. A rigid sphere of radius R indenting a plate of cell size h by half a
// cell has a Hertzian contact radius a = sqrt(R h - h^2/4). The impulse is
// spread over the top-layer cells inside a with the Hertzian pressure weight
// sqrt(1 - (r/a)^2), normalised to one.
//
// Its magnitude is a restitution-zero capture of that footprint:
//     J = mu_patch * v,   mu_patch = m_ball m_patch / (m_ball + m_patch)
// and m_patch is exactly the plate's modal effective mass for this load, since
// phi phi^T = M^-1 for a complete basis. The energy budget is the kinetic
// energy that leaves the rigid ledger over the whole contact, for which the
// engaged mass is the unsupported plate rather than the footprint:
//     E_in = 0.5 * mu_plate * v^2,  mu_plate = m_ball m_free / (m_ball + m_free).
// The two effective masses answer two different questions: what inertia the
// first impulse meets, and what inertia the ball meets before it separates.
struct ContactModel {
    double ball_mass_kg{}, speed_m_s{};
    double patch_mass_kg{}, free_mass_kg{};
    double reduced_mass_patch_kg{}, reduced_mass_plate_kg{};
    double contact_radius_m{};
    double impulse_n_s{}, energy_budget_j{};
    double ball_speed_after_m_s{};
    double strike_snap_m{};   // distance from the requested offset to the patch centre
    std::uint32_t strike_node{PlateModel::kNoIndex};
    std::uint32_t strike_row{PlateModel::kNoIndex};
    std::vector<std::uint32_t> patch_nodes;
    std::vector<double> patch_weights;
    std::string model;
};

[[nodiscard]] ContactModel buildContact(const PlateModel &plate, double offset_x_m, double offset_z_m,
                                        double speed_m_s);

struct CascadeEvent {
    std::uint32_t bond{};
    double drive{};        // G_b / Gc (or strain / break strain)
    double strain{};
    double released_force_n{};
    double crack_work_j{};       // Gc * bond area
    double stored_energy_j{};    // 0.5 k e^2 at removal
};

struct CascadeResult {
    std::vector<CascadeEvent> events;
    std::vector<std::uint32_t> first_failure;  // every bond at or above the criterion under the initial load
    double first_failure_peak_drive{};
    double energy_budget_j{}, energy_spent_j{}, energy_remaining_j{};
    double removed_energy_j{};        // stored elastic energy of the removed bonds at removal
    bool budget_exhausted{};
    bool influence_singular_used{};
    double cascade_wall_s{};
    std::size_t components{}, largest_component_cells{};
    double largest_component_mass_kg{};
    double maximum_initial_strain{};
};

struct CascadeOptions {
    CriterionKind criterion{CriterionKind::Griffith};
    std::size_t maximum_events{0};  // 0 = one per bond
};

// Runs the cascade on `plate.matter` (whose bond aliveness it updates in place)
// under the load `contact` implies, using the precomputed tables.
[[nodiscard]] CascadeResult runCascade(PlateModel &plate, const InfluenceTables &tables,
                                       const ContactModel &contact, const CascadeOptions &options);

// ---------------------------------------------------------------------------
// Pieces used by the tests
// ---------------------------------------------------------------------------

// Bond areas sum to the geometric area of an axis-aligned cut: this is the
// count that makes that true for a given horizon.
[[nodiscard]] double cutAreaNormalisation(unsigned horizon);

// A dense direct solve of K u = f over the free dofs, and the bond strains it
// implies. Reference for the influence-matrix test; O(n^3), tests only.
[[nodiscard]] std::vector<double> directBondStrains(const PlateModel &plate,
                                                    const std::vector<double> &force,
                                                    const std::vector<char> &bond_alive);

} // namespace banjo::griffith
