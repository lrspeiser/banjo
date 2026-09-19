#include "machines/Circuit.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <set>
#include <stdexcept>

namespace banjo::machines {
namespace {
void require(bool condition, const std::string &why) {
    if (!condition) throw std::invalid_argument("circuit: " + why);
}
double number(const nlohmann::json &d, const char *key, double fallback = 0.0) {
    const double v = d.value(key, fallback);
    require(std::isfinite(v), std::string(key) + " must be finite");
    return v;
}
std::vector<double> linear(std::vector<std::vector<double>> a, std::vector<double> b) {
    const auto n = b.size();
    for (std::size_t k = 0; k < n; ++k) {
        std::size_t pivot = k;
        for (std::size_t i = k + 1; i < n; ++i)
            if (std::abs(a[i][k]) > std::abs(a[pivot][k])) pivot = i;
        require(std::isfinite(a[pivot][k]) && std::abs(a[pivot][k]) > 1e-18,
                "singular or ill-conditioned network");
        std::swap(a[k], a[pivot]); std::swap(b[k], b[pivot]);
        for (std::size_t i = k + 1; i < n; ++i) {
            const double f = a[i][k] / a[k][k];
            for (std::size_t j = k + 1; j < n; ++j) a[i][j] -= f * a[k][j];
            b[i] -= f * b[k];
        }
    }
    for (std::size_t ii = n; ii-- > 0;) {
        for (std::size_t j = ii + 1; j < n; ++j) b[ii] -= a[ii][j] * b[j];
        b[ii] /= a[ii][ii];
        require(std::isfinite(b[ii]), "non-finite network solution");
    }
    return b;
}
std::size_t index(const std::vector<std::string> &ids, const std::string &id) {
    const auto it = std::find(ids.begin(), ids.end(), id);
    require(it != ids.end(), "unknown connection " + id);
    return static_cast<std::size_t>(it - ids.begin());
}
void unique(std::set<std::string> &ids, const std::string &id) {
    require(!id.empty() && ids.insert(id).second, "ids must be nonempty and unique: " + id);
}
void keys(const nlohmann::json &doc, std::initializer_list<const char *> supported) {
    require(doc.is_object(), "declaration must be an object");
    for (auto it = doc.begin(); it != doc.end(); ++it)
        require(std::any_of(supported.begin(), supported.end(), [&](const char *key) { return it.key() == key; }),
                "unsupported field " + it.key());
}
}

Circuit Circuit::read(const nlohmann::json &doc, bool restore) {
    keys(doc, {"schema", "id", "nodes", "source", "ambient_k", "thermal_nodes", "thermal_links", "branches", "ledger", "last"});
    require(doc.at("schema") == "banjo.circuit.v1", "unsupported schema");
    Circuit c;
    c.id_ = doc.at("id").get<std::string>();
    require(!c.id_.empty(), "id is required");
    c.nodes_ = doc.at("nodes").get<std::vector<std::string>>();
    require(!c.nodes_.empty() && c.nodes_.size() <= 128, "needs 1..128 electrical nodes");
    std::set<std::string> ids;
    for (const auto &id : c.nodes_) unique(ids, id);
    c.ambient_k_ = number(doc, "ambient_k", 293.15);
    require(c.ambient_k_ > 0.0, "ambient temperature must be positive");
    std::vector<std::string> heat_ids;
    ids.clear();
    require(doc.at("thermal_nodes").is_array() && !doc.at("thermal_nodes").empty() &&
            doc.at("thermal_nodes").size() <= 128, "needs 1..128 thermal nodes");
    for (const auto &h : doc.at("thermal_nodes")) {
        keys(h, {"id", "component", "capacity_j_k", "temperature_k", "ambient_w_k"});
        Heat row{h.at("id"), h.at("component"), number(h, "capacity_j_k"),
                 number(h, "temperature_k", c.ambient_k_), number(h, "ambient_w_k")};
        unique(ids, row.id);
        require(!row.component.empty() && row.capacity > 0.0 && row.temperature > 0.0 &&
                row.ambient_conductance >= 0.0, "invalid thermal node");
        heat_ids.push_back(row.id); c.heat_.push_back(row);
    }
    const auto &source = doc.at("source");
    keys(source, {"store", "positive", "negative", "resistance_ohm", "thermal"});
    require(source.at("store").is_number_unsigned() || source.at("store").is_number_integer(), "invalid store id");
    require(source.at("store").get<std::int64_t>() > 0 &&
            source.at("store").get<std::int64_t>() <= std::numeric_limits<unsigned>::max(), "invalid store id");
    c.store_ = source.at("store").get<unsigned>();
    c.positive_ = index(c.nodes_, source.at("positive"));
    c.negative_ = index(c.nodes_, source.at("negative"));
    require(c.positive_ != c.negative_, "source terminals must differ");
    c.source_heat_ = index(heat_ids, source.at("thermal"));
    c.source_resistance_ = number(source, "resistance_ohm");
    require(c.source_resistance_ >= 1e-9 && c.source_resistance_ <= 1e12, "source resistance outside supported range");
    ids.clear();
    std::set<unsigned> motor_ids;
    require(doc.at("branches").is_array() && doc.at("branches").size() <= 256, "at most 256 branches");
    for (const auto &b : doc.at("branches")) {
        keys(b, {"id", "kind", "component", "a", "b", "thermal", "resistance_ohm", "alpha_per_k", "reference_k", "trip_k",
                 "fuse_a2_s", "gear_ratio", "motor", "closed", "failed", "used_a2_s", "current_a", "motor_current_a",
                 "torque_n_m", "housing_reaction_n_m"});
        Branch row;
        row.id = b.at("id"); row.kind = b.at("kind"); row.component = b.at("component");
        unique(ids, row.id);
        require(!row.component.empty(), "branch needs source component identity");
        require(row.kind == "resistor" || row.kind == "wire" || row.kind == "switch" ||
                row.kind == "fuse" || row.kind == "motor", "unsupported branch " + row.kind);
        row.a = index(c.nodes_, b.at("a")); row.b = index(c.nodes_, b.at("b"));
        require(row.a != row.b, "branch terminals must differ");
        row.thermal = index(heat_ids, b.at("thermal"));
        row.resistance = number(b, "resistance_ohm");
        row.alpha = number(b, "alpha_per_k"); row.reference_k = number(b, "reference_k", 293.15);
        row.trip_k = number(b, "trip_k"); row.fuse_limit = number(b, "fuse_a2_s");
        row.ratio = number(b, "gear_ratio", 1.0);
        require(row.alpha >= 0.0 && row.reference_k > 0.0 && row.trip_k >= 0.0 && row.fuse_limit >= 0.0 &&
                row.ratio > 0.0 && row.ratio <= 1e6, "invalid branch law");
        require(row.kind != "fuse" || row.fuse_limit > 0.0, "fuse needs a positive I-squared-time rating");
        if (row.kind == "motor") {
            require(row.resistance == 0.0, "motor resistance is derived from its declared torque-speed line");
            require(b.at("motor").is_number_integer(), "motor id must be an integer");
            const auto id = b.at("motor").get<std::int64_t>();
            require(id > 0 && id <= std::numeric_limits<unsigned>::max(), "invalid motor id");
            row.motor = static_cast<unsigned>(id);
            require(motor_ids.insert(row.motor).second, "motor appears twice");
        } else {
            require(!b.contains("motor") && row.ratio == 1.0, "only a motor branch has a motor or gearbox");
            require(row.resistance >= 1e-9 && row.resistance <= 1e12, "resistance outside supported range");
        }
        row.closed = b.value("closed", true);
        if (restore) {
            row.failed = b.value("failed", false); row.fuse_used = number(b, "used_a2_s");
            require(row.fuse_used >= 0.0, "negative fuse history");
        }
        c.branches_.push_back(row);
    }
    const auto links = doc.value("thermal_links", nlohmann::json::array());
    require(links.is_array() && links.size() <= 256, "at most 256 thermal links");
    for (const auto &l : links) {
        keys(l, {"a", "b", "conductance_w_k"});
        HeatLink row{index(heat_ids, l.at("a")), index(heat_ids, l.at("b")), number(l, "conductance_w_k")};
        require(row.a != row.b && row.conductance >= 0.0, "invalid thermal link");
        c.heat_links_.push_back(row);
    }
    if (restore) {
        const auto ledger = doc.at("ledger");
        c.elapsed_s_ = number(ledger, "elapsed_s"); c.source_j_ = number(ledger, "source_j");
        c.heat_j_ = number(ledger, "heat_j"); c.shaft_j_ = number(ledger, "shaft_j");
        c.ambient_j_ = number(ledger, "ambient_j");
        c.electrical_residual_j_ = number(ledger, "electrical_residual_j");
        c.thermal_residual_j_ = number(ledger, "thermal_residual_j");
        c.coupling_residual_j_ = number(ledger, "coupling_residual_j");
        require(c.elapsed_s_ >= 0.0 && c.source_j_ >= 0.0 && c.heat_j_ >= 0.0, "invalid ledger history");
        const auto last = doc.value("last", nlohmann::json::object());
        c.last_.voltage_v = last.value("voltage_v", std::vector<double>{});
        require(c.last_.voltage_v.empty() || c.last_.voltage_v.size() == c.nodes_.size(), "invalid voltage snapshot");
        for (double v : c.last_.voltage_v) require(std::isfinite(v), "invalid voltage snapshot");
        c.last_.source_current_a = number(last, "source_current_a");
        c.last_.max_kcl_a = number(last, "max_kcl_a");
        c.last_.limited = last.value("power_limited", false);
        if (!c.last_.voltage_v.empty()) {
            for (const auto &b : doc.at("branches")) {
                c.last_.current_a.push_back(number(b, "current_a"));
                c.last_.motor_current_a.push_back(number(b, "motor_current_a"));
                c.last_.torque_n_m.push_back(number(b, "torque_n_m"));
            }
        }
    }
    return c;
}

CircuitStep Circuit::solve(double dt, double voltage, double charge, double max_power,
                           const std::vector<CircuitMotorInput> &motors_in) const {
    require(std::isfinite(dt) && dt > 0.0 && std::isfinite(voltage) && voltage > 0.0 &&
            std::isfinite(charge) && charge >= 0.0 && std::isfinite(max_power) && max_power >= 0.0,
            "invalid step or supply state");
    CircuitStep s; s.dt_s = dt;
    const auto n = nodes_.size(), count = branches_.size();
    std::vector<double> g(count), emf(count), gain(count), command(count);
    for (std::size_t i = 0; i < count; ++i) {
        const auto &b = branches_[i];
        if (!b.closed || b.failed || (b.trip_k > 0.0 && heat_[b.thermal].temperature >= b.trip_k) ||
            (b.fuse_limit > 0.0 && b.fuse_used >= b.fuse_limit)) continue;
        const double factor = 1.0 + b.alpha * (heat_[b.thermal].temperature - b.reference_k);
        require(factor > 0.0 && std::isfinite(factor), "resistance law outside positive domain");
        if (!b.motor) { g[i] = 1.0 / (b.resistance * factor); continue; }
        const auto m = std::find_if(motors_in.begin(), motors_in.end(), [&](const auto &v) { return v.id == b.motor; });
        require(m != motors_in.end(), "missing motor input");
        require(std::isfinite(m->command) && std::abs(m->command) <= 1.0 && std::isfinite(m->speed_rad_s) &&
                std::isfinite(m->torque_constant) && m->torque_constant > 0.0 &&
                std::isfinite(m->resistance_ohm) && m->resistance_ohm >= 1e-9, "invalid motor parameters");
        if (!m->present || m->command == 0.0) continue;
        command[i] = m->command;
        const double k = m->torque_constant * b.ratio;
        g[i] = m->command * m->command / (m->resistance_ohm * factor);
        emf[i] = k * m->speed_rad_s / m->command;
        gain[i] = k / m->command;
    }
    // One gauge per conducting island; disconnected wiring never needs a fake
    // leakage resistor to ground. The supply is CV with internal resistance,
    // changing to CC when its finite chemical-energy/power budget is reached.
    const auto solveAt = [&](bool limited, double source_current) {
        std::vector<std::vector<double>> a(n, std::vector<double>(n));
        std::vector<double> rhs(n);
        std::vector<std::size_t> parent(n); std::iota(parent.begin(), parent.end(), 0);
        const auto root = [&](std::size_t p) { while (parent[p] != p) p = parent[p]; return p; };
        const auto stamp = [&](std::size_t p, std::size_t q, double conductance, double e) {
            if (conductance == 0.0) return;
            parent[root(q)] = root(p);
            a[p][p] += conductance; a[q][q] += conductance;
            a[p][q] -= conductance; a[q][p] -= conductance;
            rhs[p] += conductance * e; rhs[q] -= conductance * e;
        };
        for (std::size_t i = 0; i < count; ++i) stamp(branches_[i].a, branches_[i].b, g[i], emf[i]);
        if (limited) { rhs[positive_] += source_current; rhs[negative_] -= source_current; }
        else stamp(positive_, negative_, 1.0 / source_resistance_, voltage);
        for (std::size_t i = 0; i < n; ++i) if (root(i) == i) {
            std::fill(a[i].begin(), a[i].end(), 0.0); a[i][i] = 1.0; rhs[i] = 0.0;
        }
        return linear(std::move(a), std::move(rhs));
    };
    s.voltage_v = solveAt(false, 0.0);
    s.source_current_a = (voltage - (s.voltage_v[positive_] - s.voltage_v[negative_])) / source_resistance_;
    const double limit = std::min(charge / dt, max_power > 0.0 ? max_power : charge / dt) / voltage;
    if (s.source_current_a > limit || s.source_current_a < 0.0) {
        s.limited = true;
        s.source_current_a = std::clamp(s.source_current_a, 0.0, limit);
        s.voltage_v = solveAt(true, s.source_current_a);
    }
    s.current_a.resize(count); s.motor_current_a.resize(count); s.torque_n_m.resize(count);
    s.branch_heat_j.resize(count); s.shaft_j.resize(count); s.heat_j.resize(heat_.size());
    std::vector<double> kcl(n);
    for (std::size_t i = 0; i < count; ++i) {
        const auto &b = branches_[i];
        const double current = g[i] * (s.voltage_v[b.a] - s.voltage_v[b.b] - emf[i]);
        s.current_a[i] = current;
        s.torque_n_m[i] = current * gain[i];
        s.motor_current_a[i] = command[i] != 0.0 ? current / command[i] : 0.0;
        s.branch_heat_j[i] = g[i] > 0.0 ? current * current / g[i] * dt : 0.0;
        s.heat_j[b.thermal] += s.branch_heat_j[i];
        s.shaft_j[i] = emf[i] * current * dt;
        kcl[b.a] += current; kcl[b.b] -= current;
    }
    kcl[positive_] -= s.source_current_a; kcl[negative_] += s.source_current_a;
    for (const double r : kcl) s.max_kcl_a = std::max(s.max_kcl_a, std::abs(r));
    const double source_loss = (voltage - s.voltage_v[positive_] + s.voltage_v[negative_]) * s.source_current_a * dt;
    require(source_loss >= -1e-8, "supply regulation would create energy");
    s.heat_j[source_heat_] += std::max(0.0, source_loss);
    s.source_j = voltage * s.source_current_a * dt;
    s.electrical_residual_j = s.source_j - std::accumulate(s.heat_j.begin(), s.heat_j.end(), 0.0) -
                              std::accumulate(s.shaft_j.begin(), s.shaft_j.end(), 0.0);
    const double scale = 1.0 + std::abs(s.source_j) +
                        std::accumulate(s.heat_j.begin(), s.heat_j.end(), 0.0);
    require(std::isfinite(s.electrical_residual_j) && std::abs(s.electrical_residual_j) <= 1e-8 * scale &&
            s.max_kcl_a <= 1e-8 * (1.0 + std::abs(s.source_current_a)), "electrical conservation tolerance exceeded");
    return s;
}

void Circuit::commit(const CircuitStep &s, double actual_work) {
    require(std::isfinite(actual_work) && s.heat_j.size() == heat_.size() && s.current_a.size() == branches_.size(),
            "invalid accepted step");
    const auto n = heat_.size();
    std::vector<std::vector<double>> a(n, std::vector<double>(n));
    std::vector<double> rhs(n);
    for (std::size_t i = 0; i < n; ++i) {
        const auto &h = heat_[i];
        a[i][i] = h.capacity / s.dt_s + h.ambient_conductance;
        rhs[i] = h.capacity / s.dt_s * h.temperature + s.heat_j[i] / s.dt_s + h.ambient_conductance * ambient_k_;
    }
    for (const auto &l : heat_links_) {
        a[l.a][l.a] += l.conductance; a[l.b][l.b] += l.conductance;
        a[l.a][l.b] -= l.conductance; a[l.b][l.a] -= l.conductance;
    }
    const auto temperatures = linear(std::move(a), std::move(rhs));
    double stored = 0.0, ambient = 0.0;
    for (std::size_t i = 0; i < n; ++i) {
        require(temperatures[i] > 0.0, "non-positive thermal state");
        stored += heat_[i].capacity * (temperatures[i] - heat_[i].temperature);
        ambient += heat_[i].ambient_conductance * (temperatures[i] - ambient_k_) * s.dt_s;
    }
    for (std::size_t i = 0; i < branches_.size(); ++i) {
        auto &b = branches_[i];
        if (b.fuse_limit > 0.0) b.fuse_used += s.current_a[i] * s.current_a[i] * s.dt_s;
        b.failed = b.failed || (b.fuse_limit > 0.0 && b.fuse_used >= b.fuse_limit) ||
                   (b.trip_k > 0.0 && std::max(heat_[b.thermal].temperature, temperatures[b.thermal]) >= b.trip_k);
    }
    for (std::size_t i = 0; i < n; ++i) heat_[i].temperature = temperatures[i];
    const double heat = std::accumulate(s.heat_j.begin(), s.heat_j.end(), 0.0);
    const double shaft = std::accumulate(s.shaft_j.begin(), s.shaft_j.end(), 0.0);
    elapsed_s_ += s.dt_s; source_j_ += s.source_j; heat_j_ += heat; shaft_j_ += actual_work; ambient_j_ += ambient;
    electrical_residual_j_ += s.electrical_residual_j;
    thermal_residual_j_ += stored + ambient - heat;
    coupling_residual_j_ += actual_work - shaft;
    last_ = s;
}

void Circuit::setSwitch(const std::string &id, bool closed) {
    const auto it = std::find_if(branches_.begin(), branches_.end(), [&](const auto &b) { return b.id == id; });
    require(it != branches_.end() && it->kind == "switch", "no switch " + id);
    it->closed = closed;
}
void Circuit::addFrictionHeat(CircuitStep &s, std::size_t branch, double joules) const {
    require(std::isfinite(joules) && joules >= 0.0, "invalid friction heat");
    s.heat_j.at(branches_.at(branch).thermal) += joules;
    s.shaft_j.at(branch) -= joules;
}
std::vector<unsigned> Circuit::motors() const {
    std::vector<unsigned> out;
    for (const auto &b : branches_) if (b.motor) out.push_back(b.motor);
    return out;
}
unsigned Circuit::motor(std::size_t b) const { return branches_.at(b).motor; }
double Circuit::ratio(std::size_t b) const { return branches_.at(b).ratio; }
double Circuit::resistanceFactor(std::size_t b) const {
    const auto &branch = branches_.at(b);
    return 1.0 + branch.alpha * (heat_[branch.thermal].temperature - branch.reference_k);
}

nlohmann::json Circuit::saved() const {
    using nlohmann::json;
    json d{{"schema", "banjo.circuit.v1"}, {"id", id_}, {"nodes", nodes_}, {"ambient_k", ambient_k_},
           {"source", {{"store", store_}, {"positive", nodes_[positive_]}, {"negative", nodes_[negative_]},
                       {"resistance_ohm", source_resistance_}, {"thermal", heat_[source_heat_].id}}},
           {"branches", json::array()}, {"thermal_nodes", json::array()}, {"thermal_links", json::array()}};
    for (const auto &h : heat_) d["thermal_nodes"].push_back({{"id", h.id}, {"component", h.component},
        {"capacity_j_k", h.capacity}, {"temperature_k", h.temperature}, {"ambient_w_k", h.ambient_conductance}});
    for (const auto &l : heat_links_) d["thermal_links"].push_back({{"a", heat_[l.a].id}, {"b", heat_[l.b].id},
                                                               {"conductance_w_k", l.conductance}});
    for (std::size_t i = 0; i < branches_.size(); ++i) {
        const auto &b = branches_[i];
        json row{{"id", b.id}, {"kind", b.kind}, {"component", b.component}, {"a", nodes_[b.a]}, {"b", nodes_[b.b]},
                 {"thermal", heat_[b.thermal].id}, {"resistance_ohm", b.resistance}, {"alpha_per_k", b.alpha},
                 {"reference_k", b.reference_k}, {"trip_k", b.trip_k}, {"fuse_a2_s", b.fuse_limit},
                 {"used_a2_s", b.fuse_used}, {"failed", b.failed}, {"closed", b.closed}, {"gear_ratio", b.ratio}};
        if (b.motor) row["motor"] = b.motor;
        if (last_.current_a.size() == branches_.size()) {
            row["current_a"] = last_.current_a[i]; row["motor_current_a"] = last_.motor_current_a[i];
            row["torque_n_m"] = last_.torque_n_m[i]; row["housing_reaction_n_m"] = -last_.torque_n_m[i];
        }
        d["branches"].push_back(row);
    }
    d["ledger"] = {{"elapsed_s", elapsed_s_}, {"source_j", source_j_}, {"heat_j", heat_j_}, {"shaft_j", shaft_j_},
                   {"ambient_j", ambient_j_}, {"electrical_residual_j", electrical_residual_j_},
                   {"thermal_residual_j", thermal_residual_j_}, {"coupling_residual_j", coupling_residual_j_}};
    d["last"] = {{"voltage_v", last_.voltage_v}, {"source_current_a", last_.source_current_a},
                  {"power_limited", last_.limited}, {"max_kcl_a", last_.max_kcl_a}};
    return d;
}
}
