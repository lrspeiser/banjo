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
#include <type_traits>
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
    // The patch's own, for anywhere the ground cannot say: attach() tells the
    // world what the ground is made of at each point, and that is what a ball
    // rolling on it meets.
    soil.rolling_resistance = soilMaterial().rolling_resistance;
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

// What came out of the ground and has not gone back, and what it weighs: see
// Environment::carried. Not rounded: a heap of all of it is asked for with
// these very numbers.
Json carriedJson(const Volumes &c) {
    return {{"sand_m3", c.sand_m3}, {"soil_m3", c.soil_m3},
            {"sand_kg", c.sand_m3 * sandMaterial().density_kg_m3},
            {"soil_kg", c.soil_m3 * soilMaterial().density_kg_m3}};
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
    if (kind == "clearing") {
        // A clearing is small and fine: 8 m square in 0.1 m columns, 0.4 m of
        // soil and no sand, dry -- unless it says otherwise.
        p.nx = 80;
        p.nz = 80;
        p.cell_m = 0.1;
        p.soil_m = 0.4;
        p.sand_m = 0.0;
        p.discharge_m3_s = 0.0;
    }
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
    if (kind == "clearing") return clearing(p);
    throw std::invalid_argument("terrain.generate is \"valley\", \"basin\", \"channel\", \"flat\" or "
                                "\"clearing\", not \"" + kind + "\"");
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

std::unique_ptr<Environment> Environment::fromScene(const std::string &scene_json, const std::string &ground_state) {
    const Json document = Json::parse(scene_json);
    if (!document.is_object() || (!document.contains("terrain") && !document.contains("water")))
        return nullptr;
    const Json terrain = document.value("terrain", Json::object());
    const Json water = document.value("water", Json::object());
    if (!terrain.is_object()) throw std::invalid_argument("terrain is an object");
    if (!water.is_object()) throw std::invalid_argument("water is an object");
    onlyKeys(terrain, {"generate", "edits"}, "terrain");
    onlyKeys(water, {"discharge_m3_s", "rivers", "state", "watershed"}, "water");
    Landscape land = landscapeFrom(terrain);
    // Regions beyond the edges (docs/watershed.md): the river network -- the
    // basins and junctions declared, and the reaches between them -- and a
    // river's source or mouth the network's water stands beyond, taken out of
    // the landscape and made a connection to a basin or to a reach's open end.
    // A source's own discharge feeds what stands at the top of it -- the basin
    // there, or the one the reach there comes down from -- unless that says
    // otherwise.
    std::unique_ptr<water::RiverNetwork> network;
    std::vector<std::pair<Link, water::Connection>> joins;
    if (water.contains("watershed")) {
        const Json &shed = water.at("watershed");
        if (!shed.is_object()) throw std::invalid_argument("water.watershed is an object");
        onlyKeys(shed, {"basins", "junctions", "reaches", "connections"}, "water.watershed");
        network = std::make_unique<water::RiverNetwork>();
        std::vector<bool> fed_declared;
        const auto addNode = [&](const Json &b, bool junction) {
            const std::string what = junction ? "a junction" : "a basin";
            if (!b.is_object()) throw std::invalid_argument(what + " is an object");
            onlyKeys(b, {"name", "bed_m", "area_m2", "stage_storage", "level_m", "fed_m3_s", "outlet", "at_m"},
                     what.c_str());
            water::RiverNetwork::Node node;
            node.name = b.value("name", std::string());
            node.junction = junction;
            if (b.contains("stage_storage")) {
                if (b.contains("bed_m") || b.contains("area_m2"))
                    throw std::invalid_argument("\"" + node.name + "\" says how much it holds twice: a "
                                                "stage_storage table, or a bed and an area");
                std::vector<std::pair<double, double>> rows;
                for (const Json &row : b.at("stage_storage")) {
                    if (!row.is_array() || row.size() != 2 || !row[0].is_number() || !row[1].is_number())
                        throw std::invalid_argument("\"" + node.name + "\"'s stage_storage is rows of "
                                                    "[level_m, volume_m3]");
                    rows.emplace_back(row[0].get<double>(), row[1].get<double>());
                }
                node.storage = water::StageStorage::table(rows);
            } else {
                node.storage = water::StageStorage::prism(number(b, "bed_m", 0.0, -1.0e4, 1.0e4),
                                                         number(b, "area_m2", junction ? 20.0 : 100.0, 1.0, 1.0e8));
            }
            const double level = number(b, "level_m", node.storage.bottom(), node.storage.bottom(), 1.0e4);
            fed_declared.push_back(b.contains("fed_m3_s"));
            node.fed_m3_s = b.contains("fed_m3_s") ? number(b, "fed_m3_s", 0.0, 0.0, 1.0e3) : 0.0;
            if (b.contains("outlet")) {
                const Json &o = b.at("outlet");
                if (!o.is_object()) throw std::invalid_argument(what + "'s outlet is an object");
                onlyKeys(o, {"crest_m", "width_m"}, "an outlet");
                node.has_outlet = true;
                node.crest_m = number(o, "crest_m", node.storage.bottom(), -1.0e4, 1.0e4);
                node.outlet_width_m = number(o, "width_m", 1.0, 0.01, 1.0e4);
            }
            if (b.contains("at_m")) {
                const auto at = pointXZ(b, "at_m");
                node.x_m = at.first;
                node.z_m = at.second;
            }
            (void)network->addNode(std::move(node), level);
        };
        for (const Json &b : shed.value("basins", Json::array())) addNode(b, false);
        for (const Json &j : shed.value("junctions", Json::array())) addNode(j, true);
        // A source or mouth of this ground, taken out of it and made a
        // connection for `link`; what it brought in, if it was a source.
        const auto takeOver = [&](const std::string &replaced, Link link) {
            const auto source = std::find_if(land.inflows.begin(), land.inflows.end(),
                                             [&](const water::Inflow &in) { return in.name == replaced; });
            const auto mouth = std::find_if(land.outflows.begin(), land.outflows.end(),
                                            [&](const water::Outflow &out) { return out.name == replaced; });
            water::Connection span;
            double brought = -1.0;
            if (source != land.inflows.end()) {
                span = {replaced, source->edge, source->from, source->to};
                link.replaced_source = true;
                brought = source->discharge_m3_s;
                land.inflows.erase(source);
            } else if (mouth != land.outflows.end()) {
                span = {replaced, mouth->edge, mouth->from, mouth->to};
                land.outflows.erase(mouth);
            } else {
                throw std::invalid_argument("there is no river source or mouth called \"" + replaced +
                                            "\" for the regions beyond the edges to take over");
            }
            link.name = replaced;
            link.into_along_axis = span.edge == water::Edge::West || span.edge == water::Edge::South ? 1.0 : -1.0;
            joins.emplace_back(link, span);
            return brought;
        };
        // What a source brought, fed to what stands at the top of it.
        const auto feedFrom = [&](int node, double brought) {
            if (node == water::RiverNetwork::kOpen || brought < 0.0) return;
            const std::size_t k = static_cast<std::size_t>(node);
            if (fed_declared[k]) return;
            (void)network->setFeed(network->nodes()[k].name, brought);
            fed_declared[k] = true;
        };
        for (const Json &r : shed.value("reaches", Json::array())) {
            if (!r.is_object()) throw std::invalid_argument("a reach is an object");
            onlyKeys(r, {"name", "from", "to", "length_m", "width_m", "bed_from_m", "bed_to_m", "manning_n",
                         "cells", "depth_m", "discharge_m3_s", "level_m", "path_m"}, "a reach");
            water::RiverNetwork::Reach reach;
            reach.name = r.value("name", std::string());
            const std::string who = "the reach \"" + reach.name + "\"";
            // An end is a basin or junction by name, or {"connection": a source or
            // mouth of this ground} -- where this region's water meets it.
            std::string from_connection, to_connection;
            const auto end = [&](const char *key, std::string &connection) {
                if (!r.contains(key)) throw std::invalid_argument(who + " needs a " + key);
                const Json &e = r.at(key);
                if (e.is_string()) {
                    const int k = network->nodeNamed(e.get<std::string>());
                    if (k == water::RiverNetwork::kOpen)
                        throw std::invalid_argument(who + " runs from or to \"" + e.get<std::string>() +
                                                    "\", which is not a basin or junction declared");
                    return k;
                }
                if (e.is_object() && e.size() == 1 && e.contains("connection") && e.at("connection").is_string()) {
                    connection = e.at("connection").get<std::string>();
                    return water::RiverNetwork::kOpen;
                }
                throw std::invalid_argument(who + "'s " + key + " is a basin's or junction's name, or "
                                            "{\"connection\": a source or mouth of this ground}");
            };
            reach.from = end("from", from_connection);
            reach.to = end("to", to_connection);
            if (r.contains("path_m")) {
                for (const Json &p : r.at("path_m")) {
                    if (!p.is_array() || p.size() != 2 || !p[0].is_number() || !p[1].is_number())
                        throw std::invalid_argument(who + "'s path_m is points of [x_m, z_m]");
                    reach.path_m.emplace_back(p[0].get<double>(), p[1].get<double>());
                }
                if (reach.path_m.size() < 2) throw std::invalid_argument(who + "'s path_m needs two points");
            }
            double along = 0.0;
            for (std::size_t k = 1; k < reach.path_m.size(); ++k)
                along += std::hypot(reach.path_m[k].first - reach.path_m[k - 1].first,
                                    reach.path_m[k].second - reach.path_m[k - 1].second);
            reach.length_m = r.contains("length_m") ? number(r, "length_m", 10.0, 0.1, 1.0e6) : along;
            if (!(reach.length_m > 0.0)) throw std::invalid_argument(who + " needs a length_m or a path_m");
            reach.width_m = number(r, "width_m", 2.0, 0.05, 1.0e4);
            reach.bed_from_m = number(r, "bed_from_m", 0.0, -1.0e4, 1.0e4);
            reach.bed_to_m = number(r, "bed_to_m", reach.bed_from_m, -1.0e4, 1.0e4);
            reach.manning_n = r.contains("manning_n") ? number(r, "manning_n", 0.03, 0.005, 0.5) : 0.0;
            reach.cells = static_cast<int>(
                number(r, "cells", std::max(1.0, std::round(reach.length_m / 10.0)), 1.0, 10000.0));
            const double depth = number(r, "depth_m", 0.0, 0.0, 100.0);
            const double discharge = number(r, "discharge_m3_s", 0.0, -1.0e3, 1.0e3);
            const int index = network->addReach(std::move(reach), depth, discharge);
            if (r.contains("level_m"))
                network->standReach(static_cast<std::size_t>(index), number(r, "level_m", 0.0, -1.0e4, 1.0e4));
            Link link;
            link.end.reach = index;
            if (!from_connection.empty()) {
                link.end.at_to = false;
                (void)takeOver(from_connection, link);
            }
            if (!to_connection.empty()) {
                link.end.at_to = true;
                feedFrom(network->reaches()[static_cast<std::size_t>(index)].from, takeOver(to_connection, link));
            }
        }
        for (const Json &c : shed.value("connections", Json::array())) {
            if (!c.is_object()) throw std::invalid_argument("a connection is an object");
            onlyKeys(c, {"basin", "instead_of"}, "a connection");
            const std::string basin_name = c.value("basin", std::string());
            const int node = network->nodeNamed(basin_name);
            if (node == water::RiverNetwork::kOpen)
                throw std::invalid_argument("a connection's basin \"" + basin_name + "\" is not declared");
            Link link;
            link.end.node = node;
            feedFrom(node, takeOver(c.value("instead_of", std::string()), link));
        }
        network->resetLedger();
    }
    auto environment = std::make_unique<Environment>(std::move(land));
    environment->network_ = std::move(network);
    for (auto &join : joins) {
        join.first.connection = environment->water_->addConnection(join.second);
        environment->links_.push_back(join.first);
    }
    if (!ground_state.empty()) environment->restoreGroundState(ground_state);
    else if (terrain.contains("edits")) environment->applyEdits(terrain.at("edits").dump());
    // A river's discharge, overridden: one number for every source, or by name
    // -- a source that became a connection feeding what stands beyond it.
    if (water.contains("discharge_m3_s")) {
        const double q = number(water, "discharge_m3_s", 0.0, 0.0, 20.0);
        for (const auto &in : environment->water_->inflows()) (void)environment->water_->setInflow(in.name, q);
        for (const Link &link : environment->links_)
            if (link.replaced_source) (void)environment->setDischarge(link.name, q);
    }
    if (water.contains("rivers")) {
        for (const Json &river : water.at("rivers")) {
            onlyKeys(river, {"name", "discharge_m3_s"}, "a river");
            const std::string name = river.value("name", std::string());
            if (!environment->setDischarge(name, number(river, "discharge_m3_s", 0.0, 0.0, 20.0)))
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
        s.ledger.across_m3 = ledger.value("across_m3", 0.0);
        s.ledger.added_m3 = ledger.value("added_m3", 0.0);
        s.ledger.impulse_in_x_n_s = ledger.value("impulse_in_x_n_s", 0.0);
        s.ledger.impulse_in_z_n_s = ledger.value("impulse_in_z_n_s", 0.0);
        s.ledger.impulse_dropped_n_s = ledger.value("impulse_dropped_n_s", 0.0);
        environment->water_->restore(s);
        // And the river network beyond the edges, by name, as it was left: a
        // reservoir that went on filling is still full in the world opened
        // again, and each reach is carried cell for cell. One no longer
        // declared is let go; one newly declared -- or a reach now cut into
        // another number of cells -- starts as declared. (A state saved before
        // the network had reaches carries its basins as "basins".)
        if (environment->network_) {
            water::RiverNetwork &net = *environment->network_;
            const Json saved = state.value("network", Json::object());
            for (const Json &n : saved.value("nodes", state.value("basins", Json::array()))) {
                const int k = net.nodeNamed(n.value("name", std::string()));
                if (k == water::RiverNetwork::kOpen) continue;
                water::RiverNetwork::NodeState node = net.nodeState(static_cast<std::size_t>(k));
                node.volume_m3 = n.value("volume_m3", node.volume_m3);
                node.level_m = n.value("level_m", std::nan(""));
                node.initial_m3 = n.value("initial_m3", node.initial_m3);
                node.fed_m3 = n.value("fed_m3", 0.0);
                node.out_m3 = n.value("out_m3", 0.0);
                node.across_m3 = n.value("across_m3", 0.0);
                node.from_reaches_m3 = n.value("from_reaches_m3", 0.0);
                node.numerical_m3 = n.value("numerical_m3", 0.0);
                net.restoreNode(static_cast<std::size_t>(k), node);
            }
            for (const Json &r : saved.value("reaches", Json::array())) {
                const int k = net.reachNamed(r.value("name", std::string()));
                if (k == water::RiverNetwork::kOpen) continue;
                water::RiverNetwork::ReachState reach;
                reach.level_m = r.value("level_m", std::vector<double>());
                reach.q_m3_s = r.value("q_m3_s", std::vector<double>());
                reach.initial_m3 = r.value("initial_m3", 0.0);
                reach.across_m3 = r.value("across_m3", 0.0);
                reach.numerical_m3 = r.value("numerical_m3", 0.0);
                reach.froude_held = r.value("froude_held", std::uint64_t{0});
                (void)net.restoreReach(static_cast<std::size_t>(k), reach);
            }
            if (saved.contains("time_s")) net.restoreClock(saved.value("time_s", 0.0));
        }
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
    // Let whatever is unsettled come to rest, in the strides the running world
    // settles in (commit).
    const auto settle = [this] {
        for (int k = 0; k < 20000 && !terrain_->settled(); ++k) (void)terrain_->relax(kGroundStrideS);
    };
    // A room runs before anyone digs in it: the ground the first edit met had
    // come to rest.
    settle();
    for (const Json &edit : edits) {
        if (!edit.is_object() || edit.size() != 1)
            throw std::invalid_argument("each terrain edit is {\"dig\": ...}, {\"deposit\": ...} or {\"cut\": ...}");
        // The key and value read off the object's own iterator, which refer into
        // `edit`. Bound as `const auto &[kind, spec] = *edit.items().begin()` they
        // referred into the TEMPORARY that items().begin() returns, which dies at
        // the end of that line: MSVC happened to leave the memory alone, and GCC
        // at -O3 reused it and the valley tests died in here with a segfault.
        const std::string kind = edit.begin().key();
        const Json &spec = edit.begin().value();
        std::vector<std::size_t> changed;
        if (kind == "dig") {
            onlyKeys(spec, {"from_m", "to_m", "width_m", "depth_m"}, "a dig");
            const auto a = pointXZ(spec, "from_m");
            const auto b = spec.contains("to_m") ? pointXZ(spec, "to_m") : a;
            // As shallow as a micrometre: what a pick's pry breaks loose goes
            // out as a dig spread over the ground its wedge reached, and a small
            // pry takes less than a centimetre off each column
            // (docs/ground-work.md). A room keeps it as an edit like any other.
            const EditReport dug = terrain_->dig(a.first, a.second, b.first, b.second,
                                                 number(spec, "width_m", 1.0, 0.05, 50.0),
                                                 number(spec, "depth_m", 0.5, 1.0e-6, 20.0));
            carry(dug.moved);
            changed = dug.cells;
        } else if (kind == "deposit") {
            onlyKeys(spec, {"at_m", "radius_m", "sand_m3", "soil_m3"}, "a deposit");
            const auto at = pointXZ(spec, "at_m");
            const double sand = number(spec, "sand_m3", 0.0, 0.0, 1.0e5);
            const double soil = number(spec, "soil_m3", 0.0, 0.0, 1.0e5);
            changed = terrain_->deposit(at.first, at.second, number(spec, "radius_m", 1.0, 0.05, 50.0),
                                        sand, soil).cells;
            putBack(sand, soil);
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
        // Each edit comes to rest before the next is made, in the strides the
        // running world settles in (commit), so the world opened again is the
        // one the edits were made in whenever each had come to rest before the
        // next: a second pit dug into the first one's slumped sides digs what
        // the slump left there. They used to be made back to back and settled
        // once, and that second pit dug unslumped ground -- 7.8 litres more
        // soil than the running room had, measured after a reload in the page.
        // The scene is the ground as it WAS left.
        settle();
    }
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

std::string Environment::groundStateJson() const {
    const auto s=terrain_->state();
    const auto packed=[](const auto &v) { return encodeBase64(v.data(),v.size()*sizeof(v[0])); };
    const auto rect=[](const auto &r) { return Json::array({r.i0,r.j0,r.ni,r.nj}); };
    Json colliders=Json::array();
    for (int k=0;k<static_cast<int>(stats_.chunks);++k)
        colliders.push_back(packed(collider_heights_.empty()?chunkHeights(k):collider_heights_[static_cast<std::size_t>(k)]));
    return Json{{"schema","banjo.ground-state.v3"},{"exported",volumesJson(exported_)},{"returned",volumesJson(returned_)},
        {"grid",{s.grid.nx,s.grid.nz,s.grid.dx,s.grid.x0,s.grid.z0}},
        {"rock",packed(s.rock)},{"soil",packed(s.soil)},{"sand",packed(s.sand)},
        {"loose",packed(s.loose)},{"moisture",packed(s.moisture)},{"floor",s.floor},
        {"ledger",{{"initial",volumesJson(s.ledger.initial)},{"dug",volumesJson(s.ledger.dug)},
            {"cut",volumesJson(s.ledger.cut)},{"deposited",volumesJson(s.ledger.deposited)},
            {"slumped_m3",s.ledger.slumped_m3},{"loosened_m3",s.ledger.loosened_m3}}},
        {"frontier",s.frontier},{"dirty_chunks",s.dirty_chunks},{"changed",rect(s.changed)},
        {"checked_total",s.checked_total},{"frontier_peak",s.frontier_peak},
        {"carried",volumesJson(carried_)},{"carry_limit_kg",std::isfinite(carry_limit_kg_)?Json(carry_limit_kg_):Json(nullptr)},
        {"time_s",time_s_},{"ground_behind_s",ground_behind_s_},{"water_behind_s",water_behind_s_},
        {"since_rebuild_s",since_rebuild_s_},{"commits",commits_},
        {"pending_chunks",pending_chunks_},{"pending_wake",rect(pending_wake_)},{"colliders",colliders}}.dump();
}

void Environment::restoreGroundState(const std::string &text) {
    if (attached_) throw std::invalid_argument("ground state must be restored before attachment");
    const Json d=Json::parse(text);
    const std::initializer_list<const char *> keys={"schema","exported","returned","grid","rock","soil","sand","loose","moisture",
        "floor","ledger","frontier","dirty_chunks","changed","checked_total","frontier_peak","carried",
        "carry_limit_kg","time_s","ground_behind_s","water_behind_s","since_rebuild_s","commits",
        "pending_chunks","pending_wake","colliders"};
    if (!d.is_object()) throw std::invalid_argument("ground state must be an object");
    onlyKeys(d,keys,"ground state");
    for (const char *key:keys) if (!d.contains(key) && !((std::string(key)=="exported" && d.value("schema","")=="banjo.ground-state.v1") ||
        (std::string(key)=="returned" && d.value("schema","")!="banjo.ground-state.v3")))
        throw std::invalid_argument(std::string("missing ground state ")+key);
    const auto integer=[](const Json &v,std::uint64_t maximum) {
        if (!v.is_number_integer() || (!v.is_number_unsigned() && v.get<std::int64_t>()<0) ||
            v.get<std::uint64_t>()>maximum) throw std::invalid_argument("invalid ground state integer");
        return v.get<std::uint64_t>();
    };
    const auto indices=[&](const Json &v,auto &out,std::uint64_t maximum) {
        if (!v.is_array()) throw std::invalid_argument("ground indices must be an array");
        out.clear();
        for (const auto &entry:v) {
            using Index=typename std::decay_t<decltype(out)>::value_type;
            if (!out.insert(static_cast<Index>(integer(entry,maximum))).second)
                throw std::invalid_argument("duplicate ground index");
        }
    };
    if (d.at("schema")!="banjo.ground-state.v1" && d.at("schema")!="banjo.ground-state.v2" && d.at("schema")!="banjo.ground-state.v3")
        throw std::invalid_argument("unsupported ground state");
    auto s=terrain_->state(); const auto &g=d.at("grid");
    if (!g.is_array() || g.size()!=5 || !g[0].is_number_integer() || !g[1].is_number_integer())
        throw std::invalid_argument("invalid ground grid");
    s.grid={g[0].get<int>(),g[1].get<int>(),g[2].get<double>(),g[3].get<double>(),g[4].get<double>()};
    const auto unpack=[&](const char *key,auto &v) {
        const auto bytes=decodeBase64(d.at(key).get<std::string>());
        if (bytes.size()!=v.size()*sizeof(v[0])) throw std::invalid_argument("ground array size mismatch");
        std::memcpy(v.data(),bytes.data(),bytes.size());
    };
    unpack("rock",s.rock);unpack("soil",s.soil);unpack("sand",s.sand);unpack("loose",s.loose);unpack("moisture",s.moisture);
    s.floor=d.at("floor").get<double>();
    const auto volumes=[](const Json &v) {
        return Volumes{v.at("rock_m3").get<double>(),v.at("soil_m3").get<double>(),v.at("sand_m3").get<double>()};
    };
    const auto &l=d.at("ledger");
    s.ledger={volumes(l.at("initial")),volumes(l.at("dug")),volumes(l.at("cut")),volumes(l.at("deposited")),
        l.at("slumped_m3").get<double>(),l.at("loosened_m3").get<double>()};
    indices(d.at("frontier"),s.frontier,s.grid.cells()-1);
    indices(d.at("dirty_chunks"),s.dirty_chunks,stats_.chunks-1);
    const auto rect=[](const Json &v) {
        if (!v.is_array() || v.size()!=4) throw std::invalid_argument("invalid ground rectangle");
        for (const auto &n:v) if (!n.is_number_integer()) throw std::invalid_argument("invalid ground rectangle index");
        return TerrainField::Rect{v[0].get<int>(),v[1].get<int>(),v[2].get<int>(),v[3].get<int>()};
    };
    s.changed=rect(d.at("changed"));
    s.checked_total=static_cast<std::size_t>(integer(d.at("checked_total"),std::numeric_limits<std::size_t>::max()));
    s.frontier_peak=static_cast<std::size_t>(integer(d.at("frontier_peak"),s.grid.cells()));
    const auto carried=volumes(d.at("carried"));
    const auto exported=d.contains("exported")?volumes(d.at("exported")):Volumes{};
    const auto returned=d.contains("returned")?volumes(d.at("returned")):Volumes{};
    for (double v:{returned.rock_m3,returned.soil_m3,returned.sand_m3})
        if (!std::isfinite(v) || v<0) throw std::invalid_argument("invalid returned ground");
    if (returned.rock_m3!=0 || returned.soil_m3>exported.soil_m3 || returned.sand_m3>exported.sand_m3)
        throw std::invalid_argument("returned ground exceeds exports");
    for (double v:{exported.rock_m3,exported.soil_m3,exported.sand_m3})
        if (!std::isfinite(v) || v<0) throw std::invalid_argument("invalid exported ground");
    if (exported.rock_m3!=0 || exported.soil_m3-returned.soil_m3+carried.soil_m3>s.ledger.dug.soil_m3+1e-9 ||
        exported.sand_m3-returned.sand_m3+carried.sand_m3>s.ledger.dug.sand_m3+1e-9)
        throw std::invalid_argument("exported and carried ground exceed excavation");
    for (double v:{carried.rock_m3,carried.soil_m3,carried.sand_m3})
        if (!std::isfinite(v) || v<0) throw std::invalid_argument("invalid carried ground");
    const double limit=d.at("carry_limit_kg").is_null()?std::numeric_limits<double>::infinity():
        number(d,"carry_limit_kg",0,0,1e12);
    const double time=number(d,"time_s",0,0,1e12), ground=number(d,"ground_behind_s",0,0,1e12),
        water=number(d,"water_behind_s",0,0,1e12), since=number(d,"since_rebuild_s",0,0,1e12);
    std::set<int> chunks;indices(d.at("pending_chunks"),chunks,stats_.chunks-1);
    const auto wake=rect(d.at("pending_wake"));
    auto candidate=std::make_unique<TerrainField>(*terrain_);candidate->restore(s);
    // Reuse the terrain's strict rectangle validation for queued wakes too.
    auto wake_check=s;wake_check.changed=wake;candidate->restore(wake_check);candidate->restore(s);
    for (int k:chunks) if (k<0 || k>=static_cast<int>(stats_.chunks)) throw std::invalid_argument("invalid pending chunk");
    const auto &cs=d.at("colliders");
    if (!cs.is_array() || cs.size()!=stats_.chunks) throw std::invalid_argument("invalid collider count");
    std::vector<std::vector<float>> colliders;
    constexpr int count=TerrainField::kChunkCells+1;
    for (std::size_t k=0;k<cs.size();++k) {
        const auto bytes=decodeBase64(cs[k].get<std::string>());
        if (bytes.size()!=count*count*sizeof(float)) throw std::invalid_argument("invalid collider size");
        std::vector<float> heights(count*count);std::memcpy(heights.data(),bytes.data(),bytes.size());
        const int x0=static_cast<int>(k)%terrain_->chunksX()*TerrainField::kChunkCells;
        const int z0=static_cast<int>(k)/terrain_->chunksX()*TerrainField::kChunkCells;
        for (int j=0;j<count;++j) for(int i=0;i<count;++i) {
            const float h=heights[static_cast<std::size_t>(j*count+i)];
            if (x0+i<s.grid.nx && z0+j<s.grid.nz ? !std::isfinite(h) : !std::isnan(h))
                throw std::invalid_argument("invalid collider height");
        }
        colliders.push_back(std::move(heights));
    }
    const auto commits=integer(d.at("commits"),std::numeric_limits<std::uint64_t>::max());
    terrain_=std::move(candidate);carried_=carried;exported_=exported;returned_=returned;carry_limit_kg_=limit;
    time_s_=time;ground_behind_s_=ground;water_behind_s_=water;since_rebuild_s_=since;commits_=commits;
    pending_chunks_=chunks;pending_wake_=wake;collider_heights_=std::move(colliders);
    for (std::size_t c=0;c<s.grid.cells();++c) water_->setTerrain(c,terrain_->height(c));
}

void Environment::attach(JoltWorld &world) {
    const Grid &g = landscape_.grid;
    const MaterialDefinition contact = groundContact();
    const bool restored = !collider_heights_.empty();
    if (!restored) {
        collider_heights_.reserve(stats_.chunks);
        for (int chunk=0; chunk<static_cast<int>(stats_.chunks); ++chunk)
            collider_heights_.push_back(chunkHeights(chunk));
    }
    for (int chunk = 0; chunk < static_cast<int>(stats_.chunks); ++chunk) {
        const int cx = chunk % terrain_->chunksX(), cz = chunk / terrain_->chunksX();
        patch_of_chunk_[static_cast<std::size_t>(chunk)] = world.addGroundPatch(
            collider_heights_[static_cast<std::size_t>(chunk)], TerrainField::kChunkCells + 1, g.dx,
            g.x0 + cx * TerrainField::kChunkCells * g.dx, g.z0 + cz * TerrainField::kChunkCells * g.dx,
            contact);
    }
    // One collider material for all of it, but not one ground: a ball on the
    // sand is held where one on the rock rolls. Asked where each contact is,
    // so a dig, a slump or a heap of sand changes it as it changes the ground.
    world.setGroundRollingResistance([this](double x, double z) { return rollingResistanceAt(x, z); });
    attached_ = true;
    if (!restored) (void)terrain_->takeDirtyChunks();
}

double Environment::addWater(double x_m, double z_m, double volume_m3) {
    if (!water_) return 0.0;
    const auto cell = terrain_->cellAt(x_m, z_m);
    if (!cell) return 0.0;
    return water_->addWater(*cell, volume_m3);
}

double Environment::rollingResistanceAt(double x_m, double z_m) const {
    const auto cell = terrain_->cellAt(x_m, z_m);
    if (!cell) return soilMaterial().rolling_resistance;
    return groundMaterialOf(terrain_->surface(*cell)).rolling_resistance;
}

void Environment::syncWaterBed(const std::vector<std::size_t> &cells) {
    std::vector<std::size_t> moved;
    for (const std::size_t c : cells) {
        const double h = terrain_->height(c);
        if (water_->terrain(c) == h) continue;
        water_->setTerrain(c, h);
        moved.push_back(c);
    }
    // Whether water gets under what rests there is a question of the ground.
    if (!moved.empty()) coupling_.groundChanged(moved);
}

void Environment::rebuildChunks(JoltWorld &world, const std::set<int> &chunks, EditEffect *effect) {
    if (!attached_ || chunks.empty()) return;
    const Clock::time_point t0 = Clock::now();
    const Grid &g = landscape_.grid;
    unsigned woken = 0;
    for (const int chunk : chunks) {
        const unsigned patch = patch_of_chunk_[static_cast<std::size_t>(chunk)];
        if (patch == 0) continue;
        auto heights = chunkHeights(chunk);
        world.replaceGroundPatch(patch, heights);
        collider_heights_[static_cast<std::size_t>(chunk)] = std::move(heights);
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
        const double weight = b.density_kg_m3 * b.volume_m3 * g;
        const auto share = lift_share_.find(b.name);
        in_water_.push_back({b.name, f.submerged_m3, f.pressure_n.y, weight,
                             share != lift_share_.end() ? share->second
                                                        : (weight > 0.0 ? f.pressure_n.y / weight : 0.0)});
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
    // What the water held up this step, folded into each body's running share
    // (see kFloatAverageS). Here, after the step was accepted, so a step taken
    // back is not counted; a body that has left the water is forgotten.
    {
        const double keep = std::exp(-dt_s / kFloatAverageS);
        std::unordered_map<std::string, double> shares;
        shares.reserve(in_water_.size());
        for (Afloat &a : in_water_) {
            const double now = a.weight_n > 0.0 ? a.buoyancy_n / a.weight_n : 0.0;
            const auto was = lift_share_.find(a.name);
            a.lift_share = was == lift_share_.end() ? now : keep * was->second + (1.0 - keep) * now;
            shares.emplace(a.name, a.lift_share);
        }
        lift_share_ = std::move(shares);
    }

    double water_ms = 0.0;
    if (water_behind_s_ >= kWaterStrideS) {
        const Clock::time_point tw = Clock::now();
        // What rests on the bed is the bed, as far as the water is concerned:
        // told only where it changed -- the columns under what moved, arrived
        // or left, and under ground that changed. It used to be worked out for
        // every column of the valley and compared, sixty times a second.
        const std::vector<std::pair<std::size_t, double>> changes = coupling_.obstacleChanges(*water_, bodies);
        if (!changes.empty()) water_->setObstacleTops(changes);
        // Each connection sees the network's water beyond it as it stands at
        // the start of the stride -- its level, and the speed it is moving into
        // this region -- and the network takes what crossed at its end.
        if (network_)
            for (const Link &link : links_)
                water_->setFarSide(link.connection, network_->levelAt(link.end),
                                   link.into_along_axis * network_->speedOut(link.end));
        water_->advance(water_behind_s_);
        if (network_) stepNetwork(water_behind_s_);
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

    // The ground settles in whole strides of kGroundStrideS -- the strides a
    // world opened again lets each replayed edit settle in (applyEdits) -- so
    // that world is this one, edit for edit, whenever each edit had come to
    // rest before the next was made. It used to be given however much time had
    // gathered, 1/60 s or 5/240 s by how the room's steps added up, and a
    // slump's path, and where it stopped, depended on which. Time short of a
    // stride waits for the next; with nothing left to settle, none is owed.
    if (terrain_->settled()) {
        ground_behind_s_ = 0.0;
    } else if (ground_behind_s_ >= kGroundStrideS) {
        const Clock::time_point tg = Clock::now();
        do {
            const Relaxed r = terrain_->relax(kGroundStrideS);
            ground_behind_s_ -= kGroundStrideS;
            syncWaterBed(r.changed);
            noteChanged(r.changed);
            stats_.ground_checked += r.checked;
        } while (ground_behind_s_ >= kGroundStrideS && !terrain_->settled());
        stats_.ground_ms_total += msSince(tg);
    }
    for (const int chunk : terrain_->takeDirtyChunks()) pending_chunks_.insert(chunk);
    if (!pending_chunks_.empty() && since_rebuild_s_ >= kRebuildStrideS) {
        rebuildChunks(world, pending_chunks_, nullptr);
        pending_chunks_.clear();
        since_rebuild_s_ = 0.0;
    }

    const water::Stats &ws = water_->stats();
    stats_.water_tile_cells_scanned = ws.tile_cells_scanned;
    stats_.water_tile_checks = ws.tile_checks;
    stats_.obstacle_cells_changed = ws.obstacle_cells_changed;
    stats_.obstacle_cells_checked = coupling_.obstacleCellsChecked();
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

void Environment::stepNetwork(double dt_s) {
    // What crossed into this region's water came out of the network, and what
    // crossed out of it went in: exactly that, once. Then the network goes on
    // over the same stride on its own clock -- its basins fed and letting water
    // over their outlets, never more than stands above the crest, and its
    // reaches carrying what the fall of their water says.
    network_->startExchange();
    for (const Link &link : links_) network_->exchange(link.end, -water_->takeCrossed(link.connection), dt_s);
    network_->advance(dt_s);
}

double Environment::carriedKg() const {
    return carried_.sand_m3 * sandMaterial().density_kg_m3 + carried_.soil_m3 * soilMaterial().density_kg_m3;
}

void Environment::setCarryLimitKg(double kg) {
    if (std::isnan(kg) || kg < 0.0) throw std::invalid_argument("a carry limit is zero or more kilograms");
    carry_limit_kg_ = kg;
}

void Environment::carry(const Volumes &dug) {
    carried_.sand_m3 += dug.sand_m3;
    carried_.soil_m3 += dug.soil_m3;
}

void Environment::putBack(double sand_m3, double soil_m3) {
    // Floored at nothing: a heap bigger than what is carried is one a scene
    // declared, and the ground it adds is declared, not owed.
    carried_.sand_m3 = std::max(0.0, carried_.sand_m3 - sand_m3);
    carried_.soil_m3 = std::max(0.0, carried_.soil_m3 - soil_m3);
}

std::string Environment::withdrawCarried(double sand_m3, double soil_m3) {
    if (!std::isfinite(sand_m3) || !std::isfinite(soil_m3) || sand_m3<0 || soil_m3<0 ||
        sand_m3+soil_m3<=0 || sand_m3>carried_.sand_m3 || soil_m3>carried_.soil_m3)
        throw std::invalid_argument("transfer needs positive finite quantities already carried");
    // Allocate/serialize before mutation. The source has no thermal state, so
    // do not invent a cold temperature or pretend transported heat is known.
    Json contents=Json::array();
    if (sand_m3>0) contents.push_back({{"substance","sand"},{"volume_m3",sand_m3},
        {"mass_kg",sand_m3*sandMaterial().density_kg_m3}});
    if (soil_m3>0) contents.push_back({{"substance","soil"},{"volume_m3",soil_m3},
        {"mass_kg",soil_m3*soilMaterial().density_kg_m3}});
    const std::string packet=Json{{"schema","banjo.bulk-material.v1"},{"source","excavated_ground"},
        {"form","granular"},{"thermal_state","unmodeled"},{"contents",contents}}.dump();
    carried_.sand_m3-=sand_m3;carried_.soil_m3-=soil_m3;
    exported_.sand_m3+=sand_m3;exported_.soil_m3+=soil_m3;
    return packet;
}

void Environment::returnCarried(double sand_m3, double soil_m3, double carried_objects_kg) {
    if (!std::isfinite(carried_objects_kg) || carried_objects_kg<0)
        throw std::invalid_argument("invalid carried object mass");
    if (!std::isfinite(sand_m3) || !std::isfinite(soil_m3) || sand_m3<0 || soil_m3<0 ||
        sand_m3+soil_m3<=0 || sand_m3>exported_.sand_m3-returned_.sand_m3 ||
        soil_m3>exported_.soil_m3-returned_.soil_m3)
        throw std::invalid_argument("return needs positive quantities previously exported and not returned");
    const double kg=sand_m3*sandMaterial().density_kg_m3+soil_m3*soilMaterial().density_kg_m3;
    if (!std::isfinite(kg) || kg>carry_limit_kg_-carriedKg()-carried_objects_kg)
        throw std::invalid_argument("returned material exceeds carrying capacity");
    carried_.sand_m3+=sand_m3;carried_.soil_m3+=soil_m3;
    returned_.sand_m3+=sand_m3;returned_.soil_m3+=soil_m3;
}

EditEffect Environment::dig(JoltWorld &world, double ax, double az, double bx, double bz,
                            double width_m, double depth_m, double carried_objects_kg) {
    if (!std::isfinite(carried_objects_kg) || carried_objects_kg<0)
        throw std::invalid_argument("invalid carried object mass");
    EditEffect effect;
    terrain_->resetActivity();
    // What comes out is carried, so no more comes out than can be.
    effect.edit = terrain_->dig(ax, az, bx, bz, width_m, depth_m,
                                std::max(0.0, carry_limit_kg_ - carriedKg() - carried_objects_kg));
    carry(effect.edit.moved);
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
    putBack(sand_m3, soil_m3);
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
    if (!(discharge_m3_s >= 0.0) || !std::isfinite(discharge_m3_s)) return false;
    if (network_) {
        // A source that became a connection feeds what stands at the top of it:
        // the basin met at the edge, or the one the reach there comes down from.
        for (const Link &link : links_) {
            if (!link.replaced_source || link.name != river) continue;
            int node = link.end.node;
            if (node == water::RiverNetwork::kOpen)
                node = network_->reaches()[static_cast<std::size_t>(link.end.reach)].from;
            if (node == water::RiverNetwork::kOpen) return false;
            return network_->setFeed(network_->nodes()[static_cast<std::size_t>(node)].name, discharge_m3_s);
        }
        // A basin, spring or junction beyond the edges, fed by its own name.
        if (network_->setFeed(river, discharge_m3_s)) return true;
    }
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
                          {"weight_n", a.weight_n}, {"lift_share", a.lift_share},
                          {"floats", a.lift_share >= kFloatsShare}});
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
                    {"carried", carriedJson(carried_)},
                    {"exported", carriedJson(exported_)},
                    {"returned", carriedJson(returned_)},
                    {"residual", volumesJson(residual)},
                    {"unsettled_columns", terrain_->unsettled()},
                    {"bare_rock", bare}}},
        {"water", {{"time_s", ws.time_s}, {"volume_m3", water_->volume()}, {"wet_area_m2", water_->wetArea()},
                   {"cells", g.cells()}, {"wet_cells", water_->wetCells()}, {"active_cells", ws.active_cells},
                   {"active_tiles", ws.active_tiles}, {"tiles", ws.tiles},
                   {"inflow_m3_s", water_->inflowRate()}, {"outflow_m3_s", water_->outflowRate()},
                   {"substeps", ws.substeps}, {"last_substep_s", ws.last_substep_s},
                   {"wave_speed_m_s", ws.max_speed_m_s}, {"clamped", ws.clamped},
                   {"speed_capped", ws.speed_capped},
                   {"ledger", {{"initial_m3", wl.initial_m3}, {"inflow_m3", wl.inflow_m3},
                               {"outflow_m3", wl.outflow_m3}, {"numerical_m3", wl.numerical_m3},
                               {"across_m3", wl.across_m3}, {"added_m3", wl.added_m3},
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
                   {"water_tile_cells_scanned", stats_.water_tile_cells_scanned},
                   {"water_tile_checks", stats_.water_tile_checks},
                   {"obstacle_cells_checked", stats_.obstacle_cells_checked},
                   {"obstacle_cells_changed", stats_.obstacle_cells_changed},
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
    if (network_) {
        // The river network beyond the edges, and one account for all the
        // water: this region's and the network's, against what was there, plus
        // everything fed from beyond the world, less everything let go to it.
        // What crossed between them is in both ledgers with opposite signs.
        const water::RiverNetwork &net = *network_;
        const auto endName = [&](int k) {
            return k == water::RiverNetwork::kOpen ? std::string("the valley")
                                                   : net.nodes()[static_cast<std::size_t>(k)].name;
        };
        Json basins = Json::array(), junctions = Json::array(), reaches = Json::array();
        for (const water::RiverNetwork::Node &n : net.nodes())
            (n.junction ? junctions : basins)
                .push_back({{"name", n.name}, {"level_m", n.level_m}, {"volume_m3", n.volume_m3},
                            {"bed_m", n.storage.bottom()}, {"area_m2", n.storage.area(n.level_m)},
                            {"fed_m3_s", n.fed_m3_s}, {"out_m3_s", n.out_rate_m3_s},
                            {"across_m3_s", n.across_rate_m3_s}, {"from_reaches_m3_s", n.from_reaches_rate_m3_s},
                            {"outlet", n.has_outlet ? Json{{"crest_m", n.crest_m}, {"width_m", n.outlet_width_m}}
                                                    : Json(nullptr)},
                            {"ledger", {{"initial_m3", n.initial_m3}, {"fed_m3", n.fed_m3}, {"out_m3", n.out_m3},
                                        {"across_m3", n.across_m3}, {"from_reaches_m3", n.from_reaches_m3},
                                        {"numerical_m3", n.numerical_m3}}}});
        for (std::size_t k = 0; k < net.reaches().size(); ++k) {
            const water::RiverNetwork::Reach &r = net.reaches()[k];
            reaches.push_back({{"name", r.name}, {"from", endName(r.from)}, {"to", endName(r.to)},
                               {"length_m", r.length_m}, {"width_m", r.width_m}, {"cells", r.cells},
                               {"manning_n", r.manning_n > 0.0 ? r.manning_n : net.settings().manning_n},
                               {"bed_m", r.bed_m}, {"level_m", r.level_m}, {"q_m3_s", r.q_m3_s},
                               {"in_m3_s", r.q_m3_s.front()}, {"middle_m3_s", r.q_m3_s[r.q_m3_s.size() / 2]},
                               {"out_m3_s", r.q_m3_s.back()}, {"volume_m3", net.reachVolume(k)},
                               {"froude_now", r.froude_now}, {"froude_held", r.froude_held},
                               {"ledger", {{"initial_m3", r.initial_m3}, {"across_m3", r.across_m3},
                                           {"numerical_m3", r.numerical_m3}}}});
        }
        Json links = Json::array();
        for (const Link &l : links_) {
            Json link = {{"name", l.name}, {"into_this_region_m3_s", water_->crossingRate(l.connection)}};
            if (l.end.node != water::RiverNetwork::kOpen) {
                link["to"] = net.nodes()[static_cast<std::size_t>(l.end.node)].name;
                link["basin"] = link["to"];
            } else {
                link["to"] = net.reaches()[static_cast<std::size_t>(l.end.reach)].name;
                link["end"] = l.end.at_to ? "to" : "from";
            }
            links.push_back(link);
        }
        const water::RiverNetwork::Totals t = net.totals();
        const double held = water_->volume() + net.volume();
        const double expected = wl.initial_m3 + wl.inflow_m3 - wl.outflow_m3 + wl.added_m3 + wl.numerical_m3 +
                                t.initial_m3 + t.fed_m3 - t.out_m3 + t.numerical_m3;
        report["watershed"] = {{"basins", basins}, {"junctions", junctions}, {"reaches", reaches},
                               {"connections", links},
                               {"network", {{"time_s", net.timeS()}, {"substeps", net.stats().substeps},
                                            {"faces_computed", net.stats().faces_computed},
                                            {"shared_out", net.stats().shared_out}}},
                               {"water_held_m3", held}, {"unaccounted_m3", held - expected}};
    }
    if (full) {
        const water::Settings &s = water_->settings();
        const water::CouplingSettings &c = coupling_.settings();
        Json materials = Json::array();
        for (const GroundMaterial *m : {&rockMaterial(), &soilMaterial(), &sandMaterial()})
            materials.push_back({{"name", m->name}, {"density_kg_m3", m->density_kg_m3},
                                 {"friction_angle_deg", m->friction_angle_deg},
                                 {"cohesion_pa", m->cohesion_pa},
                                 {"rolling_resistance", m->rolling_resistance}});
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
        if (network_) {
            const water::NetworkSettings &n = network_->settings();
            report["model"]["network"] = {
                {"scheme", "local inertial (Bates, Horritt & Fewtrell 2010): each face's discharge from what it "
                           "carried, the fall of the surface across it and semi-implicit Manning friction -- "
                           "blended with its neighbours' only where theta is below 1 (de Almeida, Bates, Freer & "
                           "Souvignet 2012); the level is the state, so still water stays exactly still"},
                {"theta", n.theta}, {"cfl", n.cfl}, {"manning_n", n.manning_n},
                {"froude_limit", n.froude_limit}, {"dry_m", n.dry_m},
                {"provenance", "declared: the detailed water's own bed by default, not calibrated to any river"}};
        }
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
            "beyond the edges, only a coarse river network: one-dimensional reaches with no advection of "
            "momentum (subcritical flow -- a face past Froude 1 inside a reach is held there and counted), "
            "junctions and basins held as level pools or stage-storage curves; no floodplain beside a reach, and "
            "no coarse-to-fine transitions yet (milestone 2)"};
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
                              {"across_m3", s.ledger.across_m3}, {"added_m3", s.ledger.added_m3},
                              {"impulse_in_x_n_s", s.ledger.impulse_in_x_n_s},
                              {"impulse_in_z_n_s", s.ledger.impulse_in_z_n_s},
                              {"impulse_dropped_n_s", s.ledger.impulse_dropped_n_s}}}};
    if (network_) {
        // The river network beyond the edges, by name: each basin's and
        // junction's volume and level, each reach cell for cell, every ledger,
        // and the network's clock -- a world opened again from these goes on
        // from where this one was, to the bit.
        const water::RiverNetwork &net = *network_;
        Json nodes = Json::array(), reaches = Json::array();
        for (std::size_t k = 0; k < net.nodes().size(); ++k) {
            const water::RiverNetwork::NodeState n = net.nodeState(k);
            nodes.push_back({{"name", net.nodes()[k].name}, {"volume_m3", n.volume_m3}, {"level_m", n.level_m},
                             {"initial_m3", n.initial_m3}, {"fed_m3", n.fed_m3}, {"out_m3", n.out_m3},
                             {"across_m3", n.across_m3}, {"from_reaches_m3", n.from_reaches_m3},
                             {"numerical_m3", n.numerical_m3}});
        }
        for (std::size_t k = 0; k < net.reaches().size(); ++k) {
            const water::RiverNetwork::ReachState r = net.reachState(k);
            reaches.push_back({{"name", net.reaches()[k].name}, {"level_m", r.level_m}, {"q_m3_s", r.q_m3_s},
                               {"initial_m3", r.initial_m3}, {"across_m3", r.across_m3},
                               {"numerical_m3", r.numerical_m3}, {"froude_held", r.froude_held}});
        }
        state["network"] = {{"time_s", net.timeS()}, {"nodes", nodes}, {"reaches", reaches}};
    }
    return state.dump();
}

std::string Environment::surveyJson(double x, double z) const {
    const auto cell = terrain_->cellAt(x, z);
    if (!cell) return Json{{"on_the_ground", false}}.dump();
    const std::size_t c = *cell;
    Json out = {{"on_the_ground", true}, {"x_m", x}, {"z_m", z}, {"ground_m", terrain_->heightAt(x, z)},
                {"rock_top_m", terrain_->rockTop(c)}, {"soil_m", terrain_->soil(c)},
                {"sand_m", terrain_->sand(c)}, {"loose_soil_m", terrain_->looseSoil(c)},
                {"surface", surfaceName(terrain_->surface(c))},
                // The ground's own share of a ball's rolling resistance here;
                // the ball adds its own, and it rests on a slope whose tangent
                // is below the sum.
                {"rolling_resistance", groundMaterialOf(terrain_->surface(c)).rolling_resistance},
                {"slope_deg", terrain_->slopeDeg(c)}};
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

Environment::WaterBox Environment::waterBox(double base_m, double shown_m) const {
    WaterBox out;
    const water::ShallowWater &w = *water_;
    const water::Grid &g = w.grid();
    const double dry = w.settings().dry_m;
    const int t = w.tileSize();
    const std::size_t across = static_cast<std::size_t>(w.tilesX());
    // Every column that may hold water: the tiles computed, and the tiles a
    // column was changed in since the last substep -- or all of them, before
    // any has been read.
    std::vector<std::size_t> tiles;
    if (w.tilesUnread()) {
        tiles.resize(across * static_cast<std::size_t>((g.nz + t - 1) / t));
        for (std::size_t k = 0; k < tiles.size(); ++k) tiles[k] = k;
    } else {
        tiles = w.activeTiles();
        tiles.insert(tiles.end(), w.changedTiles().begin(), w.changedTiles().end());
        std::sort(tiles.begin(), tiles.end());
        tiles.erase(std::unique(tiles.begin(), tiles.end()), tiles.end());
    }
    int i0 = g.nx, j0 = g.nz, i1 = -1, j1 = -1;
    for (const std::size_t tile : tiles) {
        const int tx = static_cast<int>(tile % across), tz = static_cast<int>(tile / across);
        const int ie = std::min(g.nx, (tx + 1) * t), je = std::min(g.nz, (tz + 1) * t);
        for (int j = tz * t; j < je; ++j)
            for (int i = tx * t; i < ie; ++i) {
                const double h = w.depth(g.at(i, j));
                if (h > dry) ++out.wet_cells;
                if (!(h > shown_m)) continue;
                i0 = std::min(i0, i); i1 = std::max(i1, i);
                j0 = std::min(j0, j); j1 = std::max(j1, j);
            }
    }
    if (i1 < 0) return out;
    out.i0 = i0;
    out.j0 = j0;
    out.ni = i1 - i0 + 1;
    out.nj = j1 - j0 + 1;
    const std::size_t n = static_cast<std::size_t>(out.ni) * static_cast<std::size_t>(out.nj);
    out.surface_mm.assign(n, 0);
    out.flow.assign(2 * n, 0);
    for (int j = 0; j < out.nj; ++j)
        for (int i = 0; i < out.ni; ++i) {
            const std::size_t c = g.at(i0 + i, j0 + j);
            const std::size_t k = static_cast<std::size_t>(j) * static_cast<std::size_t>(out.ni) +
                                  static_cast<std::size_t>(i);
            const double h = w.depth(c);
            if (h > shown_m) {
                const double mm = std::round((w.surface(c) - base_m) * 1000.0);
                out.surface_mm[k] = static_cast<std::uint16_t>(std::clamp(mm, 1.0, 65535.0));
            }
            if (h > 0.003) {
                out.flow[2 * k] = static_cast<std::int8_t>(std::clamp(std::round(w.velocityX(c) / 0.05), -127.0, 127.0));
                out.flow[2 * k + 1] = static_cast<std::int8_t>(std::clamp(std::round(w.velocityZ(c) / 0.05), -127.0, 127.0));
            }
        }
    return out;
}

} // namespace banjo::terrain
