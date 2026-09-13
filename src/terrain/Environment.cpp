#include "terrain/Environment.hpp"

#include "material/Material.hpp"
#include "rigid/JoltWorld.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <unordered_map>

namespace banjo::terrain {
namespace {

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

double msSince(Clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

// How often the water and the ground are brought up to the world's clock.
// The water's own stability limit decides how many substeps that takes; this
// only decides how often it is asked -- the rigid world steps at 240 Hz and a
// river does not need to be told the time that often.
constexpr double kWaterStrideS = 1.0 / 60.0;
constexpr double kGroundStrideS = 1.0 / 60.0;
// A slumping bank's colliders are rebuilt at most this often.
constexpr double kRebuildStrideS = 0.05;

// What a thing landing on the ground meets: soil. Soft, so it absorbs a blow
// rather than bouncing it back, with the friction of dry earth.
MaterialDefinition groundContact() {
    MaterialDefinition soil;
    soil.name = "terrain";
    soil.density_kg_m3 = soilMaterial().density_kg_m3;
    soil.young_modulus_pa = 0.05e9;
    soil.poisson_ratio = 0.3;
    soil.static_friction = 0.7;
    soil.dynamic_friction = 0.6;
    soil.friction = soil.dynamic_friction;
    soil.rolling_resistance = 0.05;
    soil.contact_damping_ratio = 0.6;
    soil.derive_restitution_from_damping = true;
    return soil;
}

const char *surfaceName(Surface s) {
    switch (s) {
    case Surface::Rock: return "rock";
    case Surface::Soil: return "soil";
    case Surface::Sand: return "sand";
    }
    return "soil";
}

const char *edgeName(water::Edge e) {
    switch (e) {
    case water::Edge::West: return "west";
    case water::Edge::East: return "east";
    case water::Edge::South: return "south";
    case water::Edge::North: return "north";
    }
    return "west";
}

Json volumesJson(const Volumes &v) {
    return {{"rock_m3", v.rock_m3}, {"soil_m3", v.soil_m3}, {"sand_m3", v.sand_m3}};
}

double number(const Json &node, const char *key, double fallback, double low, double high) {
    if (!node.contains(key)) return fallback;
    if (!node.at(key).is_number())
        throw std::invalid_argument(std::string(key) + " must be a number");
    const double v = node.at(key).get<double>();
    if (!std::isfinite(v) || v < low || v > high)
        throw std::invalid_argument(std::string(key) + " must be between " + std::to_string(low) +
                                    " and " + std::to_string(high));
    return v;
}

// Every key in `node` must be one of `allowed`: a misspelt key is refused by
// name rather than silently meaning nothing.
void onlyKeys(const Json &node, std::initializer_list<const char *> allowed, const char *what) {
    for (const auto &item : node.items()) {
        bool known = false;
        for (const char *k : allowed) known = known || item.key() == k;
        if (!known) throw std::invalid_argument(std::string(what) + " has no \"" + item.key() + "\"");
    }
}

std::pair<double, double> pointXZ(const Json &node, const char *key) {
    if (!node.contains(key) || !node.at(key).is_array() || node.at(key).size() < 2)
        throw std::invalid_argument(std::string(key) + " needs [x, z] (or [x, y, z]) in metres");
    const Json &p = node.at(key);
    // [x, z] or [x, y, z]: a point on the ground is named by where it is across it.
    if (p.size() == 2) return {p[0].get<double>(), p[1].get<double>()};
    return {p[0].get<double>(), p[2].get<double>()};
}

Landscape landscapeFrom(const Json &terrain) {
    const Json generate = terrain.contains("generate") ? terrain.at("generate") : Json("valley");
    std::string kind = "valley";
    Json options = Json::object();
    if (generate.is_string()) kind = generate.get<std::string>();
    else if (generate.is_object()) {
        options = generate;
        kind = generate.value("kind", std::string("valley"));
    } else throw std::invalid_argument("terrain.generate is a kind, or {\"kind\": ..., ...}");
    if (kind == "valley") {
        onlyKeys(options, {"kind", "seed", "chunks", "cell_m", "discharge_m3_s", "erosion_iterations"},
                 "a valley");
        ValleyParameters p;
        if (options.contains("seed")) p.seed = options.at("seed").get<std::uint64_t>();
        if (options.contains("chunks")) {
            const Json &c = options.at("chunks");
            if (!c.is_array() || c.size() != 2) throw std::invalid_argument("chunks is [along, across]");
            p.chunks_x = c[0].get<int>();
            p.chunks_z = c[1].get<int>();
        }
        p.cell_m = number(options, "cell_m", p.cell_m, 0.1, 1.0);
        p.discharge_m3_s = number(options, "discharge_m3_s", p.discharge_m3_s, 0.0, 20.0);
        p.erosion_iterations = static_cast<int>(number(options, "erosion_iterations", p.erosion_iterations, 0, 5000));
        return valley(p);
    }
    SimpleParameters p;
    onlyKeys(options, {"kind", "nx", "nz", "cell_m", "discharge_m3_s", "lake_level_m", "soil_m", "sand_m"},
             "a simple landscape");
    p.nx = static_cast<int>(number(options, "nx", p.nx, 4, 1024));
    p.nz = static_cast<int>(number(options, "nz", p.nz, 4, 1024));
    p.cell_m = number(options, "cell_m", p.cell_m, 0.05, 2.0);
    p.discharge_m3_s = number(options, "discharge_m3_s", p.discharge_m3_s, 0.0, 20.0);
    p.lake_level_m = number(options, "lake_level_m", p.lake_level_m, -100.0, 100.0);
    p.soil_m = number(options, "soil_m", p.soil_m, 0.0, 20.0);
    p.sand_m = number(options, "sand_m", p.sand_m, 0.0, 20.0);
    if (kind == "basin") return basin(p);
    if (kind == "channel") return channel(p);
    if (kind == "flat") return flatGround(p);
    throw std::invalid_argument("terrain.generate is \"valley\", \"basin\", \"channel\" or \"flat\", not \"" +
                                kind + "\"");
}

template <typename T> std::vector<T> decodeArray(const Json &state, const char *key, std::size_t count) {
    if (!state.contains(key) || !state.at(key).is_string())
        throw std::invalid_argument(std::string("a saved water state needs ") + key);
    const std::vector<std::uint8_t> bytes = decodeBase64(state.at(key).get<std::string>());
    if (bytes.size() != count * sizeof(T))
        throw std::invalid_argument(std::string("a saved water state's ") + key + " is the wrong size");
    std::vector<T> out(count);
    std::memcpy(out.data(), bytes.data(), bytes.size());
    return out;
}

} // namespace

// ---- base64 -----------------------------------------------------------------

std::string encodeBase64(const void *data, std::size_t bytes) {
    static constexpr char kAlphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const auto *p = static_cast<const std::uint8_t *>(data);
    std::string out;
    out.reserve((bytes + 2) / 3 * 4);
    for (std::size_t i = 0; i < bytes; i += 3) {
        const std::uint32_t a = p[i];
        const std::uint32_t b = i + 1 < bytes ? p[i + 1] : 0U;
        const std::uint32_t c = i + 2 < bytes ? p[i + 2] : 0U;
        const std::uint32_t triple = (a << 16) | (b << 8) | c;
        out.push_back(kAlphabet[(triple >> 18) & 63U]);
        out.push_back(kAlphabet[(triple >> 12) & 63U]);
        out.push_back(i + 1 < bytes ? kAlphabet[(triple >> 6) & 63U] : '=');
        out.push_back(i + 2 < bytes ? kAlphabet[triple & 63U] : '=');
    }
    return out;
}

std::vector<std::uint8_t> decodeBase64(const std::string &text) {
    const auto value = [](char ch) -> int {
        if (ch >= 'A' && ch <= 'Z') return ch - 'A';
        if (ch >= 'a' && ch <= 'z') return ch - 'a' + 26;
        if (ch >= '0' && ch <= '9') return ch - '0' + 52;
        if (ch == '+') return 62;
        if (ch == '/') return 63;
        return -1;
    };
    std::vector<std::uint8_t> out;
    out.reserve(text.size() / 4 * 3);
    std::uint32_t buffer = 0;
    int bits = 0;
    for (const char ch : text) {
        if (ch == '=') break;
        const int v = value(ch);
        if (v < 0) continue;
        buffer = (buffer << 6) | static_cast<std::uint32_t>(v);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<std::uint8_t>((buffer >> bits) & 0xFFU));
        }
    }
    return out;
}

// ---- building one -----------------------------------------------------------

std::unique_ptr<Environment> Environment::fromScene(const std::string &scene_json) {
    const Json document = Json::parse(scene_json);
    if (!document.is_object() || (!document.contains("terrain") && !document.contains("water")))
        return nullptr;
    const Json terrain = document.value("terrain", Json::object());
    const Json water = document.value("water", Json::object());
    if (!terrain.is_object()) throw std::invalid_argument("terrain is an object");
    if (!water.is_object()) throw std::invalid_argument("water is an object");
    onlyKeys(terrain, {"generate", "edits"}, "terrain");
    onlyKeys(water, {"discharge_m3_s", "rivers", "state"}, "water");
    auto environment = std::make_unique<Environment>(landscapeFrom(terrain));
    if (terrain.contains("edits")) environment->applyEdits(terrain.at("edits").dump());
    // A river's discharge, overridden: one number for every source, or by name.
    if (water.contains("discharge_m3_s")) {
        const double q = number(water, "discharge_m3_s", 0.0, 0.0, 20.0);
        for (const auto &in : environment->water_->inflows()) (void)environment->water_->setInflow(in.name, q);
    }
    if (water.contains("rivers")) {
        for (const Json &river : water.at("rivers")) {
            onlyKeys(river, {"name", "discharge_m3_s"}, "a river");
            const std::string name = river.value("name", std::string());
            if (!environment->water_->setInflow(name, number(river, "discharge_m3_s", 0.0, 0.0, 20.0)))
                throw std::invalid_argument("there is no river called \"" + name + "\"");
        }
    }
    // Water carried over from the world this scene was opened from: the same
    // water, standing over whatever ground the edits have left.
    if (water.contains("state")) {
        const Json &state = water.at("state");
        const water::Grid &g = environment->water_->grid();
        if (state.value("nx", 0) != g.nx || state.value("nz", 0) != g.nz)
            throw std::invalid_argument("the carried water was saved on a grid of a different size");
        water::ShallowWater::State s;
        s.depth = decodeArray<double>(state, "depth_b64", g.cells());
        s.qx = decodeArray<double>(state, "qx_b64", g.cells());
        s.qz = decodeArray<double>(state, "qz_b64", g.cells());
        s.time_s = state.value("time_s", 0.0);
        const Json ledger = state.value("ledger", Json::object());
        s.ledger.initial_m3 = ledger.value("initial_m3", 0.0);
        s.ledger.inflow_m3 = ledger.value("inflow_m3", 0.0);
        s.ledger.outflow_m3 = ledger.value("outflow_m3", 0.0);
        s.ledger.numerical_m3 = ledger.value("numerical_m3", 0.0);
        s.ledger.impulse_in_x_n_s = ledger.value("impulse_in_x_n_s", 0.0);
        s.ledger.impulse_in_z_n_s = ledger.value("impulse_in_z_n_s", 0.0);
        s.ledger.impulse_dropped_n_s = ledger.value("impulse_dropped_n_s", 0.0);
        environment->water_->restore(s);
    }
    return environment;
}

Environment::Environment(Landscape landscape) : landscape_(std::move(landscape)) {
    const Grid &g = landscape_.grid;
    terrain_ = std::make_unique<TerrainField>(g, landscape_.rock, landscape_.soil, landscape_.sand,
                                              landscape_.loose, landscape_.moisture);
    std::vector<double> ground(g.cells());
    for (std::size_t c = 0; c < ground.size(); ++c) ground[c] = terrain_->height(c);
    water_ = std::make_unique<water::ShallowWater>(water::Grid{g.nx, g.nz, g.dx, g.x0, g.z0}, ground);
    for (std::size_t c = 0; c < ground.size(); ++c) {
        if (c < landscape_.depth.size() && landscape_.depth[c] > 0.0) water_->setDepth(c, landscape_.depth[c]);
        if (c < landscape_.qx.size()) water_->setDischarge(c, landscape_.qx[c], landscape_.qz[c]);
    }
    for (const auto &in : landscape_.inflows) water_->addInflow(in);
    for (const auto &out : landscape_.outflows) water_->addOutflow(out);
    // A still pond by its level, so it is flat bit for bit and stays at rest
    // bit for bit.
    placeStillPonds(*water_, landscape_);
    water_->resetLedger();
    terrain_->resetLedger();
    stats_.water_cells = g.cells();
    stats_.ground_columns = g.cells();
    stats_.chunks = static_cast<std::size_t>(terrain_->chunksX()) * static_cast<std::size_t>(terrain_->chunksZ());
    patch_of_chunk_.assign(stats_.chunks, 0);
}

Environment::~Environment() = default;

void Environment::applyEdits(const std::string &edits_json) {
    const Json edits = Json::parse(edits_json);
    if (!edits.is_array()) throw std::invalid_argument("terrain.edits is a list");
    for (const Json &edit : edits) {
        if (!edit.is_object() || edit.size() != 1)
            throw std::invalid_argument("each terrain edit is {\"dig\": ...}, {\"deposit\": ...} or {\"cut\": ...}");
        const auto &[kind, spec] = *edit.items().begin();
        std::vector<std::size_t> changed;
        if (kind == "dig") {
            onlyKeys(spec, {"from_m", "to_m", "width_m", "depth_m"}, "a dig");
            const auto a = pointXZ(spec, "from_m");
            const auto b = spec.contains("to_m") ? pointXZ(spec, "to_m") : a;
            changed = terrain_->dig(a.first, a.second, b.first, b.second,
                                    number(spec, "width_m", 1.0, 0.05, 50.0),
                                    number(spec, "depth_m", 0.5, 0.01, 20.0)).cells;
        } else if (kind == "deposit") {
            onlyKeys(spec, {"at_m", "radius_m", "sand_m3", "soil_m3"}, "a deposit");
            const auto at = pointXZ(spec, "at_m");
            changed = terrain_->deposit(at.first, at.second, number(spec, "radius_m", 1.0, 0.05, 50.0),
                                        number(spec, "sand_m3", 0.0, 0.0, 1.0e5),
                                        number(spec, "soil_m3", 0.0, 0.0, 1.0e5)).cells;
        } else if (kind == "cut") {
            onlyKeys(spec, {"at_m", "cells", "height_m"}, "a cut");
            const auto at = pointXZ(spec, "at_m");
            int cx = 4, cz = 4;
            if (spec.contains("cells")) {
                cx = spec.at("cells").at(0).get<int>();
                cz = spec.at("cells").at(1).get<int>();
            }
            std::string why;
            if (!terrain_->cut(at.first, at.second, cx, cz, number(spec, "height_m", 0.4, 0.01, 20.0), &why))
                throw std::invalid_argument("a cut in the scene cannot be made: " + why);
        } else {
            throw std::invalid_argument("a terrain edit is dig, deposit or cut, not \"" + kind + "\"");
        }
        (void)changed;
    }
    // The scene is the ground as it WAS left: whatever the edits unsettled has
    // long since come to rest.
    for (int k = 0; k < 20000 && !terrain_->settled(); ++k) (void)terrain_->relax(kGroundStrideS);
    std::vector<std::size_t> moved;
    for (std::size_t c = 0; c < landscape_.grid.cells(); ++c)
        if (terrain_->height(c) != water_->terrain(c)) moved.push_back(c);
    syncWaterBed(moved);
    (void)terrain_->takeDirtyChunks();
    (void)terrain_->takeChangedRect();
}

double Environment::floorY() const { return terrain_->floor(); }

std::vector<float> Environment::chunkHeights(int chunk) const {
    const Grid &g = landscape_.grid;
    const int cx = chunk % terrain_->chunksX(), cz = chunk / terrain_->chunksX();
    const int i0 = cx * TerrainField::kChunkCells, j0 = cz * TerrainField::kChunkCells;
    constexpr int kCount = TerrainField::kChunkCells + 1;
    std::vector<float> heights(static_cast<std::size_t>(kCount) * kCount,
                               std::numeric_limits<float>::quiet_NaN());
    for (int jj = 0; jj < kCount; ++jj)
        for (int ii = 0; ii < kCount; ++ii) {
            const int i = i0 + ii, j = j0 + jj;
            if (i >= g.nx || j >= g.nz) continue;
            heights[static_cast<std::size_t>(jj) * kCount + static_cast<std::size_t>(ii)] =
                static_cast<float>(terrain_->height(g.at(i, j)));
        }
    return heights;
}

void Environment::attach(JoltWorld &world) {
    const Grid &g = landscape_.grid;
    const MaterialDefinition contact = groundContact();
    for (int chunk = 0; chunk < static_cast<int>(stats_.chunks); ++chunk) {
        const int cx = chunk % terrain_->chunksX(), cz = chunk / terrain_->chunksX();
        patch_of_chunk_[static_cast<std::size_t>(chunk)] = world.addGroundPatch(
            chunkHeights(chunk), TerrainField::kChunkCells + 1, g.dx,
            g.x0 + cx * TerrainField::kChunkCells * g.dx, g.z0 + cz * TerrainField::kChunkCells * g.dx,
            contact);
    }
    attached_ = true;
    (void)terrain_->takeDirtyChunks();
}

void Environment::syncWaterBed(const std::vector<std::size_t> &cells) {
    for (const std::size_t c : cells) {
        const double h = terrain_->height(c);
        if (water_->terrain(c) != h) water_->setTerrain(c, h);
    }
}

void Environment::rebuildChunks(JoltWorld &world, const std::set<int> &chunks, EditEffect *effect) {
    if (!attached_ || chunks.empty()) return;
    const Clock::time_point t0 = Clock::now();
    const Grid &g = landscape_.grid;
    unsigned woken = 0;
    for (const int chunk : chunks) {
        const unsigned patch = patch_of_chunk_[static_cast<std::size_t>(chunk)];
        if (patch == 0) continue;
        world.replaceGroundPatch(patch, chunkHeights(chunk));
        ++stats_.chunks_rebuilt;
    }
    // Whatever the changed ground was holding up: wake it, and let the solver
    // find out whether it is still held. Only over the columns that changed,
    // and a little past them -- a body resting a metre away is not disturbed
    // by a hole it is not over.
    const TerrainField::Rect r = pending_wake_;
    if (r.ni > 0) {
        double low = std::numeric_limits<double>::infinity(), high = -low;
        for (int j = r.j0; j < r.j0 + r.nj; ++j)
            for (int i = r.i0; i < r.i0 + r.ni; ++i) {
                const double h = terrain_->height(g.at(i, j));
                low = std::min(low, h);
                high = std::max(high, h);
            }
        const double margin = 0.6;
        woken = world.wakeBodiesIn({g.xOf(r.i0) - margin, low - 1.0, g.zOf(r.j0) - margin},
                                   {g.xOf(r.i0 + r.ni - 1) + margin, high + 4.0,
                                    g.zOf(r.j0 + r.nj - 1) + margin});
        pending_wake_ = {};
    }
    const double ms = msSince(t0);
    stats_.rebuild_ms_last = ms;
    stats_.rebuild_ms_worst = std::max(stats_.rebuild_ms_worst, ms);
    stats_.bodies_woken += woken;
    if (effect != nullptr) {
        effect->chunks_rebuilt += chunks.size();
        effect->rebuild_ms += ms;
        effect->bodies_woken += woken;
    }
}

void Environment::noteChanged(const std::vector<std::size_t> &cells) {
    const Grid &g = landscape_.grid;
    for (const std::size_t c : cells) {
        const int i = static_cast<int>(c % static_cast<std::size_t>(g.nx));
        const int j = static_cast<int>(c / static_cast<std::size_t>(g.nx));
        if (pending_wake_.ni == 0) {
            pending_wake_ = {i, j, 1, 1};
            continue;
        }
        const int i1 = std::max(pending_wake_.i0 + pending_wake_.ni - 1, i);
        const int j1 = std::max(pending_wake_.j0 + pending_wake_.nj - 1, j);
        pending_wake_.i0 = std::min(pending_wake_.i0, i);
        pending_wake_.j0 = std::min(pending_wake_.j0, j);
        pending_wake_.ni = i1 - pending_wake_.i0 + 1;
        pending_wake_.nj = j1 - pending_wake_.j0 + 1;
    }
}

// ---- the step ---------------------------------------------------------------

void Environment::push(JoltWorld &world, const std::vector<water::BodyInWater> &bodies) {
    const Clock::time_point t0 = Clock::now();
    forces_ = coupling_.forces(*water_, bodies, reactions_);
    in_water_.clear();
    const double g = water_->settings().gravity_m_s2;
    for (const water::BodyForce &f : forces_) {
        const water::BodyInWater &b = bodies[f.index];
        in_water_.push_back({b.name, f.submerged_m3, f.pressure_n.y, b.density_kg_m3 * b.volume_m3 * g});
        if (!world.contains(b.body_id)) continue;
        world.pushBody(b.body_id, f.force_n);
        world.twistBody(b.body_id, f.torque_n_m);
    }
    stats_.bodies_in_water = forces_.size();
    stats_.coupling_ms_last = msSince(t0);
    stats_.coupling_ms_worst = std::max(stats_.coupling_ms_worst, stats_.coupling_ms_last);
    stats_.push_ms_total += stats_.coupling_ms_last;
    push_ms_ = stats_.coupling_ms_last;
}

void Environment::commit(JoltWorld &world, const std::vector<water::BodyInWater> &bodies, double dt_s) {
    const Clock::time_point t0 = Clock::now();
    time_s_ += dt_s;
    water_behind_s_ += dt_s;
    ground_behind_s_ += dt_s;
    since_rebuild_s_ += dt_s;
    ++commits_;
    // The drag the bodies took from the water, given back: the one path by
    // which momentum crosses between them.
    for (const water::Reaction &r : reactions_) water_->addImpulse(r.cell, -r.fx_n * dt_s, -r.fz_n * dt_s);
    reactions_.clear();

    double water_ms = 0.0;
    if (water_behind_s_ >= kWaterStrideS) {
        const Clock::time_point tw = Clock::now();
        // What rests on the bed is the bed, as far as the water is concerned.
        std::vector<double> tops = coupling_.obstacleTops(*water_, bodies);
        if (tops != water_->obstacles()) water_->setObstacles(tops);
        water_->advance(water_behind_s_);
        water_behind_s_ = 0.0;
        water_ms = msSince(tw);
        stats_.water_ms_last = water_ms;
        stats_.water_ms_worst = std::max(stats_.water_ms_worst, water_ms);
        stats_.water_ms_total += water_ms;
    }
    // Sleeping bodies the water has come to: a log left on a dry bank that
    // the river rises round is not going to notice by itself. Asked at the
    // water's stride, and only of bodies the water reaches.
    if (water_ms > 0.0) wakeWhatTheWaterReached(world, bodies);

    if (ground_behind_s_ >= kGroundStrideS) {
        if (!terrain_->settled()) {
            const Clock::time_point tg = Clock::now();
            const Relaxed r = terrain_->relax(ground_behind_s_);
            syncWaterBed(r.changed);
            noteChanged(r.changed);
            stats_.ground_checked += r.checked;
            stats_.ground_ms_total += msSince(tg);
        }
        ground_behind_s_ = 0.0;
    }
    for (const int chunk : terrain_->takeDirtyChunks()) pending_chunks_.insert(chunk);
    if (!pending_chunks_.empty() && since_rebuild_s_ >= kRebuildStrideS) {
        rebuildChunks(world, pending_chunks_, nullptr);
        pending_chunks_.clear();
        since_rebuild_s_ = 0.0;
    }

    const water::Stats &ws = water_->stats();
    stats_.water_active_cells = ws.active_cells;
    stats_.water_wet_cells = ws.wet_cells;
    stats_.water_substeps = ws.substeps;
    stats_.ground_unsettled = terrain_->unsettled();
    stats_.commit_ms_total += msSince(t0);
    stats_.step_ms_last = msSince(t0) + push_ms_;
    stats_.step_ms_worst = std::max(stats_.step_ms_worst, stats_.step_ms_last);
    ++stats_.steps;
}

void Environment::wakeWhatTheWaterReached(JoltWorld &world, const std::vector<water::BodyInWater> &bodies) {
    for (const water::BodyInWater &b : bodies) {
        if (b.awake || b.anchored || b.held || !world.contains(b.body_id)) continue;
        // The force the water would put on it now, against what it was when
        // it went to sleep: a change of more than a twentieth of its weight
        // is the world having changed around it.
        water::BodyInWater asked = b;
        asked.awake = true;
        std::vector<water::Reaction> ignored;
        const std::vector<water::BodyForce> now = coupling_.forces(*water_, {asked}, ignored);
        const Vec3 force = now.empty() ? Vec3{} : now.front().force_n;
        const double weight = b.density_kg_m3 * b.volume_m3 * water_->settings().gravity_m_s2;
        auto [rest, fresh] = rest_force_.try_emplace(b.name, force);
        if (fresh) continue;
        if (length(force - rest->second) > 0.05 * weight) {
            world.wake(b.body_id);
            rest->second = force;
        }
    }
    // A body that is awake is not at rest: forget what it rested at.
    for (const water::BodyInWater &b : bodies)
        if (b.awake) rest_force_.erase(b.name);
}

// ---- edits ------------------------------------------------------------------

EditEffect Environment::dig(JoltWorld &world, double ax, double az, double bx, double bz,
                            double width_m, double depth_m) {
    EditEffect effect;
    terrain_->resetActivity();
    effect.edit = terrain_->dig(ax, az, bx, bz, width_m, depth_m);
    for (const std::size_t c : effect.edit.cells) effect.water_columns_moved += water_->depth(c) > 0.0;
    syncWaterBed(effect.edit.cells);
    noteChanged(effect.edit.cells);
    stats_.ground_checked = 0;
    // Rebuilt here and now: a dig is a synchronised point already -- the host
    // is between steps -- and the thing standing on the edge of the hole has
    // to find out before the next step whether it is still standing on
    // anything.
    const std::set<int> chunks = terrain_->takeDirtyChunks();
    rebuildChunks(world, chunks, &effect);
    return effect;
}

EditEffect Environment::deposit(JoltWorld &world, double x, double z, double radius_m,
                                double sand_m3, double soil_m3) {
    EditEffect effect;
    effect.edit = terrain_->deposit(x, z, radius_m, sand_m3, soil_m3);
    for (const std::size_t c : effect.edit.cells) effect.water_columns_moved += water_->depth(c) > 0.0;
    syncWaterBed(effect.edit.cells);
    noteChanged(effect.edit.cells);
    rebuildChunks(world, terrain_->takeDirtyChunks(), &effect);
    return effect;
}

std::optional<CutBlock> Environment::cut(JoltWorld &world, double x, double z, int cells_x, int cells_z,
                                         double depth_m, std::string *why) {
    std::optional<CutBlock> block = terrain_->cut(x, z, cells_x, cells_z, depth_m, why);
    if (!block) return block;
    std::vector<std::size_t> changed;
    for (std::size_t c = 0; c < landscape_.grid.cells(); ++c)
        if (terrain_->height(c) != water_->terrain(c)) changed.push_back(c);
    syncWaterBed(changed);
    noteChanged(changed);
    rebuildChunks(world, terrain_->takeDirtyChunks(), nullptr);
    return block;
}

double Environment::contactImpedanceAt(const Vec3 &point_m) const {
    // Rock is the engine's stone and meets a blow as stone does. Soil and sand
    // are soft ground: a bulk stiffness of about 50 MPa (loose to medium-dense
    // sand, firm soil -- DECLARED, textbook range) at their bulk density.
    const auto c = terrain_->cellAt(point_m.x, point_m.z);
    const bool rock = c && terrain_->surface(*c) == Surface::Rock;
    if (rock) return std::sqrt(rockMaterial().density_kg_m3 * 30.0e9);
    return std::sqrt(soilMaterial().density_kg_m3 * 0.05e9);
}

bool Environment::setDischarge(const std::string &river, double discharge_m3_s) {
    return water_->setInflow(river, discharge_m3_s);
}

// ---- reading ----------------------------------------------------------------

std::string Environment::reportJson(bool full) const {
    const Grid &g = landscape_.grid;
    const Volumes volumes = terrain_->volumes();
    const Ledger &gl = terrain_->ledger();
    const Volumes residual = terrain_->residual();
    const water::Ledger &wl = water_->ledger();
    const water::Stats &ws = water_->stats();
    Json rivers = Json::array();
    for (const auto &in : water_->inflows())
        rivers.push_back({{"name", in.name}, {"discharge_m3_s", in.discharge_m3_s},
                          {"enters_from", edgeName(in.edge)}, {"cells", {in.from, in.to}}});
    Json mouths = Json::array();
    for (const auto &out : water_->outflows())
        mouths.push_back({{"name", out.name}, {"leaves_by", edgeName(out.edge)}, {"cells", {out.from, out.to}}});
    // Where the river runs: every couple of metres along the valley, the
    // deepest column that is FLOWING -- a still pond beside it is deeper and
    // is not the river.
    Json path = Json::array();
    const int stride = std::max(1, static_cast<int>(std::lround(2.0 / g.dx)));
    for (int i = 0; i < g.nx; i += stride) {
        double deepest = 0.0;
        int at = -1;
        for (int j = 0; j < g.nz; ++j) {
            const std::size_t c = g.at(i, j);
            const double h = water_->depth(c);
            if (!(h > 0.02) || !(std::hypot(water_->velocityX(c), water_->velocityZ(c)) > 0.03)) continue;
            if (h > deepest) { deepest = h; at = j; }
        }
        if (at < 0) continue;
        const std::size_t c = g.at(i, at);
        int from = at, to = at;
        while (from > 0 && water_->depth(g.at(i, from - 1)) > 0.01) --from;
        while (to + 1 < g.nz && water_->depth(g.at(i, to + 1)) > 0.01) ++to;
        path.push_back({{"x_m", g.xOf(i)}, {"z_m", g.zOf(at)}, {"level_m", water_->surface(c)},
                        {"depth_m", deepest}, {"bed_m", water_->bed(c)},
                        {"speed_m_s", std::hypot(water_->velocityX(c), water_->velocityZ(c))},
                        {"wet_from_z_m", g.zOf(from)}, {"wet_to_z_m", g.zOf(to)}});
    }
    // Where there is bare, level rock to cut stone from: the middle of the
    // first 5 x 5 patch of columns that are all rock and none steeper than
    // 15 degrees. A model looking for a quarry should not have to survey the
    // whole valley for one.
    Json bare = nullptr;
    for (int j = 2; j + 2 < g.nz && bare.is_null(); ++j)
        for (int i = 2; i + 2 < g.nx && bare.is_null(); ++i) {
            bool ok = true;
            for (int dj = -2; dj <= 2 && ok; ++dj)
                for (int di = -2; di <= 2 && ok; ++di) {
                    const std::size_t c = g.at(i + di, j + dj);
                    ok = terrain_->surface(c) == Surface::Rock && terrain_->slopeDeg(c) < 15.0;
                }
            if (ok) bare = {{"at_m", {g.xOf(i), g.zOf(j)}}, {"level_m", terrain_->height(g.at(i, j))}};
        }
    Json afloat = Json::array();
    for (const Afloat &a : in_water_)
        afloat.push_back({{"name", a.name}, {"submerged_m3", a.submerged_m3}, {"buoyancy_n", a.buoyancy_n},
                          {"weight_n", a.weight_n}, {"floats", a.buoyancy_n >= 0.98 * a.weight_n}});
    Json ponds = Json::array();
    for (const Lake &lake : landscape_.lakes) {
        Json pond = {{"name", lake.name}, {"at_m", {lake.x_m, lake.z_m}}, {"brim_m", lake.surface_m},
                     {"area_when_full_m2", lake.area_m2}, {"volume_when_full_m3", lake.volume_m3}};
        if (const auto c = terrain_->cellAt(lake.x_m, lake.z_m)) {
            pond["level_m"] = water_->wet(*c) ? Json(water_->surface(*c)) : Json(nullptr);
            pond["depth_now_m"] = water_->depth(*c);
        }
        ponds.push_back(pond);
    }
    Json report = {
        {"kind", landscape_.kind},
        {"grid", {{"nx", g.nx}, {"nz", g.nz}, {"cell_m", g.dx}, {"x0_m", g.x0}, {"z0_m", g.z0},
                  {"size_m", {(g.nx - 1) * g.dx, (g.nz - 1) * g.dx}},
                  {"chunks", {terrain_->chunksX(), terrain_->chunksZ()}},
                  {"chunk_cells", TerrainField::kChunkCells}}},
        {"ground", {{"lowest_m", terrain_->lowest()}, {"highest_m", terrain_->highest()},
                    {"floor_m", terrain_->floor()}, {"volumes", volumesJson(volumes)},
                    {"ledger", {{"initial", volumesJson(gl.initial)}, {"dug", volumesJson(gl.dug)},
                                {"cut", volumesJson(gl.cut)}, {"deposited", volumesJson(gl.deposited)},
                                {"slumped_m3", gl.slumped_m3}, {"loosened_m3", gl.loosened_m3}}},
                    {"residual", volumesJson(residual)},
                    {"unsettled_columns", terrain_->unsettled()},
                    {"bare_rock", bare}}},
        {"water", {{"time_s", ws.time_s}, {"volume_m3", water_->volume()}, {"wet_area_m2", water_->wetArea()},
                   {"cells", g.cells()}, {"wet_cells", ws.wet_cells}, {"active_cells", ws.active_cells},
                   {"active_tiles", ws.active_tiles}, {"tiles", ws.tiles},
                   {"inflow_m3_s", water_->inflowRate()}, {"outflow_m3_s", water_->outflowRate()},
                   {"substeps", ws.substeps}, {"last_substep_s", ws.last_substep_s},
                   {"wave_speed_m_s", ws.max_speed_m_s}, {"clamped", ws.clamped},
                   {"speed_capped", ws.speed_capped},
                   {"ledger", {{"initial_m3", wl.initial_m3}, {"inflow_m3", wl.inflow_m3},
                               {"outflow_m3", wl.outflow_m3}, {"numerical_m3", wl.numerical_m3},
                               {"impulse_in_x_n_s", wl.impulse_in_x_n_s},
                               {"impulse_in_z_n_s", wl.impulse_in_z_n_s},
                               {"impulse_dropped_n_s", wl.impulse_dropped_n_s}}},
                   {"residual_m3", water_->residual()},
                   {"rivers", rivers}, {"mouths", mouths}, {"ponds", ponds},
                   {"river_path", path}, {"bodies_in_water", afloat}}},
        {"costs", {{"water_ms_last", stats_.water_ms_last}, {"water_ms_worst", stats_.water_ms_worst},
                   {"coupling_ms_last", stats_.coupling_ms_last},
                   {"coupling_ms_worst", stats_.coupling_ms_worst},
                   {"rebuild_ms_last", stats_.rebuild_ms_last}, {"rebuild_ms_worst", stats_.rebuild_ms_worst},
                   {"chunks_rebuilt", stats_.chunks_rebuilt}, {"bodies_woken_by_ground", stats_.bodies_woken},
                   {"step_ms_last", stats_.step_ms_last}, {"step_ms_worst", stats_.step_ms_worst},
                   {"bodies_in_water", stats_.bodies_in_water},
                   {"ground_columns_checked", stats_.ground_checked}}},
        {"generation", {{"from_cache", landscape_.report.from_cache},
                        {"cache_path", landscape_.report.cache_path},
                        {"generate_ms", landscape_.report.total_ms},
                        {"drainage_ms", landscape_.report.drainage_ms},
                        {"erosion_ms", landscape_.report.erosion_ms},
                        {"river_ms", landscape_.report.river_ms},
                        {"river_settled_after_s", landscape_.report.river_time_s},
                        {"depressions", landscape_.report.depressions},
                        {"ponds_kept", landscape_.report.lakes},
                        {"pits_filled", landscape_.report.pits_filled},
                        {"carved_m3", landscape_.report.carved_m3},
                        {"eroded_m3", landscape_.report.eroded_m3},
                        {"deposited_m3", landscape_.report.deposited_m3}}},
        {"view", {{"eye_m", {landscape_.eye_m[0], landscape_.eye_m[1], landscape_.eye_m[2]}},
                  {"look_m", {landscape_.look_m[0], landscape_.look_m[1], landscape_.look_m[2]}}}},
    };
    if (full) {
        const water::Settings &s = water_->settings();
        const water::CouplingSettings &c = coupling_.settings();
        Json materials = Json::array();
        for (const GroundMaterial *m : {&rockMaterial(), &soilMaterial(), &sandMaterial()})
            materials.push_back({{"name", m->name}, {"density_kg_m3", m->density_kg_m3},
                                 {"friction_angle_deg", m->friction_angle_deg},
                                 {"cohesion_pa", m->cohesion_pa}});
        report["model"] = {
            {"ground", {{"materials", materials}, {"stop_layer_m", TerrainField::kStopLayerM},
                        {"provenance", "declared: textbook ranges for dry ground, not a calibration; rock "
                                       "is the engine's stone (the concrete preset)"}}},
            {"water", {{"scheme", "first-order finite volume, hydrostatic reconstruction (Audusse et al. "
                                  "2004), Rusanov flux, implicit Manning friction"},
                       {"manning_n", s.manning_n}, {"cfl", s.cfl}, {"dry_m", s.dry_m},
                       {"tile_cells", s.tile}, {"mouth", "free outfall over the edge's bed (broad-crested weir)"}}},
            {"coupling", {{"pressure", "hydrostatic, integrated over each body's own surface patches, clipped "
                                       "at the local water surface"},
                          {"drag_coefficient", c.drag_coefficient}, {"skin_coefficient", c.skin_coefficient},
                          {"patch_m", c.patch_m}, {"seal_gap_m", c.seal_gap_m},
                          {"provenance", "declared coefficients, not fitted"}}},
            {"generation", {{"version", kGeneratorVersion},
                            {"steps", {"landform", "Priority-Flood drainage from the mouth",
                                       "channel carved along the drainage route", "ponds kept, pits filled",
                                       "limited virtual-pipe erosion (after Mei, Decaudin & Hu 2007)",
                                       "soil thinned by slope", "river run to steady flow"}}}},
        };
        report["not_modelled"] = {
            "erosion and sediment transport during play (generation only)",
            "rain, evaporation and seepage into the ground",
            "a floating body's displacement raising the water around it, and the waves it makes",
            "added mass: water carried along with an accelerating body",
            "water that is not a single layer: waterfalls, spray, overturning waves, water under a floating roof",
            "uplift under a block resting on the bed (a gap smaller than the grid is treated as sealed)",
            "rock failing: rock never slumps, and is only cut",
            "moisture changing how the ground holds",
            "a break against the terrain: the lattice is supported by the flat floor under it",
            "coarse river networks and coarse-to-fine transitions (milestone 2)"};
    }
    return report.dump();
}

std::string Environment::stateJson() const {
    const water::ShallowWater::State s = water_->state();
    const water::Grid &g = water_->grid();
    Json state = {{"version", 1}, {"nx", g.nx}, {"nz", g.nz}, {"time_s", s.time_s},
                  {"depth_b64", encodeBase64(s.depth.data(), s.depth.size() * sizeof(double))},
                  {"qx_b64", encodeBase64(s.qx.data(), s.qx.size() * sizeof(double))},
                  {"qz_b64", encodeBase64(s.qz.data(), s.qz.size() * sizeof(double))},
                  {"volume_m3", water_->volume()},
                  {"ledger", {{"initial_m3", s.ledger.initial_m3}, {"inflow_m3", s.ledger.inflow_m3},
                              {"outflow_m3", s.ledger.outflow_m3}, {"numerical_m3", s.ledger.numerical_m3},
                              {"impulse_in_x_n_s", s.ledger.impulse_in_x_n_s},
                              {"impulse_in_z_n_s", s.ledger.impulse_in_z_n_s},
                              {"impulse_dropped_n_s", s.ledger.impulse_dropped_n_s}}}};
    return state.dump();
}

std::string Environment::surveyJson(double x, double z) const {
    const auto cell = terrain_->cellAt(x, z);
    if (!cell) return Json{{"on_the_ground", false}}.dump();
    const std::size_t c = *cell;
    Json out = {{"on_the_ground", true}, {"x_m", x}, {"z_m", z}, {"ground_m", terrain_->heightAt(x, z)},
                {"rock_top_m", terrain_->rockTop(c)}, {"soil_m", terrain_->soil(c)},
                {"sand_m", terrain_->sand(c)}, {"loose_soil_m", terrain_->looseSoil(c)},
                {"surface", surfaceName(terrain_->surface(c))}, {"slope_deg", terrain_->slopeDeg(c)}};
    if (water_->wet(c) && water_->depth(c) > 0.003) {
        const double u = water_->velocityX(c), w = water_->velocityZ(c);
        out["water"] = {{"depth_m", water_->depth(c)}, {"surface_m", water_->surface(c)},
                        {"speed_m_s", std::hypot(u, w)}, {"velocity_m_s", {u, w}},
                        {"bed_m", water_->bed(c)}};
    } else {
        out["water"] = nullptr;
    }
    return out.dump();
}

std::vector<float> Environment::heights() const {
    std::vector<float> out(landscape_.grid.cells());
    for (std::size_t c = 0; c < out.size(); ++c) out[c] = static_cast<float>(terrain_->height(c));
    return out;
}

std::vector<std::uint8_t> Environment::surfaces() const {
    std::vector<std::uint8_t> out(landscape_.grid.cells());
    for (std::size_t c = 0; c < out.size(); ++c) out[c] = static_cast<std::uint8_t>(terrain_->surface(c));
    return out;
}

std::vector<std::uint16_t> Environment::waterSurfaceMm(double base_m, double shown_m) const {
    std::vector<std::uint16_t> out(landscape_.grid.cells(), 0);
    for (std::size_t c = 0; c < out.size(); ++c) {
        if (!(water_->depth(c) > shown_m)) continue;
        const double mm = std::round((water_->surface(c) - base_m) * 1000.0);
        out[c] = static_cast<std::uint16_t>(std::clamp(mm, 1.0, 65535.0));
    }
    return out;
}

std::vector<std::int8_t> Environment::waterFlow() const {
    std::vector<std::int8_t> out(2 * landscape_.grid.cells(), 0);
    for (std::size_t c = 0; c < landscape_.grid.cells(); ++c) {
        if (!(water_->depth(c) > 0.003)) continue;
        out[2 * c] = static_cast<std::int8_t>(std::clamp(std::round(water_->velocityX(c) / 0.05), -127.0, 127.0));
        out[2 * c + 1] = static_cast<std::int8_t>(std::clamp(std::round(water_->velocityZ(c) / 0.05), -127.0, 127.0));
    }
    return out;
}

} // namespace banjo::terrain
