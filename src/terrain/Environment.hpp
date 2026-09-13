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
#include "water/ShallowWater.hpp"
#include "water/WaterCoupling.hpp"

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
    [[nodiscard]] static std::unique_ptr<Environment> fromScene(const std::string &scene_json);
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
                   double width_m, double depth_m);
    EditEffect deposit(JoltWorld &world, double x, double z, double radius_m,
                       double sand_m3, double soil_m3);
    // A cut out of bare rock; the host adds the block as a body.
    std::optional<CutBlock> cut(JoltWorld &world, double x, double z, int cells_x, int cells_z,
                                double depth_m, std::string *why = nullptr);
    // A river's discharge, from now. A source that became a connection feeds
    // the basin beyond it instead.
    bool setDischarge(const std::string &river, double discharge_m3_s);

    // Regions beyond the edges (docs/watershed.md). A basin is another
    // region's water held as a level pool -- its level its bed plus its volume
    // over its area -- fed from beyond the world and drained over an outlet
    // weir to beyond it, as declared. A link joins a connection of this
    // region's water to a basin: the connection's faces see the basin's level
    // at the start of each water stride, and the basin takes exactly what
    // crossed them at its end -- computed once, applied twice.
    struct Basin {
        std::string name;
        double bed_m{}, area_m2{}, volume_m3{};
        double fed_m3_s{};                     // from beyond the world
        bool has_outlet{};
        double crest_m{}, width_m{};           // its weir, to beyond the world
        // Its own ledger: volume = initial + fed - out + across, to rounding.
        double initial_m3{}, fed_m3{}, out_m3{}, across_m3{};
        double out_rate_m3_s{}, across_rate_m3_s{};   // over the last stride
        [[nodiscard]] double level() const { return bed_m + volume_m3 / area_m2; }
    };
    struct Link {
        std::string name;          // the source or mouth it took over
        std::size_t basin{};       // into basins()
        int connection{};          // into the water's connections
        bool replaced_source{};    // a river's source became it
    };
    [[nodiscard]] const std::vector<Basin> &basins() const { return basins_; }
    [[nodiscard]] const std::vector<Link> &links() const { return links_; }

    // What has come out of the ground and not gone back: the sand and soil
    // dug, less what was heaped from them. Whoever dug it carries it, and a
    // heap made from what is carried can be no bigger (the host says which
    // heaps those are). Counted through every edit -- a scene's own, replayed
    // when a world opens, included -- so a world opened again from the same
    // edits carries the same. A heap a scene declares beyond it is declared
    // ground and leaves nothing owed; a cut leaves as a body, not carried.
    [[nodiscard]] const Volumes &carried() const { return carried_; }

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

    // Everything, as JSON: the ground and its ledger, the water and its
    // ledger, rivers and ponds, the costs. `full` adds the model's provenance
    // and what is not modelled.
    [[nodiscard]] std::string reportJson(bool full = false) const;
    // The water as it stands, for carrying into a world opened again from an
    // edited scene: depth over the ground, discharge, the clock, the ledger.
    [[nodiscard]] std::string stateJson() const;
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
    void rebuildChunks(JoltWorld &world, const std::set<int> &chunks, EditEffect *effect);
    void syncWaterBed(const std::vector<std::size_t> &cells);
    // Grow the rectangle of ground that bodies will be woken over.
    void noteChanged(const std::vector<std::size_t> &cells);
    // The carried account: what a dig took out, and what a heap put back.
    void carry(const Volumes &dug);
    void putBack(double sand_m3, double soil_m3);
    // A sleeping body whose water has changed around it is woken.
    void wakeWhatTheWaterReached(JoltWorld &world, const std::vector<water::BodyInWater> &bodies);
    // The basins over one water stride: each takes what crossed its links,
    // then its feed and what its outlet lets go.
    void stepBasins(double dt_s);
    std::vector<float> chunkHeights(int chunk) const;

    Landscape landscape_;
    std::unique_ptr<TerrainField> terrain_;
    std::unique_ptr<water::ShallowWater> water_;
    water::WaterCoupling coupling_;
    std::vector<water::Reaction> reactions_;
    std::vector<water::BodyForce> forces_;
    std::vector<unsigned> patch_of_chunk_;
    bool attached_{};
    Volumes carried_{};
    std::vector<Basin> basins_;
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
