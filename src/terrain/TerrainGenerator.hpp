#pragma once

// A landscape shaped by physical processes, made once and saved.
//
// World generation is the one time the engine can afford to replay geological
// history, so it does it here and never again: the player walks into a valley
// that water has already been through. In order --
//
//   1. broad landforms: a valley with a meandering floor, hills on either side,
//      a hollow on the floodplain and a rocky knoll;
//   2. drainage: Priority-Flood (Barnes, Lehman & Mulla 2014), seeded at the
//      river's mouth, fills every depression to the level it would spill at and
//      gives every column a way down to the mouth; flow accumulation along
//      those routes says where the water goes;
//   3. the river's channel, carved along the route the drainage takes from
//      where the river comes in -- the landform proposes a valley, the drainage
//      decides where in it the river runs;
//   4. depressions kept or filled: a hollow deep and wide enough is kept as a
//      pond at the level it spills at, rather than being filled flat as
//      Priority-Flood alone would; small pits are filled with sediment;
//   5. a limited hydraulic erosion pass (after Mei, Decaudin & Hu 2007): rain
//      and the river's water run over the ground through virtual pipes, pick
//      up loose material where they can carry more than they hold and put it
//      down where they can carry less. Sediment moves with the water, so none
//      is made or lost;
//   6. soil thinned on steep ground until rock shows, and sand where the water
//      has left it;
//   7. the river itself, run with the real shallow-water solver from dry until
//      it passes on what it is fed, so the world opens with a river that is
//      already flowing.
//
// All of it is deterministic in its parameters and cached on disk under a key
// of them and of the generator's version: the first valley costs seconds, and
// every one after is read back.
#include "terrain/TerrainField.hpp"
#include "water/ShallowWater.hpp"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace banjo::terrain {

// Bumped whenever generation changes what it makes, so an old cached valley is
// never read back as a new one.
inline constexpr int kGeneratorVersion = 3;

struct ValleyParameters {
    std::uint64_t seed{7};
    int chunks_x{5};              // 31 cells each, along the river
    int chunks_z{4};              // across it
    double cell_m{0.25};
    double discharge_m3_s{0.35};  // what the river brings in
    int erosion_iterations{300};
    double spinup_limit_s{600.0}; // the most river time spent reaching steady flow
};

struct Lake {
    std::string name;
    double surface_m{};
    double area_m2{};
    double volume_m3{};
    double deepest_m{};
    double x_m{}, z_m{};          // its middle
};

// What generation did, for anyone asking how the valley came to be.
struct GenerationReport {
    bool from_cache{};
    std::string cache_path;
    double total_ms{};
    double drainage_ms{};
    double erosion_ms{};
    double river_ms{};
    int depressions{};
    int lakes{};
    int pits_filled{};
    double pits_filled_m3{};
    double carved_m3{};
    double eroded_m3{};
    double deposited_m3{};
    double river_time_s{};        // how long the river ran to settle
    double river_in_m3_s{};
    double river_out_m3_s{};
    double river_volume_m3{};
};

struct Landscape {
    std::string kind;             // "valley", "basin", "channel", "flat"
    Grid grid;
    std::vector<double> rock, soil, sand, loose;
    std::vector<float> moisture;
    // The water as the world opens with it: depth over the ground, discharge.
    std::vector<double> depth, qx, qz;
    std::vector<water::Inflow> inflows;
    std::vector<water::Outflow> outflows;
    std::vector<Lake> lakes;
    GenerationReport report;
    // Where somebody arriving would stand, and what they would look at.
    double eye_m[3]{};
    double look_m[3]{};
};

[[nodiscard]] Landscape generateValley(const ValleyParameters &parameters);
// The valley from the cache if it has been made before, and made and saved if
// not. `directory` empty means BANJO_TERRAIN_CACHE, or the system's temporary
// directory.
[[nodiscard]] Landscape valley(const ValleyParameters &parameters, const std::string &directory = {});
[[nodiscard]] std::string cacheFileName(const ValleyParameters &parameters);

// Small landscapes for tests and experiments, made on the spot.
//   basin:   a closed bowl holding a lake at rest.
//   channel: a straight sloping channel with a source at one end and a mouth
//            at the other, dry until the water arrives.
//   flat:    level ground, soil over rock, nothing else.
struct SimpleParameters {
    int nx{64}, nz{48};
    double cell_m{0.25};
    double discharge_m3_s{0.12};
    double lake_level_m{1.0};
    double soil_m{0.6};
    double sand_m{0.2};
};
[[nodiscard]] Landscape basin(const SimpleParameters &parameters);
[[nodiscard]] Landscape channel(const SimpleParameters &parameters);
[[nodiscard]] Landscape flatGround(const SimpleParameters &parameters);

// Put a landscape's still ponds into water by their LEVEL: every column of a
// pond that no river runs through gets exactly the pond's surface and no
// discharge. A still pond placed as ground plus depth is flat only to rounding
// -- the ground is rebuilt from its layers -- and a lake at rest has to be
// flat bit for bit to stay at rest bit for bit.
void placeStillPonds(water::ShallowWater &water, const Landscape &landscape);

bool saveLandscape(const Landscape &landscape, const std::string &path);
[[nodiscard]] std::optional<Landscape> loadLandscape(const std::string &path);

} // namespace banjo::terrain
