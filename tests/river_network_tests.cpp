// The coarse river network (docs/watershed.md, W3): what it keeps exactly --
// still water, every cubic metre, its clock, its state carried into another --
// and that its reaches carry what the fall of the water and Manning's law say,
// either way, through junctions, onto dry ground, and across a connection to
// the detailed water on one account.
#include "water/RiverNetwork.hpp"
#include "water/ShallowWater.hpp"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <deque>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using namespace banjo::water;
using Node = RiverNetwork::Node;
using Reach = RiverNetwork::Reach;
using Endpoint = RiverNetwork::Endpoint;

void require(bool condition, std::string_view message) {
    if (!condition) throw std::runtime_error(std::string(message));
}

void near(double actual, double expected, double tolerance, std::string_view message) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(message) + ": actual=" + std::to_string(actual) +
                                 " expected=" + std::to_string(expected) +
                                 " tolerance=" + std::to_string(tolerance));
}

Node basin(std::string name, double bed_m, double area_m2, double fed_m3_s = 0.0) {
    Node n;
    n.name = std::move(name);
    n.storage = StageStorage::prism(bed_m, area_m2);
    n.fed_m3_s = fed_m3_s;
    return n;
}

Node junction(std::string name, double bed_m, double area_m2) {
    Node n = basin(std::move(name), bed_m, area_m2);
    n.junction = true;
    return n;
}

Node withOutlet(Node n, double crest_m, double width_m) {
    n.has_outlet = true;
    n.crest_m = crest_m;
    n.outlet_width_m = width_m;
    return n;
}

Reach reach(std::string name, int from, int to, double length_m, double width_m, double bed_from_m,
            double bed_to_m, int cells) {
    Reach r;
    r.name = std::move(name);
    r.from = from;
    r.to = to;
    r.length_m = length_m;
    r.width_m = width_m;
    r.bed_from_m = bed_from_m;
    r.bed_to_m = bed_to_m;
    r.cells = cells;
    return r;
}

// Everything that changes, for comparing two networks, or one with itself.
std::vector<double> stateOf(const RiverNetwork &net) {
    std::vector<double> all;
    for (const Node &n : net.nodes()) {
        all.push_back(n.volume_m3);
        all.push_back(n.level_m);
    }
    for (const Reach &r : net.reaches()) {
        all.insert(all.end(), r.level_m.begin(), r.level_m.end());
        all.insert(all.end(), r.q_m3_s.begin(), r.q_m3_s.end());
    }
    return all;
}

// A reservoir and a spring feeding a confluence, a river on to a lake, and a
// channel up from the lake to a pond on higher ground -- part of it above the
// water, so the network has a shore.
struct Watershed {
    RiverNetwork net;
    int reservoir{}, confluence{}, spring{}, lake{}, high{};
    explicit Watershed(double level_m, double reservoir_level_m) {
        reservoir = net.addNode(basin("the reservoir", 0.2, 400.0), reservoir_level_m);
        confluence = net.addNode(junction("the confluence", -0.4, 20.0), level_m);
        spring = net.addNode(basin("the spring", 0.5, 30.0), level_m);
        lake = net.addNode(basin("the lake", -1.0, 2000.0), level_m);
        high = net.addNode(basin("the high pond", 1.5, 50.0), level_m);
        net.addReach(reach("the river", reservoir, confluence, 60.0, 3.0, 0.9, 0.1, 6), 0.0, 0.0);
        net.addReach(reach("the brook", spring, confluence, 30.0, 1.2, 0.8, 0.1, 5), 0.0, 0.0);
        net.addReach(reach("the river below", confluence, lake, 40.0, 3.5, 0.1, -0.3, 4), 0.0, 0.0);
        net.addReach(reach("the high channel", lake, high, 50.0, 2.0, -0.3, 1.5, 5), 0.0, 0.0);
        for (std::size_t k = 0; k < net.reaches().size(); ++k) net.standReach(k, level_m);
        net.resetLedger();
    }
};

// 1. Still water at one level, through basins, reaches, a junction and up to a
// shore, stays EXACTLY still: every level and discharge the same to the bit,
// over an hour of the network's own coarse steps and a minute of the detailed
// water's strides.
void stillWaterStaysExactlyStill() {
    Watershed shed(1.3, 1.3);
    const std::vector<double> before = stateOf(shed.net);
    const double v0 = shed.net.volume();
    int substeps = 0;
    for (int k = 0; k < 1800; ++k) substeps += shed.net.advance(2.0);
    for (int k = 0; k < 3600; ++k) substeps += shed.net.advance(1.0 / 60.0);
    require(substeps >= 5400, "it was stepped");
    require(stateOf(shed.net) == before, "a level or a discharge moved");
    require(shed.net.volume() == v0 && shed.net.residual() == 0.0, "and not a drop moved");
    const Reach &high = shed.net.reaches()[3];
    require(high.level_m.back() == high.bed_m.back(), "the channel's top end is above the water, dry");
    std::cout << "    " << substeps << " substeps, " << shed.net.stats().faces_computed
              << " faces computed: every level and discharge as it was, to the bit\n";
}

// The level a closed network's water comes to rest at: the one level at which
// every node and cell together hold all of it.
double levelHolding(const RiverNetwork &net, double volume_m3) {
    const auto held = [&](double level) {
        double v = 0.0;
        for (const Node &n : net.nodes()) v += n.storage.volume(level);
        for (const Reach &r : net.reaches())
            for (std::size_t c = 0; c < r.level_m.size(); ++c)
                v += std::max(0.0, level - r.bed_m[c]) * r.width_m * r.dx_m;
        return v;
    };
    double lo = -10.0, hi = 10.0;
    for (int k = 0; k < 200; ++k) {
        const double mid = 0.5 * (lo + hi);
        (held(mid) < volume_m3 ? lo : hi) = mid;
    }
    return 0.5 * (lo + hi);
}

// What the water would give up coming to rest at `rest_m`: the weight of the
// water standing above that level everywhere (or the hollow below it), and its
// motion through every face. Every node here is a prism.
double energyAbove(const RiverNetwork &net, double rest_m) {
    constexpr double rho = 1000.0, g = 9.81;
    const auto column = [&](double level, double bed, double area) {
        // Relative to how it stands at rest: filled to `rest_m` over a bed below
        // it, empty over one above.
        const double floor = std::max(bed, rest_m);
        return 0.5 * rho * g * area * ((level - rest_m) * (level - rest_m) - (floor - rest_m) * (floor - rest_m));
    };
    double e = 0.0;
    for (const Node &n : net.nodes())
        e += column(n.level_m, n.storage.bottom(), n.storage.area(n.level_m));
    for (const Reach &r : net.reaches()) {
        const double a = r.width_m * r.dx_m;
        const std::size_t cells = r.level_m.size();
        for (std::size_t c = 0; c < cells; ++c) e += column(r.level_m[c], r.bed_m[c], a);
        for (std::size_t f = 0; f <= cells; ++f) {
            const double el = f == 0 ? net.nodes()[static_cast<std::size_t>(r.from)].level_m : r.level_m[f - 1];
            const double er = f == cells ? net.nodes()[static_cast<std::size_t>(r.to)].level_m : r.level_m[f];
            const double bl = f == 0 ? r.bed_from_m : r.bed_m[f - 1];
            const double br = f == cells ? r.bed_to_m : r.bed_m[f];
            const double h = std::max(el, er) - std::max(bl, br);
            if (h > 1.0e-3) e += 0.5 * rho * r.q_m3_s[f] * r.q_m3_s[f] * r.dx_m / (r.width_m * h);
        }
    }
    return e;
}

// 2. A closed network -- nothing fed, nothing let out -- keeps its water to
// rounding while a reservoir set higher than the rest drains through the
// reaches and the junction into everything else. It rings on towards the one
// level that holds all of it: the water between the reservoir and the lake
// swings back and forth, rubbed only by the bed (Manning friction, which
// weakens as the square of the speed, so the last few millimetres of a swing
// die slowly), and its energy above that level falls hour by hour while the
// reservoir's level, averaged over a swing, is that level.
void aClosedNetworkKeepsItsWaterAndRingsDownToOneLevel() {
    Watershed shed(1.0, 1.6);
    const double v0 = shed.net.volume();
    const double rest = levelHolding(shed.net, v0);
    const double e0 = energyAbove(shed.net, rest);
    std::vector<double> hourly(6, 0.0);
    double sum_last_hour = 0.0;
    int samples_last_hour = 0, crossings = 0;
    double was = 0.0;
    struct Range { double lo{1.0e9}, hi{-1.0e9}; void see(double v) { lo = std::min(lo, v); hi = std::max(hi, v); } };
    Range res, lake, conf, cell;
    const auto &nodes = shed.net.nodes();
    for (int hour = 0; hour < 6; ++hour)
        for (int sample = 0; sample < 1800; ++sample) {
            shed.net.advance(2.0);
            hourly[static_cast<std::size_t>(hour)] =
                std::max(hourly[static_cast<std::size_t>(hour)], energyAbove(shed.net, rest));
            if (hour == 5) {
                const double r = nodes[static_cast<std::size_t>(shed.reservoir)].level_m;
                sum_last_hour += r;
                ++samples_last_hour;
                res.see(r);
                lake.see(nodes[static_cast<std::size_t>(shed.lake)].level_m);
                conf.see(nodes[static_cast<std::size_t>(shed.confluence)].level_m);
                cell.see(shed.net.reaches()[0].level_m[3]);
                if (sample > 0 && ((r - rest) > 0.0) != (was > 0.0)) ++crossings;
                was = r - rest;
            }
        }
    const double mean = sum_last_hour / samples_last_hour;
    {
        // Where the energy is, at the end: each node's and reach's share, and how
        // far each stands from rest.
        constexpr double rho = 1000.0, g = 9.81;
        for (const Node &n : nodes) {
            const double floor = std::max(n.storage.bottom(), rest);
            const double e = 0.5 * rho * g * n.storage.area(n.level_m) *
                             ((n.level_m - rest) * (n.level_m - rest) - (floor - rest) * (floor - rest));
            std::cout << "      " << n.name << ": " << n.level_m - rest << " m from rest, " << e << " J\n";
        }
        for (const Reach &r : shed.net.reaches()) {
            double e = 0.0, far = 0.0, fastest = 0.0;
            for (std::size_t c = 0; c < r.level_m.size(); ++c) {
                const double floor = std::max(r.bed_m[c], rest);
                e += 0.5 * rho * g * r.width_m * r.dx_m *
                     ((r.level_m[c] - rest) * (r.level_m[c] - rest) - (floor - rest) * (floor - rest));
                if (r.level_m[c] > r.bed_m[c] + 1.0e-3) far = std::max(far, std::abs(r.level_m[c] - rest));
            }
            for (const double q : r.q_m3_s) fastest = std::max(fastest, std::abs(q));
            std::cout << "      " << r.name << ": wet cells within " << far << " m of rest, " << e
                      << " J standing, fastest face " << fastest << " m^3/s\n";
        }
    }
    std::cout << "      the last hour: reservoir " << res.lo - rest << " to " << res.hi - rest << " m about rest, lake "
              << lake.lo - rest << " to " << lake.hi - rest << ", confluence " << conf.lo - rest << " to "
              << conf.hi - rest << ", the river's cell 3 " << cell.lo - rest << " to " << cell.hi - rest
              << "; the reservoir crossed rest " << crossings << " times: a period of "
              << (crossings > 0 ? 7200.0 / crossings : 0.0) << " s\n";
    std::cout << "    reservoir 1.6 m, the rest 1.0 m; they hold their water at " << rest
              << " m. Energy above that level " << e0 << " J at the start, the most in each hour:";
    for (const double e : hourly) std::cout << ' ' << e;
    std::cout << " J; the reservoir over the last hour " << mean << " m on average; residual "
              << shed.net.residual() << " m^3\n";
    near(shed.net.volume(), v0, 1.0e-12 * v0, "not a cubic metre made or lost");
    near(shed.net.residual(), 0.0, 1.0e-12 * v0, "the ledger closes");
    for (std::size_t h = 1; h < hourly.size(); ++h)
        require(hourly[h] < hourly[h - 1], "its energy falls hour by hour: nothing drives it");
    require(hourly.back() < 1.0e-3 * e0, "and all but a thousandth of it is gone in six hours");
    near(mean, rest, 0.001, "swinging about the one level that holds all its water");
}

// 3. A long reach fed a steady discharge settles to Manning's normal depth for
// its slope, width and roughness -- q = h^(5/3) S^(1/2) / n per metre of width,
// the law the detailed water's bed uses -- and passes the discharge it is fed.
void aLongReachSettlesToManningsNormalDepth() {
    const double q_total = 0.6, width = 4.0, slope = 0.002, n = 0.03, length = 2000.0;
    RiverNetwork net;
    const int head = net.addNode(basin("the head pond", 3.9, 60.0, q_total), 4.1);
    const int foot = net.addNode(withOutlet(basin("the tail pool", -2.0, 200.0), -1.5, 10.0), -1.5);
    Reach r = reach("the long reach", head, foot, length, width, 4.0, 4.0 - slope * length, 100);
    r.manning_n = n;
    net.addReach(r, 0.2, q_total);
    net.resetLedger();
    for (int k = 0; k < 3 * 3600 / 2; ++k) net.advance(2.0);
    const double normal = std::pow(n * (q_total / width) / std::sqrt(slope), 3.0 / 5.0);
    const Reach &long_reach = net.reaches()[0];
    double worst_depth = 0.0, worst_flow = 0.0;
    for (std::size_t c = 33; c < 67; ++c) {
        worst_depth = std::max(worst_depth, std::abs(long_reach.level_m[c] - long_reach.bed_m[c] - normal) / normal);
        worst_flow = std::max(worst_flow, std::abs(long_reach.q_m3_s[c] - q_total) / q_total);
    }
    const double mid = long_reach.level_m[50] - long_reach.bed_m[50];
    // Where it falls freely into the pool below it, the brink passes the
    // critical discharge for its depth: the last cell stands at critical depth.
    const double critical = std::cbrt((q_total / width) * (q_total / width) / 9.81);
    const double brink = long_reach.level_m.back() - long_reach.bed_m.back();
    std::cout << "    normal depth " << normal << " m; the middle third " << mid << " m, off by at most "
              << 100.0 * worst_depth << "%; passing " << long_reach.q_m3_s[50] << " m^3/s of " << q_total
              << ", off by at most " << 100.0 * worst_flow << "%; Froude inside it " << long_reach.froude_now
              << "; at the brink " << brink << " m against critical depth " << critical << " m\n";
    require(worst_depth < 0.01, "the middle of the reach runs at Manning's normal depth");
    require(worst_flow < 0.005, "and passes what it is fed");
    // Inside the regime all along it: no face inside the reach held. Its middle
    // runs well below critical; the water speeds up towards the brink, as it does.
    const double froude_mid = (q_total / width) / (mid * std::sqrt(9.81 * mid));
    std::cout << "    Froude in the middle " << froude_mid << ", rising to " << long_reach.froude_now
              << " beside the brink; faces inside held " << long_reach.froude_held << " times\n";
    require(long_reach.froude_held == 0 && froude_mid < 0.5, "a gentle river is inside the regime this covers");
    near(brink, critical, 0.001 * critical, "it falls freely into the pool at critical depth");
    near(net.residual(), 0.0, 1.0e-10 * net.volume(), "the ledger closes");
}

// 4. What a reach carries is decided by the water at its two ends: from the
// higher to the lower, and back again once the lower is raised above it.
void aReachRunsEitherWayByTheLevelsAtItsEnds() {
    // Ponds far bigger than what the cut carries in a minute, so the fall
    // across it is the one set, not the ponds sloshing back and forth.
    RiverNetwork net;
    const double area = 20000.0;
    const int a = net.addNode(basin("the upper pond", 0.0, area), 1.0);
    const int b = net.addNode(basin("the lower pond", 0.0, area), 0.95);
    net.addReach(reach("the cut", a, b, 40.0, 2.0, 0.1, 0.1, 4), 0.875, 0.0);
    net.resetLedger();
    for (int k = 0; k < 60 * 60; ++k) net.advance(1.0 / 60.0);
    const double forward = net.reaches()[0].q_m3_s[2];
    const double a_level = net.nodes()[static_cast<std::size_t>(a)].level_m;
    const double b_level = net.nodes()[static_cast<std::size_t>(b)].level_m;
    // Raise the lower pond 5 cm above the upper one, from beyond.
    const Endpoint lower{b, RiverNetwork::kOpen, false};
    net.startExchange();
    net.exchange(lower, (a_level + 0.05 - b_level) * area, 1.0);
    for (int k = 0; k < 60 * 60; ++k) net.advance(1.0 / 60.0);
    const double backward = net.reaches()[0].q_m3_s[2];
    std::cout << "    the upper pond " << 100.0 * (a_level - b_level) << " cm higher: " << forward
              << " m^3/s down the cut; the lower raised 5 cm above it: " << backward
              << " m^3/s back up it; residual " << net.residual() << " m^3\n";
    require(forward > 0.1, "water runs from the higher pond to the lower");
    require(backward < -0.1, "and back when the lower is raised above it");
    near(net.residual(), 0.0, 1.0e-12 * net.volume(), "what was put in from beyond is counted");
}

// 5. Where two rivers meet, what leaves is what came in: at steady state the
// river below the junction carries both rivers above it, the lake lets out what
// it is sent, and every cubic metre is on the ledger.
void aJunctionPassesWhatComesIntoIt() {
    RiverNetwork net;
    const int a = net.addNode(basin("the first spring", 1.0, 30.0, 0.3), 1.15);
    const int b = net.addNode(basin("the second spring", 1.2, 20.0, 0.1), 1.3);
    const int j = net.addNode(junction("the confluence", 0.4, 15.0), 0.6);
    const int lake = net.addNode(withOutlet(basin("the lake", -1.0, 500.0), -0.2, 3.0), -0.1);
    net.addReach(reach("the river", a, j, 100.0, 3.0, 1.0, 0.5, 10), 0.15, 0.3);
    net.addReach(reach("the brook", b, j, 80.0, 1.5, 1.2, 0.5, 8), 0.1, 0.1);
    net.addReach(reach("the river below", j, lake, 100.0, 3.5, 0.5, 0.0, 10), 0.2, 0.4);
    net.resetLedger();
    for (int k = 0; k < 3 * 3600 / 2; ++k) net.advance(2.0);
    const Reach &below = net.reaches()[2];
    const Node &l = net.nodes()[static_cast<std::size_t>(lake)];
    const double in = net.reaches()[0].q_m3_s.back() + net.reaches()[1].q_m3_s.back();
    std::cout << "    into the confluence " << in << " m^3/s, out of it " << below.q_m3_s.front()
              << ", down the river " << below.q_m3_s[5] << ", over the lake's outlet " << l.out_rate_m3_s
              << "; residual " << net.residual() << " m^3\n";
    near(below.q_m3_s.front(), in, 0.005 * in, "the junction passes what comes into it");
    near(below.q_m3_s[5], 0.4, 0.005 * 0.4, "the river below carries both springs");
    near(l.out_rate_m3_s, 0.4, 0.01 * 0.4, "and the lake lets out what it is sent");
    near(net.residual(), 0.0, 1.0e-10 * net.volume(), "every cubic metre on the ledger");
}

// 6. A dry reach wets from the end water arrives at: the front moves down it,
// no cell goes below its bed, and every cubic metre that left the reservoir is
// in the reach or the basin below.
void aDryReachWetsFromTheEndWaterArrivesAt() {
    RiverNetwork net;
    const int res = net.addNode(basin("the reservoir", 0.5, 300.0), 1.2);
    const int low = net.addNode(basin("the basin", -0.5, 300.0), -0.5);
    net.addReach(reach("the dry bed", res, low, 200.0, 2.0, 0.9, 0.3, 20), 0.0, 0.0);
    net.resetLedger();
    const double v0 = net.volume();
    int last_front = 0;
    std::vector<int> fronts;
    for (int t = 1; t <= 240; ++t) {
        for (int k = 0; k < 60; ++k) net.advance(1.0 / 60.0);
        const Reach &r = net.reaches()[0];
        int front = 0;
        for (std::size_t c = 0; c < r.level_m.size(); ++c) {
            require(r.level_m[c] >= r.bed_m[c], "no cell goes below its bed");
            if (r.level_m[c] - r.bed_m[c] > 1.0e-3) front = static_cast<int>(c) + 1;
        }
        if (t % 30 == 0) fronts.push_back(front);
        require(front >= last_front - 1, "the front does not fall back");
        last_front = std::max(last_front, front);
    }
    std::cout << "    wet cells every 30 s:";
    for (const int f : fronts) std::cout << ' ' << f;
    std::cout << "; the basin " << net.nodes()[static_cast<std::size_t>(low)].volume_m3 << " m^3; residual "
              << net.residual() << " m^3 (put back " << net.reaches()[0].numerical_m3 << ")\n";
    require(fronts.front() > 0 && fronts.front() < 20, "the front was part way down after half a minute");
    require(fronts.back() == 20, "and reached the end");
    require(net.nodes()[static_cast<std::size_t>(low)].volume_m3 > 0.0, "the basin below got water");
    near(net.volume(), v0 + net.totals().numerical_m3, 1.0e-12 * v0, "what left the reservoir is somewhere");
}

// 7. A basin's stage-storage taken from its ground holds, at each level, what
// the detailed water holds over that ground as a lake at rest -- and where the
// lake reaches a saddle the level waits there while the hollow beyond fills.
void aBasinsGroundHoldsWhatTheDetailedLakeHolds() {
    const Grid g{40, 32, 0.5, 0.0, 0.0};
    std::vector<double> bed(g.cells());
    std::size_t seed = 0;
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i) {
            const double x = g.xOf(i), z = g.zOf(j);
            const double left = 0.02 * ((x - 5.0) * (x - 5.0) + (z - 8.0) * (z - 8.0));
            const double right = 0.02 * ((x - 15.0) * (x - 15.0) + (z - 8.0) * (z - 8.0)) - 0.3;
            bed[g.at(i, j)] = std::min(left, right) + 0.03 * std::sin(1.7 * x) * std::cos(1.1 * z);
        }
    // The lake starts in the left hollow, the shallower one.
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < 20; ++i)
            if (bed[g.at(i, j)] < bed[seed] || (i == 0 && j == 0)) seed = g.at(i, j);
    const StageStorage storage = StageStorage::fromGround(g.nx, g.nz, bed, g.dx * g.dx, seed);
    // The lake at a level, in detail: every column reached from the seed through
    // columns lower than the level, set to it.
    const auto detailed = [&](double level) {
        ShallowWater water(g, bed);
        std::vector<std::uint8_t> seen(g.cells(), 0);
        std::deque<std::size_t> open{seed};
        seen[seed] = 1;
        while (!open.empty()) {
            const std::size_t c = open.front();
            open.pop_front();
            if (!(bed[c] < level)) continue;
            water.setSurface(c, level);
            const int i = static_cast<int>(c % static_cast<std::size_t>(g.nx)), j = static_cast<int>(c / static_cast<std::size_t>(g.nx));
            for (const auto [di, dj] : {std::pair{-1, 0}, std::pair{1, 0}, std::pair{0, -1}, std::pair{0, 1}}) {
                if (i + di < 0 || j + dj < 0 || i + di >= g.nx || j + dj >= g.nz) continue;
                const std::size_t m = g.at(i + di, j + dj);
                if (!seen[m]) {
                    seen[m] = 1;
                    open.push_back(m);
                }
            }
        }
        return water.volume();
    };
    // The saddle between the hollows: the break point where the volume steps.
    double saddle = 0.0, before = 0.0, after = 0.0;
    for (double level = bed[seed] + 0.01; level < 3.0; level += 0.0137) {
        const double v = storage.volume(level);
        near(v, detailed(level), 1.0e-9 * std::max(1.0, v), "the curve holds what the detailed lake holds");
        near(storage.level(v), level, 1.0e-12, "and the level of that volume is that level");
    }
    for (double level = bed[seed]; level < 3.0; level += 0.0005) {
        const double step = storage.volume(level + 0.0005) - storage.volume(level);
        if (step > 60.0 * 0.0005 * g.dx * g.dx * 400.0) {
            saddle = level;
            before = storage.volume(level);
            after = storage.volume(level + 0.0005);
            break;
        }
    }
    require(saddle > 0.0, "the lake reaches the saddle into the deeper hollow");
    const double halfway = storage.level(0.5 * (before + after));
    std::cout << "    " << storage.breakPoints() << " break points; the lake reaches the saddle at " << saddle
              << " m, where " << after - before << " m^3 fills the hollow beyond with the level at "
              << halfway << " m\n";
    near(halfway, saddle, 0.0006, "the level waits at the saddle while the hollow beyond fills");
}

// 8. A reach steeper than the model covers is held to its declared limit and
// says so: no face past the Froude limit, and each hold counted.
void aTorrentIsHeldToTheRegimeAndSaysSo() {
    RiverNetwork net;
    const int top = net.addNode(basin("the spring", 4.9, 20.0, 1.0), 5.1);
    const int bottom = net.addNode(basin("the pool", -1.0, 400.0), -1.0);
    net.addReach(reach("the chute", top, bottom, 50.0, 1.0, 5.0, 0.0, 10), 0.05, 0.0);
    net.resetLedger();
    for (int k = 0; k < 5 * 60 * 60; ++k) net.advance(1.0 / 60.0);
    const Reach &chute = net.reaches()[0];
    std::cout << "    a 1-in-10 chute passing 1 m^3/s: held " << chute.froude_held
              << " times, Froude now " << chute.froude_now << "\n";
    require(chute.froude_held > 0, "a torrent is outside what this covers, and it says so");
    require(chute.froude_now <= net.settings().froude_limit * (1.0 + 1.0e-12), "no face past the limit");
    near(net.residual(), 0.0, 1.0e-10 * net.volume(), "held, not lost");
}

// 9. advance(dt) takes exactly the time asked, in substeps none longer than the
// stability limit.
void advanceTakesExactlyTheTimeAskedWithinTheLimit() {
    Watershed shed(3.0, 3.5);
    const double limit = shed.net.stableStep();
    const int steps = shed.net.advance(10.0);
    std::cout << "    10 s in " << steps << " substeps against a limit of " << limit << " s\n";
    require(shed.net.timeS() == 10.0, "exactly the time asked");
    require(steps >= static_cast<int>(10.0 / limit), "no fewer substeps than the limit allows");
    require(shed.net.stats().last_substep_s <= shed.net.stableStep() * 1.5, "none far past it");
}

// 10. A network carried into another -- each node's and reach's state and
// ledger taken and given back -- goes on as the one it came from, to the bit.
void aCarriedNetworkGoesOnBitForBit() {
    Watershed a(1.0, 1.6), b(1.0, 1.6);
    for (int k = 0; k < 600; ++k) a.net.advance(0.5);
    for (std::size_t k = 0; k < a.net.nodes().size(); ++k) b.net.restoreNode(k, a.net.nodeState(k));
    for (std::size_t k = 0; k < a.net.reaches().size(); ++k)
        require(b.net.restoreReach(k, a.net.reachState(k)), "a reach of the same cells is taken back");
    b.net.restoreClock(a.net.timeS());
    require(stateOf(a.net) == stateOf(b.net), "carried as it was");
    for (int k = 0; k < 600; ++k) {
        a.net.advance(0.5);
        b.net.advance(0.5);
    }
    require(stateOf(a.net) == stateOf(b.net), "and goes on the same, to the bit");
    require(a.net.residual() == b.net.residual(), "its ledger with it");
}

// 11. A detailed channel between two reaches: the channel's water sees each
// reach's end level and the speed of its water, what crosses is handed to the
// reach once with the opposite sign, and the reservoir upstream, the reaches,
// the channel and the basin downstream keep one account to rounding.
void aDetailedChannelBetweenTwoReachesKeepsOneAccount() {
    const Grid g{64, 12, 0.25, 0.0, 0.0};
    std::vector<double> bed(g.cells());
    for (int j = 0; j < g.nz; ++j)
        for (int i = 0; i < g.nx; ++i)
            bed[g.at(i, j)] = 0.30 - 0.20 * i / (g.nx - 1) + 0.01 * std::abs(j - 5.5);
    ShallowWater water(g, bed);
    const int west = water.addConnection({"the river in", Edge::West, 2, 9});
    const int east = water.addConnection({"the river out", Edge::East, 2, 9});
    RiverNetwork net;
    const int res = net.addNode(basin("the reservoir", 0.2, 200.0, 0.08), 0.62);
    const int pool = net.addNode(withOutlet(basin("the basin", -0.6, 300.0), -0.25, 2.0), -0.3);
    const int above = net.addReach(reach("above", res, RiverNetwork::kOpen, 30.0, 2.0, 0.5, 0.31, 6), 0.05, 0.0);
    const int below = net.addReach(reach("below", RiverNetwork::kOpen, pool, 30.0, 2.0, 0.09, -0.1, 6), 0.0, 0.0);
    water.resetLedger();
    net.resetLedger();
    const Endpoint in_end{RiverNetwork::kOpen, above, true}, out_end{RiverNetwork::kOpen, below, false};
    const double start = water.volume() + net.volume();
    const double stride = 1.0 / 60.0;
    for (int k = 0; k < 5 * 60 * 60; ++k) {
        // West: into the channel is +x, and so is out of the network. East: out
        // of the network is into the channel, -x.
        water.setFarSide(west, net.levelAt(in_end), net.speedOut(in_end));
        water.setFarSide(east, net.levelAt(out_end), -net.speedOut(out_end));
        water.advance(stride);
        net.startExchange();
        net.exchange(in_end, -water.takeCrossed(west), stride);
        net.exchange(out_end, -water.takeCrossed(east), stride);
        net.advance(stride);
    }
    const RiverNetwork::Totals t = net.totals();
    const double held = water.volume() + net.volume();
    const double expected = start + t.fed_m3 - t.out_m3 + t.numerical_m3 + water.ledger().numerical_m3;
    std::cout << "    after 5 min: " << water.crossingRate(west) << " m^3/s into the channel, "
              << -water.crossingRate(east) << " out of it; " << water.volume() << " m^3 in it; the basin "
              << net.nodes()[static_cast<std::size_t>(pool)].level_m << " m, letting out "
              << net.nodes()[static_cast<std::size_t>(pool)].out_rate_m3_s << " m^3/s; unaccounted "
              << held - expected << " m^3\n";
    require(water.crossingRate(west) > 0.02, "the reach feeds the channel");
    require(water.crossingRate(east) < -0.02, "and the channel pours into the reach below");
    require(net.nodes()[static_cast<std::size_t>(pool)].volume_m3 >
                (-0.3 + 0.6) * 300.0, "the basin downstream holds what it was sent");
    near(held, expected, 1.0e-10 * held, "one account for the network and the detailed water");
    near(t.across_m3, -water.ledger().across_m3, 1.0e-10 * held, "what crossed is in both ledgers, opposite");
}

} // namespace

int main() {
    const std::vector<std::pair<std::string_view, std::function<void()>>> tests{
        {"still water stays exactly still", stillWaterStaysExactlyStill},
        {"a closed network keeps its water and rings down to one level",
         aClosedNetworkKeepsItsWaterAndRingsDownToOneLevel},
        {"a long reach settles to Manning's normal depth", aLongReachSettlesToManningsNormalDepth},
        {"a reach runs either way by the levels at its ends", aReachRunsEitherWayByTheLevelsAtItsEnds},
        {"a junction passes what comes into it", aJunctionPassesWhatComesIntoIt},
        {"a dry reach wets from the end water arrives at", aDryReachWetsFromTheEndWaterArrivesAt},
        {"a basin's ground holds what the detailed lake holds", aBasinsGroundHoldsWhatTheDetailedLakeHolds},
        {"a torrent is held to the regime and says so", aTorrentIsHeldToTheRegimeAndSaysSo},
        {"advance takes exactly the time asked within the limit",
         advanceTakesExactlyTheTimeAskedWithinTheLimit},
        {"a carried network goes on bit for bit", aCarriedNetworkGoesOnBitForBit},
        {"a detailed channel between two reaches keeps one account",
         aDetailedChannelBetweenTwoReachesKeepsOneAccount},
    };
    unsigned failures = 0;
    for (const auto &[name, test] : tests) {
        try {
            test();
            std::cout << "[PASS] " << name << '\n';
        } catch (const std::exception &error) {
            ++failures;
            std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << tests.size() - failures << '/' << tests.size() << " tests passed\n";
    return failures == 0U ? EXIT_SUCCESS : EXIT_FAILURE;
}
