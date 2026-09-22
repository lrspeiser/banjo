#pragma once

// Where the ground and the water meet the rigid world.
//
// The terrain (TerrainField) holds what the ground is made of and knows
// nothing about bodies. The water (ShallowWater) holds the rivers and ponds
// and knows nothing about bodies either. The coupling (WaterCoupling) turns
// the two into forces. This is the one place all three meet the solver, and
// it is deliberately thin: it decides WHEN each of them runs and what each is
// told, never what physics any of them does.
//
//     push()    inside the step's reversible trial: the water's pressure and
//               drag onto every awake body touching it. A step that is taken
//               back takes these pushes back with it (Jolt's recorded state
//               holds the force accumulator), exactly as a gas pushing a
//               piston does.
//     commit()  after the step is accepted, on the world clock:
//                 - the water advances to the world's time in as many
//                   substeps as its stability limit needs, and is given back
//                   the drag the bodies took from it;
//                 - what rests on the bed is re-read as the bed the water
//                   sees (a row of blocks is a dam);
//                 - the ground's stability check runs over whatever columns
//                   an edit or a slump has unsettled -- nothing, most of the
//                   time;
//                 - chunks whose ground changed get new colliders, built and
//                   swapped in here, between steps, and whatever they were
//                   holding up is woken to find out whether it still is.
//
// Different clocks, one timeline: the rigid world steps at the room's rate,
// the water at whatever its CFL limit allows (never ahead of the world), the
// ground's settling a few times a frame. Nothing skips physical time.
#include "terrain/TerrainField.hpp"
#include "terrain/TerrainGenerator.hpp"
#include "water/RiverNetwork.hpp"
#include "water/ShallowWater.hpp"
#include "water/WaterCoupling.hpp"

#include <limits>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace banjo {
class JoltWorld;
struct MaterialDefinition;
}

namespace banjo::terrain {

// What one host call touched, for anyone who wants to see that digging one
// corner touched one corner.
struct EditEffect {
    EditReport edit;
    std::size_t chunks_rebuilt{};
    double rebuild_ms{};
    unsigned bodies_woken{};
    std::size_t water_columns_moved{};   // columns whose bed changed under water
};

struct EnvironmentStats {
    // The water.
    std::size_t water_cells{};
    std::size_t water_active_cells{};    // computed in the last substep
    std::size_t water_wet_cells{};
    std::uint64_t water_substeps{};
    double water_ms_last{};              // the last commit's water work
    double water_ms_worst{};
    // The coupling.
    std::size_t bodies_in_water{};
    double coupling_ms_last{};
    double coupling_ms_worst{};
    // The ground.
    std::size_t ground_columns{};
    std::size_t ground_unsettled{};      // columns the stability check still has to ask
    std::size_t ground_checked{};        // columns asked since the last edit
    std::size_t chunks{};
    std::size_t chunks_rebuilt{};        // since the world opened
    double rebuild_ms_last{};
    double rebuild_ms_worst{};
    unsigned bodies_woken{};             // by ground changing under them, since the world opened
    // The whole of what this adds to a step, and the worst one.
    double step_ms_last{};
    double step_ms_worst{};
    std::uint64_t steps{};
    // Running totals since the world opened, for a breakdown of where a
    // step's time went: pushing forces, and everything done after the step
    // (of which the water and the ground are shown apart).
    double push_ms_total{};
    double commit_ms_total{};
    double water_ms_total{};
    double ground_ms_total{};
    // Where the water's bookkeeping looked, since the world opened: columns
    // read to decide which tiles are computed, tiles asked whether they are,
    // columns whose solid top was worked out again, and columns whose top
    // changed. None of them grows with the size of a quiet valley.
    std::uint64_t water_tile_cells_scanned{};
    std::uint64_t water_tile_checks{};
    std::uint64_t obstacle_cells_checked{};
    std::uint64_t obstacle_cells_changed{};
};

class Environment {
public:
    // Built from a scene's "terrain" and "water" blocks; null when the scene
    // declares neither. Throws, with the reason, on a declaration it cannot
    // honour.
    [[nodiscard]] static std::unique_ptr<Environment> fromScene(const std::string &scene_json,
                                                              const std::string &ground_state = {});
    explicit Environment(Landscape landscape);
    ~Environment();
    Environment(const Environment &) = delete;
    Environment &operator=(const Environment &) = delete;

    // The level a safety floor can stand at: below all the rock there is.
    [[nodiscard]] double floorY() const;
    // Give the rigid world its ground: one height-field collider per chunk.
    void attach(JoltWorld &world);

    void push(JoltWorld &world, const std::vector<water::BodyInWater> &bodies);
    void commit(JoltWorld &world, const std::vector<water::BodyInWater> &bodies, double dt_s);
    // How long the world has run, as far as the environment knows.
    [[nodiscard]] double timeS() const { return time_s_; }

    // Edits from the host, between steps. Each rebuilds exactly the chunks it
    // changed and wakes exactly what they held.
    EditEffect dig(JoltWorld &world, double ax, double az, double bx, double bz,
                   double width_m, double depth_m, double carried_objects_kg = 0);
    EditEffect deposit(JoltWorld &world, double x, double z, double radius_m,
                       double sand_m3, double soil_m3);
    // A cut out of bare rock; the host adds the block as a body.
    std::optional<CutBlock> cut(JoltWorld &world, double x, double z, int cells_x, int cells_z,
                                double depth_m, std::string *why = nullptr);
    // A river's discharge, from now. A source that became a connection feeds
    // what stands beyond it instead -- the basin there, or the basin or spring
    // at the top of the reach there -- and a basin, spring or junction beyond
    // the edges is fed by its own name.
    bool setDischarge(const std::string &river, double discharge_m3_s);

    // Regions beyond the edges (docs/watershed.md): the river network this
    // region's water meets -- basins, junctions and the reaches between them,
    // held coarsely (water::RiverNetwork). A link joins a connection of this
    // region's water to the network, at a basin or at a reach's open end. The
    // connection's faces see that water's level and speed at the start of each
    // water stride; the network takes exactly what crossed them at its end --
    // computed once, applied twice -- and goes on over the same stride.
    struct Link {
        std::string name;                      // the source or mouth it took over
        int connection{};                      // into the water's connections
        water::RiverNetwork::Endpoint end;     // what it meets beyond the edge
        bool replaced_source{};                // a river's source became it
        // Water leaving the network across it moves into this region along +x
        // or +z (a west or south edge: +1) or against it (east or north: -1).
        double into_along_axis{1.0};
    };
    [[nodiscard]] const water::RiverNetwork *network() const { return network_.get(); }
    [[nodiscard]] const std::vector<Link> &links() const { return links_; }

    // What has come out of the ground and not gone back: the sand and soil
    // dug, less what was heaped from them. Whoever dug it carries it, and a
    // heap made from what is carried can be no bigger (the host says which
    // heaps those are). Counted through every edit -- a scene's own, replayed
    // when a world opens, included -- so a world opened again from the same
    // edits carries the same. A heap a scene declares beyond it is declared
    // ground and leaves nothing owed; a cut leaves as a body, not carried.
    [[nodiscard]] const Volumes &carried() const { return carried_; }
    // Transfer already excavated bulk material out of the carried account.
    // A host must durably accept the returned packet with the saved world in
    // one transaction. This does not turn sand into glass or consume an object.
    [[nodiscard]] std::string withdrawCarried(double sand_m3, double soil_m3);
    // Host atomically debits stored lots with this return into carrying.
    void returnCarried(double sand_m3, double soil_m3, double carried_objects_kg = 0);
    // What that weighs, and how much of it a person can carry. Carried ground
    // had no weight and no end: six presses of Dig here put 435 kg of sand and
    // soil on the person in the owner's room, who walked off with it. With a
    // limit, a dig takes out only what still fits (TerrainField::dig's budget)
    // -- a spade's and a pick's alike, both go through dig() here -- and takes
    // nothing once it is reached. Infinite unless a host says, which is every
    // world as it was; the ground a scene's own edits dig is never limited.
    [[nodiscard]] double carriedKg() const;
    [[nodiscard]] double carryLimitKg() const { return carry_limit_kg_; }
    void setCarryLimitKg(double kg);

    [[nodiscard]] const TerrainField &terrain() const { return *terrain_; }
    [[nodiscard]] const water::ShallowWater *water() const { return water_.get(); }
    [[nodiscard]] const Landscape &landscape() const { return landscape_; }
    [[nodiscard]] const EnvironmentStats &stats() const { return stats_; }
    // Forces the water put on each body in the last push.
    [[nodiscard]] const std::vector<water::BodyForce> &lastForces() const { return forces_; }
    // What a body landing at this point hits: bare rock, or soft ground. The
    // acoustic impedance sqrt(rho E) that decides whether an impact can break
    // anything -- a stone dropped on sand is not a stone dropped on stone.
    [[nodiscard]] double contactImpedanceAt(const Vec3 &point_m) const;
    // What the ground adds to a ball's rolling resistance at a point: rock's,
    // soil's or sand's own share, by what is on top there -- the reason a ball
    // set down on a sandy bank stays put and one let go on bare rock rolls.
    // Off the ground, soil's. See docs/rolling-resistance.md.
    [[nodiscard]] double rollingResistanceAt(double x_m, double z_m) const;
    // Water from the world -- meltwater running off ice -- into the column of
    // the room's water under (x, z). Returns the volume that went in: nothing
    // outside the valley's grid, where it runs off the world instead.
    double addWater(double x_m, double z_m, double volume_m3);
    // How deep the room's water stands in the column under (x, z), metres:
    // zero outside the grid or where it is dry. What a sensor reads.
    [[nodiscard]] double waterDepthAt(double x_m, double z_m) const;

    // Everything, as JSON: the ground and its ledger, the water and its
    // ledger, rivers and ponds, the costs. `full` adds the model's provenance
    // and what is not modelled.
    [[nodiscard]] std::string reportJson(bool full = false) const;
    // The water as it stands, for carrying into a world opened again from an
    // edited scene: depth over the ground, discharge, the clock, the ledger.
    [[nodiscard]] std::string stateJson() const;
    // Accepted ground state and clocks, including colliders that may still be
    // waiting for the next rebuild stride. Restored only before attachment.
    [[nodiscard]] std::string groundStateJson() const;
    // What is at a point: ground, what it is made of, water, flow.
    [[nodiscard]] std::string surveyJson(double x, double z) const;

    // For drawing. Heights of the ground as float32, row by row (j outer); the
    // top material as one byte per column (0 rock, 1 soil, 2 sand); the water
    // surface as uint16 millimetres above `base`, 0 where dry or thinner than
    // `shown_m`; the flow as int8 pairs in 5 cm/s.
    [[nodiscard]] std::vector<float> heights() const;
    [[nodiscard]] std::vector<std::uint8_t> surfaces() const;
    [[nodiscard]] std::vector<std::uint16_t> waterSurfaceMm(double base_m, double shown_m = 0.003) const;
    [[nodiscard]] std::vector<std::int8_t> waterFlow() const;
    // The same pictures for the columns that hold water and no others: the
    // smallest box round every column deeper than `shown_m`, its surface in
    // millimetres above `base_m` and its flow, and how many columns hold any
    // water at all -- found from the tiles the water computes (and any a
    // column was changed in since), not from every column of the valley.
    struct WaterBox {
        int i0{}, j0{}, ni{}, nj{};
        std::vector<std::uint16_t> surface_mm;
        std::vector<std::int8_t> flow;
        std::size_t wet_cells{};
    };
    [[nodiscard]] WaterBox waterBox(double base_m, double shown_m = 0.003) const;
    // The rectangle of ground points changed since last asked.
    [[nodiscard]] TerrainField::Rect takeChangedGround() { return terrain_->takeChangedRect(); }

private:
    void applyEdits(const std::string &edits_json);
    void restoreGroundState(const std::string &state_json);
    void rebuildChunks(JoltWorld &world, const std::set<int> &chunks, EditEffect *effect);
    void syncWaterBed(const std::vector<std::size_t> &cells);
    // Grow the rectangle of ground that bodies will be woken over.
    void noteChanged(const std::vector<std::size_t> &cells);
    // The carried account: what a dig took out, and what a heap put back.
    void carry(const Volumes &dug);
    void putBack(double sand_m3, double soil_m3);
    // A sleeping body whose water has changed around it is woken.
    void wakeWhatTheWaterReached(JoltWorld &world, const std::vector<water::BodyInWater> &bodies);
    // The network over one water stride: it takes what crossed each link, then
    // goes on over the same stride on its own clock.
    void stepNetwork(double dt_s);
    std::vector<float> chunkHeights(int chunk) const;

    Landscape landscape_;
    std::unique_ptr<TerrainField> terrain_;
    std::unique_ptr<water::ShallowWater> water_;
    water::WaterCoupling coupling_;
    std::vector<water::Reaction> reactions_;
    std::vector<water::BodyForce> forces_;
    std::vector<unsigned> patch_of_chunk_;
    std::vector<std::vector<float>> collider_heights_;
    bool attached_{};
    Volumes carried_{};
    Volumes exported_{};
    Volumes returned_{};
    double carry_limit_kg_{std::numeric_limits<double>::infinity()};
    std::unique_ptr<water::RiverNetwork> network_;
    std::vector<Link> links_;
    double time_s_{};
    double water_behind_s_{};     // world time the water has yet to catch up
    double ground_behind_s_{};
    double since_rebuild_s_{};
    double push_ms_{};
    std::uint64_t commits_{};
    std::set<int> pending_chunks_;
    TerrainField::Rect pending_wake_{};
    // What the water pressed on each sleeping body with when it went to sleep.
    std::unordered_map<std::string, Vec3> rest_force_;
    // Who was in the water at the last push, for the report.
    struct Afloat {
        std::string name;
        double submerged_m3{}, buoyancy_n{}, weight_n{};
        double lift_share{};    // buoyancy over weight, averaged: see kFloatAverageS
    };
    std::vector<Afloat> in_water_;
    // Floating is judged over time, not at an instant. A log bobbing in still
    // water is held up by anything from 0.75 to 1.3 times its weight as it
    // passes up and down through its waterline; a log aground is held up by
    // less than its weight however long it is watched. So what the water held
    // up against what a body weighs is averaged with this time constant, over
    // accepted steps only, and a body floats when the water carries at least
    // kFloatsShare of it.
    static constexpr double kFloatAverageS = 2.0;
    static constexpr double kFloatsShare = 0.95;
    std::unordered_map<std::string, double> lift_share_;
    EnvironmentStats stats_;
};

// base64, for carrying arrays in JSON.
[[nodiscard]] std::string encodeBase64(const void *data, std::size_t bytes);
[[nodiscard]] std::vector<std::uint8_t> decodeBase64(const std::string &text);

} // namespace banjo::terrain
