#include "water/RiverNetwork.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <numeric>
#include <queue>
#include <stdexcept>

namespace banjo::water {

namespace {

// A broad-crested weir passes (2/3)^(3/2) sqrt(g) h^(3/2) per metre of crest:
// the free outfall the detailed water's mouths use.
constexpr double kWeir = 0.5443310539518174;

std::string quoted(const std::string &name) { return "\"" + name + "\""; }

} // namespace

// ---- stage-storage -----------------------------------------------------------

StageStorage StageStorage::prism(double bed_m, double area_m2) {
    if (!std::isfinite(bed_m) || !std::isfinite(area_m2) || !(area_m2 > 0.0))
        throw std::invalid_argument("a basin needs a bed and an area greater than nothing");
    StageStorage s;
    s.level_ = {bed_m};
    s.below_ = {0.0};
    s.above_ = {0.0};
    s.slope_ = {area_m2};
    return s;
}

StageStorage StageStorage::table(const std::vector<std::pair<double, double>> &points) {
    if (points.size() < 2) throw std::invalid_argument("a stage-storage table needs two levels at least");
    if (points.front().second != 0.0) throw std::invalid_argument("a stage-storage table starts from no water");
    StageStorage s;
    for (std::size_t k = 0; k + 1 < points.size(); ++k) {
        const double l0 = points[k].first, v0 = points[k].second;
        const double l1 = points[k + 1].first, v1 = points[k + 1].second;
        if (!std::isfinite(l0) || !std::isfinite(l1) || !std::isfinite(v1) || !(l1 > l0) || !(v1 > v0))
            throw std::invalid_argument("a stage-storage table rises, in level and in volume, from row to row");
        s.level_.push_back(l0);
        s.below_.push_back(v0);
        s.above_.push_back(v0);
        s.slope_.push_back((v1 - v0) / (l1 - l0));
    }
    // Above its last row it goes on at the last segment's area.
    s.level_.push_back(points.back().first);
    s.below_.push_back(points.back().second);
    s.above_.push_back(points.back().second);
    s.slope_.push_back(s.slope_.back());
    return s;
}

StageStorage StageStorage::fromGround(int nx, int nz, const std::vector<double> &bed, double cell_area_m2,
                                      std::size_t seed) {
    const std::size_t n = nx > 0 && nz > 0 ? static_cast<std::size_t>(nx) * static_cast<std::size_t>(nz) : 0;
    if (n == 0 || bed.size() != n || seed >= n || !(cell_area_m2 > 0.0))
        throw std::invalid_argument("a basin's ground is a grid of heights, with its lake's first cell on it");
    for (const double b : bed)
        if (!std::isfinite(b)) throw std::invalid_argument("a basin's ground has a height that is not a number");
    // Priority flood from the seed: the level a column joins the lake at is the
    // lowest level any way to it from the seed can be crossed at -- its own bed,
    // or the highest ground on the best way there.
    std::vector<double> joins(n, std::numeric_limits<double>::infinity());
    std::vector<std::uint8_t> done(n, 0);
    using Item = std::pair<double, std::size_t>;
    std::priority_queue<Item, std::vector<Item>, std::greater<Item>> open;
    joins[seed] = bed[seed];
    open.emplace(bed[seed], seed);
    const std::size_t width = static_cast<std::size_t>(nx);
    while (!open.empty()) {
        const auto [level, c] = open.top();
        open.pop();
        if (done[c]) continue;
        done[c] = 1;
        const std::size_t i = c % width, j = c / width;
        const auto reach = [&](std::size_t m) {
            if (done[m]) return;
            const double via = std::max(bed[m], level);
            if (via < joins[m]) {
                joins[m] = via;
                open.emplace(via, m);
            }
        };
        if (i > 0) reach(c - 1);
        if (i + 1 < width) reach(c + 1);
        if (j > 0) reach(c - width);
        if (j + 1 < static_cast<std::size_t>(nz)) reach(c + width);
    }
    // The columns in the order they join. Each level some join at is a break
    // point: the volume steps by what those columns hold at that level (nothing,
    // for a column joining at its own bed; the ground beyond a saddle, filling at
    // the saddle's level, for the rest), and rises faster by their area from there.
    std::vector<std::size_t> order(n);
    std::iota(order.begin(), order.end(), std::size_t{0});
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return joins[a] < joins[b] || (joins[a] == joins[b] && a < b);
    });
    StageStorage s;
    double count = 0.0, bed_sum = 0.0;   // columns in the lake so far, and their beds summed
    for (std::size_t k = 0; k < n;) {
        const double level = joins[order[k]];
        const double below = cell_area_m2 * (count * level - bed_sum);
        for (; k < n && joins[order[k]] == level; ++k) {
            count += 1.0;
            bed_sum += bed[order[k]];
        }
        s.level_.push_back(level);
        s.below_.push_back(s.level_.size() == 1 ? 0.0 : below);
        s.above_.push_back(cell_area_m2 * (count * level - bed_sum));
        s.slope_.push_back(cell_area_m2 * count);
    }
    return s;
}

double StageStorage::volume(double level_m) const {
    if (level_.empty() || !(level_m > level_.front())) return 0.0;
    const auto k = static_cast<std::size_t>(std::upper_bound(level_.begin(), level_.end(), level_m) -
                                            level_.begin()) - 1;
    return above_[k] + slope_[k] * (level_m - level_[k]);
}

double StageStorage::level(double volume_m3) const {
    if (level_.empty()) return 0.0;
    if (!(volume_m3 > 0.0)) return level_.front();
    auto k = static_cast<std::size_t>(std::upper_bound(below_.begin(), below_.end(), volume_m3) - below_.begin());
    k = k == 0 ? 0 : k - 1;
    // Filling the ground beyond a saddle: the level waits at the saddle.
    if (volume_m3 <= above_[k]) return level_[k];
    return level_[k] + (volume_m3 - above_[k]) / slope_[k];
}

double StageStorage::area(double level_m) const {
    if (level_.empty()) return 0.0;
    if (!(level_m > level_.front())) return slope_.front();
    const auto k = static_cast<std::size_t>(std::upper_bound(level_.begin(), level_.end(), level_m) -
                                            level_.begin()) - 1;
    return slope_[k];
}

// ---- the network -------------------------------------------------------------

RiverNetwork::RiverNetwork(NetworkSettings settings) : settings_(settings) {
    if (!(settings_.gravity_m_s2 > 0.0) || !(settings_.manning_n >= 0.0) || !(settings_.cfl > 0.0) ||
        !(settings_.cfl <= 1.0) || !(settings_.theta > 0.0) || !(settings_.theta <= 1.0) ||
        !(settings_.dry_m > 0.0) || !(settings_.froude_limit > 0.0) || !(settings_.max_step_s > 0.0))
        throw std::invalid_argument("a river network's settings are out of range");
}

int RiverNetwork::nodeNamed(const std::string &name) const {
    for (std::size_t k = 0; k < nodes_.size(); ++k)
        if (nodes_[k].name == name) return static_cast<int>(k);
    return kOpen;
}

int RiverNetwork::reachNamed(const std::string &name) const {
    for (std::size_t k = 0; k < reaches_.size(); ++k)
        if (reaches_[k].name == name) return static_cast<int>(k);
    return kOpen;
}

int RiverNetwork::addNode(Node node, double level_m) {
    if (node.name.empty()) throw std::invalid_argument("a basin or a junction needs a name");
    if (nodeNamed(node.name) != kOpen || reachNamed(node.name) != kOpen)
        throw std::invalid_argument("two parts of the river network are called " + quoted(node.name));
    if (node.storage.empty()) throw std::invalid_argument(quoted(node.name) + " has no stage-storage");
    if (!std::isfinite(level_m)) throw std::invalid_argument(quoted(node.name) + " needs a level");
    if (!(node.fed_m3_s >= 0.0) || !std::isfinite(node.fed_m3_s))
        throw std::invalid_argument(quoted(node.name) + " is fed a discharge that is not a number of m^3/s");
    if (node.has_outlet && (!std::isfinite(node.crest_m) || !(node.outlet_width_m > 0.0)))
        throw std::invalid_argument(quoted(node.name) + "'s outlet needs a crest and a width");
    level_m = std::max(level_m, node.storage.bottom());
    node.volume_m3 = node.storage.volume(level_m);
    node.level_m = level_m;
    node.initial_m3 = node.volume_m3;
    node.fed_m3 = node.out_m3 = node.across_m3 = node.from_reaches_m3 = node.numerical_m3 = 0.0;
    node.out_rate_m3_s = node.across_rate_m3_s = node.from_reaches_rate_m3_s = 0.0;
    nodes_.push_back(std::move(node));
    node_dv_.push_back(0.0);
    node_out_.push_back(0.0);
    node_share_.push_back(1.0);
    node_width_.push_back(0.0);
    return static_cast<int>(nodes_.size()) - 1;
}

int RiverNetwork::addReach(Reach reach, double depth_m, double discharge_m3_s) {
    if (reach.name.empty()) throw std::invalid_argument("a reach needs a name");
    if (nodeNamed(reach.name) != kOpen || reachNamed(reach.name) != kOpen)
        throw std::invalid_argument("two parts of the river network are called " + quoted(reach.name));
    const int count = static_cast<int>(nodes_.size());
    const auto known = [&](int end) { return end == kOpen || (end >= 0 && end < count); };
    if (!known(reach.from) || !known(reach.to))
        throw std::invalid_argument(quoted(reach.name) + " runs from or to a basin or junction that is not there");
    if (reach.from == kOpen && reach.to == kOpen)
        throw std::invalid_argument(quoted(reach.name) + " has to start or end at a basin or a junction");
    if (reach.from == reach.to) throw std::invalid_argument(quoted(reach.name) + " starts and ends at one place");
    if (!(reach.length_m > 0.0) || !std::isfinite(reach.length_m) || !(reach.width_m > 0.0) ||
        !std::isfinite(reach.width_m) || reach.cells < 1 || reach.cells > 100000 || !(reach.manning_n >= 0.0) ||
        !std::isfinite(reach.manning_n) || !std::isfinite(reach.bed_from_m) || !std::isfinite(reach.bed_to_m))
        throw std::invalid_argument(quoted(reach.name) + " needs a length, a width, cells and beds");
    if (!(depth_m >= 0.0) || !std::isfinite(depth_m) || !std::isfinite(discharge_m3_s))
        throw std::invalid_argument(quoted(reach.name) + " starts with a depth or a discharge that is not a number");
    reach.dx_m = reach.length_m / reach.cells;
    reach.bed_m.resize(static_cast<std::size_t>(reach.cells));
    reach.level_m.resize(static_cast<std::size_t>(reach.cells));
    for (int i = 0; i < reach.cells; ++i) {
        const std::size_t c = static_cast<std::size_t>(i);
        reach.bed_m[c] = reach.bed_from_m + (reach.bed_to_m - reach.bed_from_m) * (i + 0.5) / reach.cells;
        reach.level_m[c] = reach.bed_m[c] + depth_m;
    }
    reach.q_m3_s.assign(static_cast<std::size_t>(reach.cells) + 1, discharge_m3_s);
    reach.initial_m3 = reach.across_m3 = reach.numerical_m3 = 0.0;
    reach.froude_now = 0.0;
    reach.froude_held = 0;
    if (reach.from != kOpen) node_width_[static_cast<std::size_t>(reach.from)] += reach.width_m;
    if (reach.to != kOpen) node_width_[static_cast<std::size_t>(reach.to)] += reach.width_m;
    const std::size_t cells = static_cast<std::size_t>(reach.cells);
    reaches_.push_back(std::move(reach));
    reaches_.back().initial_m3 = reachVolume(reaches_.size() - 1);
    cell_dv_.emplace_back(cells, 0.0);
    cell_out_.emplace_back(cells, 0.0);
    cell_share_.emplace_back(cells, 1.0);
    return static_cast<int>(reaches_.size()) - 1;
}

void RiverNetwork::standReach(std::size_t reach, double level_m) {
    Reach &r = reaches_.at(reach);
    if (!std::isfinite(level_m)) throw std::invalid_argument(quoted(r.name) + " needs a level");
    for (std::size_t c = 0; c < r.level_m.size(); ++c) r.level_m[c] = std::max(level_m, r.bed_m[c]);
    std::fill(r.q_m3_s.begin(), r.q_m3_s.end(), 0.0);
}

void RiverNetwork::resetLedger() {
    for (Node &n : nodes_) {
        n.initial_m3 = n.volume_m3;
        n.fed_m3 = n.out_m3 = n.across_m3 = n.from_reaches_m3 = n.numerical_m3 = 0.0;
    }
    for (std::size_t k = 0; k < reaches_.size(); ++k) {
        reaches_[k].initial_m3 = reachVolume(k);
        reaches_[k].across_m3 = reaches_[k].numerical_m3 = 0.0;
    }
}

bool RiverNetwork::setFeed(const std::string &name, double discharge_m3_s) {
    if (!(discharge_m3_s >= 0.0) || !std::isfinite(discharge_m3_s)) return false;
    const int k = nodeNamed(name);
    if (k == kOpen) return false;
    nodes_[static_cast<std::size_t>(k)].fed_m3_s = discharge_m3_s;
    return true;
}

double RiverNetwork::endBed(const Reach &reach, bool at_to) const {
    const int node = at_to ? reach.to : reach.from;
    const double own = at_to ? reach.bed_to_m : reach.bed_from_m;
    return node == kOpen ? own : std::max(own, nodes_[static_cast<std::size_t>(node)].storage.bottom());
}

// ---- the detailed region's side ------------------------------------------------

double RiverNetwork::levelAt(const Endpoint &end) const {
    if (end.node != kOpen) return nodes_.at(static_cast<std::size_t>(end.node)).level_m;
    const Reach &r = reaches_.at(static_cast<std::size_t>(end.reach));
    return r.level_m[end.at_to ? r.level_m.size() - 1 : 0];
}

double RiverNetwork::speedOut(const Endpoint &end) const {
    if (end.node != kOpen) return 0.0;   // a basin's water stands still at its edge
    const Reach &r = reaches_.at(static_cast<std::size_t>(end.reach));
    const std::size_t cell = end.at_to ? r.level_m.size() - 1 : 0;
    const double h = r.level_m[cell] - r.bed_m[cell];
    if (!(h > settings_.dry_m)) return 0.0;
    // The discharge reaching the end cell from inside the reach: through its
    // other face.
    const double q = r.q_m3_s[end.at_to ? r.q_m3_s.size() - 2 : 1];
    const double u = q / (r.width_m * h);   // positive from `from` towards `to`
    return end.at_to ? u : -u;
}

void RiverNetwork::startExchange() {
    for (Node &n : nodes_) n.across_rate_m3_s = 0.0;
}

void RiverNetwork::exchange(const Endpoint &end, double into_m3, double dt_s) {
    if (!std::isfinite(into_m3)) throw std::invalid_argument("what crossed into the river network is not a number");
    const double rate = dt_s > 0.0 ? into_m3 / dt_s : 0.0;
    if (end.node != kOpen) {
        Node &n = nodes_.at(static_cast<std::size_t>(end.node));
        n.across_m3 += into_m3;
        n.across_rate_m3_s += rate;
        if (into_m3 == 0.0) return;
        n.volume_m3 += into_m3;
        if (n.volume_m3 < 0.0) {
            n.numerical_m3 -= n.volume_m3;
            n.volume_m3 = 0.0;
        }
        n.level_m = n.storage.level(n.volume_m3);
        return;
    }
    Reach &r = reaches_.at(static_cast<std::size_t>(end.reach));
    r.across_m3 += into_m3;
    // The open face's discharge, from `from` towards `to`, for the report: in
    // across a `from` end, out across a `to` end.
    r.q_m3_s[end.at_to ? r.q_m3_s.size() - 1 : 0] = end.at_to ? -rate : rate;
    if (into_m3 == 0.0) return;
    const std::size_t cell = end.at_to ? r.level_m.size() - 1 : 0;
    const double area = r.width_m * r.dx_m;
    r.level_m[cell] += into_m3 / area;
    if (r.level_m[cell] < r.bed_m[cell]) {
        r.numerical_m3 += (r.bed_m[cell] - r.level_m[cell]) * area;
        r.level_m[cell] = r.bed_m[cell];
    }
}

// ---- time --------------------------------------------------------------------

double RiverNetwork::stableStep() const {
    const double g = settings_.gravity_m_s2, dry = settings_.dry_m;
    double step = settings_.max_step_s;
    for (const Reach &r : reaches_) {
        for (std::size_t c = 0; c < r.level_m.size(); ++c) {
            const double h = r.level_m[c] - r.bed_m[c];
            if (!(h > dry)) continue;
            const double u = std::max(std::abs(r.q_m3_s[c]), std::abs(r.q_m3_s[c + 1])) / (r.width_m * h);
            step = std::min(step, settings_.cfl * r.dx_m / (u + std::sqrt(g * h)));
        }
        for (const bool at_to : {false, true}) {
            const int node = at_to ? r.to : r.from;
            if (node == kOpen) continue;
            const Node &n = nodes_[static_cast<std::size_t>(node)];
            const double h = n.level_m - endBed(r, at_to);
            if (!(h > dry)) continue;
            const double wave = std::sqrt(g * h);
            // A node small enough to fill or empty in a step is as short as its
            // surface is over the widths it opens into.
            const double length = n.storage.area(n.level_m) / node_width_[static_cast<std::size_t>(node)];
            step = std::min(step, settings_.cfl * std::min(r.dx_m, length) / wave);
        }
    }
    return step;
}

int RiverNetwork::advance(double dt_s) {
    if (!(dt_s > 0.0) || !std::isfinite(dt_s)) return 0;
    double left = dt_s;
    int steps = 0;
    while (left > 0.0) {
        const double limit = stableStep();
        double dt = std::min(left, limit);
        // No sliver of a step left over at the end.
        if (left - dt < 1.0e-9 * dt_s) dt = left;
        substep(dt, limit);
        left -= dt;
        ++steps;
    }
    stats_.time_s += dt_s;
    stats_.substeps += static_cast<std::uint64_t>(steps);
    return steps;
}

void RiverNetwork::substep(double dt, double limit) {
    const double g = settings_.gravity_m_s2, dry = settings_.dry_m;
    const auto open = [](const Reach &r, std::size_t f) {
        return (f == 0 && r.from == kOpen) || (f + 1 == r.q_m3_s.size() && r.to == kOpen);
    };
    // 1. The discharge through every face the network computes: from its own
    //    discharge blended with its neighbours', the fall of the surface across
    //    it against the bed's friction, the friction taken with the discharge it
    //    had (semi-implicit), held to the Froude limit.
    //
    //    The blend is a rate, not a share a substep: de Almeida et al.'s theta
    //    is for a substep at the stability limit, and a shorter one blends in
    //    that much less, so the water is damped the same whether it is stepped
    //    at the limit or, coupled to the detailed water, a sixtieth of a second
    //    at a time -- where the same share every substep would damp it a
    //    hundred times harder and hold a flood front back.
    const double theta = 1.0 - (1.0 - settings_.theta) * std::min(1.0, dt / limit);
    if (q_old_.size() != reaches_.size()) q_old_.resize(reaches_.size());
    for (std::size_t k = 0; k < reaches_.size(); ++k) {
        Reach &r = reaches_[k];
        const double n = r.manning_n > 0.0 ? r.manning_n : settings_.manning_n;
        const double friction = g * dt * n * n;
        const std::size_t cells = r.level_m.size();
        // Every face starts from the discharges as they were, not as the faces
        // before it in this loop have just made them.
        std::vector<double> &old = q_old_[k];
        old = r.q_m3_s;
        r.froude_now = 0.0;
        for (std::size_t f = 0; f <= cells; ++f) {
            if (open(r, f)) continue;
            const bool at_from = f == 0, at_to = f == cells;
            const double eta_l = at_from ? nodes_[static_cast<std::size_t>(r.from)].level_m : r.level_m[f - 1];
            const double bed_l = at_from ? endBed(r, false) : r.bed_m[f - 1];
            const double eta_r = at_to ? nodes_[static_cast<std::size_t>(r.to)].level_m : r.level_m[f];
            const double bed_r = at_to ? endBed(r, true) : r.bed_m[f];
            double &flow = r.q_m3_s[f];
            ++stats_.faces_computed;
            const double h = std::max(eta_l, eta_r) - std::max(bed_l, bed_r);
            if (!(h > dry)) {
                flow = 0.0;
                continue;
            }
            // Its own discharge, blended with its neighbours' as they are -- a
            // dry face's nothing too, as a wall's (standing in the face's own
            // for a dry neighbour pumped a seiche in a reach running up onto
            // dry ground) -- and past a reach's end, where there is no
            // neighbour, its own.
            const double left = at_from ? old[f] : old[f - 1];
            const double right = at_to ? old[f] : old[f + 1];
            const double q = old[f] / r.width_m;
            const double start = (theta * old[f] + 0.5 * (1.0 - theta) * (left + right)) / r.width_m;
            double next = (start - g * h * dt * (eta_r - eta_l) / r.dx_m) /
                          (1.0 + friction * std::abs(q) / std::pow(h, 7.0 / 3.0));
            // Held to the limit. At an end, where the water falls freely into a
            // node standing below it, that is the brink: the critical discharge
            // for its depth, as the detailed water's mouths pass -- the boundary,
            // not the reach outside its regime, so only the faces inside a reach
            // are counted and said.
            const double critical = settings_.froude_limit * h * std::sqrt(g * h);
            const bool inside = !at_from && !at_to;
            if (std::abs(next) > critical) {
                next = std::copysign(critical, next);
                if (inside) ++r.froude_held;
            }
            if (inside) r.froude_now = std::max(r.froude_now, std::abs(next) / (h * std::sqrt(g * h)));
            flow = next * r.width_m;
        }
    }
    // 2. What each cell and node can give. One asked for more than it holds
    //    gives what it holds, shared over the faces it is losing water through:
    //    each face's discharge scaled by the share of the one side it leaves, so
    //    both sides see the same flux and nothing is made or lost.
    std::fill(node_out_.begin(), node_out_.end(), 0.0);
    for (std::vector<double> &out : cell_out_) std::fill(out.begin(), out.end(), 0.0);
    for (std::size_t k = 0; k < reaches_.size(); ++k) {
        const Reach &r = reaches_[k];
        const std::size_t cells = r.level_m.size();
        for (std::size_t f = 0; f <= cells; ++f) {
            if (open(r, f)) continue;
            const double flow = r.q_m3_s[f];
            if (flow > 0.0) {
                (f == 0 ? node_out_[static_cast<std::size_t>(r.from)] : cell_out_[k][f - 1]) += flow * dt;
            } else if (flow < 0.0) {
                (f == cells ? node_out_[static_cast<std::size_t>(r.to)] : cell_out_[k][f]) -= flow * dt;
            }
        }
    }
    const auto share = [&](double out, double held) {
        if (!(out > held)) return 1.0;
        ++stats_.shared_out;
        return held > 0.0 ? held / out : 0.0;
    };
    for (std::size_t n = 0; n < nodes_.size(); ++n) node_share_[n] = share(node_out_[n], nodes_[n].volume_m3);
    for (std::size_t k = 0; k < reaches_.size(); ++k) {
        const Reach &r = reaches_[k];
        const double area = r.width_m * r.dx_m;
        for (std::size_t c = 0; c < r.level_m.size(); ++c)
            cell_share_[k][c] = cell_out_[k][c] > 0.0 ? share(cell_out_[k][c], (r.level_m[c] - r.bed_m[c]) * area)
                                                      : 1.0;
    }
    std::fill(node_dv_.begin(), node_dv_.end(), 0.0);
    for (std::vector<double> &dv : cell_dv_) std::fill(dv.begin(), dv.end(), 0.0);
    for (std::size_t k = 0; k < reaches_.size(); ++k) {
        Reach &r = reaches_[k];
        const std::size_t cells = r.level_m.size();
        for (std::size_t f = 0; f <= cells; ++f) {
            if (open(r, f)) continue;
            double &flow = r.q_m3_s[f];
            if (flow > 0.0) flow *= f == 0 ? node_share_[static_cast<std::size_t>(r.from)] : cell_share_[k][f - 1];
            else if (flow < 0.0) flow *= f == cells ? node_share_[static_cast<std::size_t>(r.to)] : cell_share_[k][f];
            if (flow == 0.0) continue;
            const double moved = flow * dt;   // from the `from` side to the `to` side
            (f == 0 ? node_dv_[static_cast<std::size_t>(r.from)] : cell_dv_[k][f - 1]) -= moved;
            (f == cells ? node_dv_[static_cast<std::size_t>(r.to)] : cell_dv_[k][f]) += moved;
        }
    }
    // 3. The levels: each cell's, then each node's with what it is fed from beyond
    //    the world and what its outlet lets go -- never more than stands above
    //    its crest. A level is worked out again only where water moved.
    for (std::size_t k = 0; k < reaches_.size(); ++k) {
        Reach &r = reaches_[k];
        const double area = r.width_m * r.dx_m;
        for (std::size_t c = 0; c < r.level_m.size(); ++c) {
            const double dv = cell_dv_[k][c];
            if (dv == 0.0) continue;
            r.level_m[c] += dv / area;
            if (r.level_m[c] < r.bed_m[c]) {
                r.numerical_m3 += (r.bed_m[c] - r.level_m[c]) * area;
                r.level_m[c] = r.bed_m[c];
            }
        }
    }
    for (std::size_t k = 0; k < nodes_.size(); ++k) {
        Node &n = nodes_[k];
        double v = n.volume_m3 + node_dv_[k];
        n.from_reaches_m3 += node_dv_[k];
        n.from_reaches_rate_m3_s = node_dv_[k] / dt;
        if (n.fed_m3_s > 0.0) {
            v += n.fed_m3_s * dt;
            n.fed_m3 += n.fed_m3_s * dt;
        }
        n.out_rate_m3_s = 0.0;
        if (n.has_outlet) {
            const double head = n.storage.level(v) - n.crest_m;
            if (head > 0.0) {
                const double rate = kWeir * std::sqrt(g) * head * std::sqrt(head) * n.outlet_width_m;
                const double out = std::min(rate * dt, std::max(0.0, v - n.storage.volume(n.crest_m)));
                v -= out;
                n.out_m3 += out;
                n.out_rate_m3_s = out / dt;
            }
        }
        if (v < 0.0) {
            n.numerical_m3 -= v;
            v = 0.0;
        }
        if (v != n.volume_m3) {
            n.volume_m3 = v;
            n.level_m = n.storage.level(v);
        }
    }
    stats_.last_substep_s = dt;
}

// ---- accounts and state ------------------------------------------------------

double RiverNetwork::reachVolume(std::size_t reach) const {
    const Reach &r = reaches_.at(reach);
    const double area = r.width_m * r.dx_m;
    double v = 0.0;
    for (std::size_t c = 0; c < r.level_m.size(); ++c) v += (r.level_m[c] - r.bed_m[c]) * area;
    return v;
}

double RiverNetwork::volume() const {
    double v = 0.0;
    for (const Node &n : nodes_) v += n.volume_m3;
    for (std::size_t k = 0; k < reaches_.size(); ++k) v += reachVolume(k);
    return v;
}

RiverNetwork::Totals RiverNetwork::totals() const {
    Totals t;
    for (const Node &n : nodes_) {
        t.initial_m3 += n.initial_m3;
        t.fed_m3 += n.fed_m3;
        t.out_m3 += n.out_m3;
        t.across_m3 += n.across_m3;
        t.numerical_m3 += n.numerical_m3;
    }
    for (const Reach &r : reaches_) {
        t.initial_m3 += r.initial_m3;
        t.across_m3 += r.across_m3;
        t.numerical_m3 += r.numerical_m3;
    }
    return t;
}

double RiverNetwork::residual() const {
    const Totals t = totals();
    return volume() - (t.initial_m3 + t.fed_m3 - t.out_m3 + t.across_m3 + t.numerical_m3);
}

RiverNetwork::NodeState RiverNetwork::nodeState(std::size_t node) const {
    const Node &n = nodes_.at(node);
    return {n.volume_m3, n.level_m, n.initial_m3, n.fed_m3, n.out_m3, n.across_m3, n.from_reaches_m3,
            n.numerical_m3};
}

RiverNetwork::ReachState RiverNetwork::reachState(std::size_t reach) const {
    const Reach &r = reaches_.at(reach);
    return {r.level_m, r.q_m3_s, r.initial_m3, r.across_m3, r.numerical_m3, r.froude_held};
}

void RiverNetwork::restoreNode(std::size_t node, const NodeState &s) {
    Node &n = nodes_.at(node);
    if (!std::isfinite(s.volume_m3) || s.volume_m3 < 0.0) throw std::invalid_argument("a saved volume is not a volume");
    n.volume_m3 = s.volume_m3;
    // The level it was left at, to the bit -- unless it was saved over another
    // shape of basin, when it is the level this basin holds that volume at.
    const double held_at = n.storage.level(s.volume_m3);
    n.level_m = std::isfinite(s.level_m) && std::abs(s.level_m - held_at) <= 1.0e-9 ? s.level_m : held_at;
    n.initial_m3 = s.initial_m3;
    n.fed_m3 = s.fed_m3;
    n.out_m3 = s.out_m3;
    n.across_m3 = s.across_m3;
    n.from_reaches_m3 = s.from_reaches_m3;
    n.numerical_m3 = s.numerical_m3;
}

bool RiverNetwork::restoreReach(std::size_t reach, const ReachState &s) {
    Reach &r = reaches_.at(reach);
    if (s.level_m.size() != r.level_m.size() || s.q_m3_s.size() != r.q_m3_s.size()) return false;
    for (std::size_t c = 0; c < r.level_m.size(); ++c) {
        if (!std::isfinite(s.level_m[c])) return false;
        // Over a bed declared higher since, the water it no longer has room for is gone.
        r.level_m[c] = std::max(s.level_m[c], r.bed_m[c]);
    }
    for (std::size_t f = 0; f < r.q_m3_s.size(); ++f) r.q_m3_s[f] = std::isfinite(s.q_m3_s[f]) ? s.q_m3_s[f] : 0.0;
    r.initial_m3 = s.initial_m3;
    r.across_m3 = s.across_m3;
    r.numerical_m3 = s.numerical_m3;
    r.froude_held = s.froude_held;
    return true;
}

} // namespace banjo::water
