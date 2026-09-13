#include "thermo/ThermoWorld.hpp"

#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>
#include <unordered_map>

namespace banjo::thermo {
namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kGravityM_S2 = 9.80665;
constexpr std::size_t kNone = static_cast<std::size_t>(-1);
// A body keeps a separate surface layer when heat cannot cross it quickly --
// when its Biot number against the film coefficient is above this.
constexpr double kThickBiot = 0.1;
// Declared: how thick the layer that heats, radiates and burns is, for a body
// that conducts too poorly to be one temperature throughout. The thermal
// penetration depth of wood over a minute, sqrt(alpha t) with alpha about
// 1.5e-7 m2/s, is about 3 mm.
constexpr double kDefaultLayerM = 0.003;
// Two bounding boxes touch when they meet face to face within this gap, or
// overlap by no more than this much (resting contact has a little of both).
constexpr double kTouchGapM = 0.006;
constexpr double kTouchPenetrationM = 0.02;
// A body joins the network when something in it could move this much power
// into the body. Below it the body stays at the surroundings' temperature.
constexpr double kJoinPowerW = 0.02;
// The most a reaction may raise a parcel's temperature in one sub-step before
// the step is divided.
constexpr double kReactionStepK = 20.0;
// Below this the gas has, for practical purposes, no temperature left to lose.
constexpr double kColdestGasK = 1.0;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::invalid_argument(message);
}

// Exact exchange between two parcels through a conductance, with both heat
// capacities held fixed over the step: the energy that moves from a to b.
double pairTransfer(double ta, double tb, double ca, double cb, double conductance, double dt) {
    if (!(conductance > 0.0) || !(dt > 0.0) || !(ca > 0.0) || !(cb > 0.0) || ta == tb) return 0.0;
    const double rate = conductance * (1.0 / ca + 1.0 / cb);
    const double settled = -std::expm1(-rate * dt);
    return (ca * cb / (ca + cb)) * (ta - tb) * settled;
}

// Exact relaxation of one parcel towards a fixed temperature: the energy that leaves it.
double relaxTransfer(double t, double fixed, double capacity, double conductance, double dt) {
    if (!(conductance > 0.0) || !(dt > 0.0) || !(capacity > 0.0) || t == fixed) return 0.0;
    return capacity * (t - fixed) * -std::expm1(-conductance * dt / capacity);
}

// sigma eps A (T1^2 + T2^2)(T1 + T2): times (T1 - T2) it is exactly
// sigma eps A (T1^4 - T2^4), so the exact pair update above carries radiation
// to first order and can never overshoot.
double radiationConductance(double area, double emissivity, double t1, double t2) {
    if (!(area > 0.0) || !(emissivity > 0.0)) return 0.0;
    return kStefanBoltzmannWM2K4 * emissivity * area * (t1 * t1 + t2 * t2) * (t1 + t2);
}

Vec3 find(const std::vector<Moved> &moved, const std::string &body) {
    if (body.empty()) return {};
    for (const Moved &m : moved)
        if (m.body == body) return m.displacement_m;
    return {};
}

} // namespace

struct ThermoWorld::Impl {
    Model model;
    Ambient ambient;
    std::vector<double> air;
    double air_gas_constant{};
    std::vector<bool> fuel;
    std::vector<double> quoted_heat;   // per reaction, J per kg of basis at 298.15 K
    ThermoState s;
    std::vector<BodyShape> shapes;
    std::unordered_map<std::string, std::size_t> shape_of;
    double floor_y{};

    explicit Impl(Model m) : model(std::move(m)) {
        model.validate();
        derive();
    }

    void derive() {
        air.assign(model.size(), 0.0);
        if (!ambient.mass_fraction.empty()) {
            require(ambient.mass_fraction.size() == model.size(),
                    "the surroundings' composition needs one fraction per substance");
            air = ambient.mass_fraction;
        } else {
            const std::pair<const char *, double> dry_air[] = {
                {"nitrogen", 0.7552}, {"oxygen", 0.2314}, {"argon", 0.0129}, {"carbon dioxide", 0.0005}};
            for (const auto &[id, fraction] : dry_air)
                if (model.has(id)) air[model.index(id)] = fraction;
        }
        double sum = 0.0;
        for (std::size_t i = 0; i < air.size(); ++i) {
            require(air[i] >= 0.0 && std::isfinite(air[i]), "a fraction is finite and not negative");
            require(air[i] == 0.0 || model[i].phase == Phase::Gas, "the surroundings are gas");
            sum += air[i];
        }
        air_gas_constant = 0.0;
        if (sum > 0.0)
            for (std::size_t i = 0; i < air.size(); ++i) {
                air[i] /= sum;
                air_gas_constant += air[i] * gasConstantJKgK(model[i]);
            }
        fuel.assign(model.size(), false);
        for (std::size_t i = 0; i < model.size(); ++i) fuel[i] = model.isFuel(i);
        quoted_heat.clear();
        for (const Reaction &reaction : model.reactions)
            quoted_heat.push_back(model.heatOfReactionJPerKg(reaction, kQuotedTemperatureK));
    }

    [[nodiscard]] double airDensity() const {
        return air_gas_constant > 0.0 ? ambient.pressure_pa / (air_gas_constant * ambient.temperature_k)
                                      : 0.0;
    }

    [[nodiscard]] std::size_t lumpOf(const std::string &body) const {
        for (std::size_t i = 0; i < s.lumps.size(); ++i)
            if (s.lumps[i].body == body) return i;
        return kNone;
    }

    [[nodiscard]] int regionOf(const std::string &name) const {
        for (std::size_t i = 0; i < s.regions.size(); ++i)
            if (s.regions[i].name == name) return static_cast<int>(i);
        return -1;
    }

    [[nodiscard]] const BodyShape *shape(const std::string &name) const {
        const auto found = shape_of.find(name);
        return found == shape_of.end() ? nullptr : &shapes[found->second];
    }

    [[nodiscard]] double temperature(const Parcel &p) const { return temperatureK(model, p); }
    [[nodiscard]] double capacity(const Parcel &p) const { return heatCapacityJK(model, p); }
    [[nodiscard]] double fuelIn(const Parcel &p) const {
        double total = 0.0;
        for (std::size_t i = 0; i < p.kg.size(); ++i)
            if (fuel[i]) total += p.kg[i];
        return total;
    }
    [[nodiscard]] static double lumpEnergy(const Lump &l) {
        return l.surface.internal_energy_j + l.core.internal_energy_j;
    }
    [[nodiscard]] static double lumpMass(const Lump &l) { return massKg(l.surface) + massKg(l.core); }

    // How far heat has to go inside a lump to reach where it is exchanged.
    [[nodiscard]] static double reach(const Lump &l) {
        if (l.layer_depth_m > 0.0) return 0.5 * l.layer_depth_m;
        return l.area_m2 > 0.0 ? 0.5 * l.volume_m3 / l.area_m2 : 0.0;
    }

    void coreConductance(Lump &l) const {
        if (!(l.layer_depth_m > 0.0) || !(l.area_m2 > 0.0)) {
            l.core_conductance_w_k = 0.0;
            return;
        }
        const double characteristic = l.volume_m3 / l.area_m2;
        const double distance = std::max(l.layer_depth_m, characteristic - 0.5 * l.layer_depth_m);
        l.core_conductance_w_k = l.conductivity_w_m_k * l.area_m2 / distance;
    }

    Lump makeLump(const BodyShape &shape, const std::vector<std::pair<std::size_t, double>> &fractions,
                  double temperature_k, double layer_depth_m, bool declared) const {
        require(shape.mass_kg > 0.0 && std::isfinite(shape.mass_kg),
                shape.name + " has no mass to hold anything");
        require(shape.volume_m3 > 0.0 && shape.area_m2 > 0.0,
                shape.name + " has no volume or surface to hold anything");
        Lump lump;
        lump.body = shape.name;
        lump.material = shape.material;
        lump.declared = declared;
        lump.anchored = shape.anchored;
        lump.area_m2 = shape.area_m2;
        lump.exposed_area_m2 = shape.area_m2;
        lump.volume_m3 = shape.volume_m3;
        double k = 0.0, k_weight = 0.0, e = 0.0, e_weight = 0.0;
        std::vector<double> kg(model.size(), 0.0);
        for (const auto &[substance, fraction] : fractions) {
            kg[substance] += fraction * shape.mass_kg;
            const Substance &what = model[substance];
            if (what.conductivity_w_m_k > 0.0) {
                k += fraction * what.conductivity_w_m_k;
                k_weight += fraction;
            }
            if (what.phase != Phase::Gas) {
                e += fraction * what.emissivity;
                e_weight += fraction;
            }
        }
        lump.conductivity_w_m_k = k_weight > 0.0 ? k / k_weight : 1.0;
        lump.emissivity = e_weight > 0.0 ? e / e_weight : 0.9;
        const double characteristic = shape.volume_m3 / shape.area_m2;
        double depth = layer_depth_m;
        if (depth < 0.0)
            depth = ambient.film_coefficient_w_m2_k * characteristic / lump.conductivity_w_m_k > kThickBiot
                        ? kDefaultLayerM
                        : 0.0;
        Parcel whole = parcelAt(model, std::move(kg), temperature_k);
        const double share = depth > 0.0 && depth < characteristic
                                 ? std::min(1.0, shape.area_m2 * depth / shape.volume_m3)
                                 : 1.0;
        if (share < 1.0) {
            lump.core = takeShare(whole, 1.0 - share);
            lump.layer_depth_m = depth;
        } else {
            lump.core = emptyParcel(model);
        }
        lump.surface = std::move(whole);
        lump.layer_fuel_kg = fuelIn(lump.surface);
        lump.mirrored_mass_kg = shape.mass_kg;
        coreConductance(lump);
        return lump;
    }

    void join(const Lump &lump) {
        if (!s.opened) return;
        s.ledger.joined_j += lumpEnergy(lump);
        s.ledger.joined_kg += lumpMass(lump);
    }

    void leave(const Lump &lump) {
        if (!s.opened) return;
        s.ledger.left_j += lumpEnergy(lump);
        s.ledger.left_kg += lumpMass(lump);
    }

    std::size_t activate(const std::string &body) {
        const BodyShape *found = shape(body);
        if (found == nullptr) return kNone;
        const auto composition = model.composition_of.find(found->material);
        if (composition == model.composition_of.end()) return kNone;
        s.lumps.push_back(makeLump(*found, composition->second, ambient.temperature_k, -1.0, false));
        join(s.lumps.back());
        return s.lumps.size() - 1;
    }

    [[nodiscard]] bool busy(std::size_t i) const {
        const Lump &l = s.lumps[i];
        if (std::abs(temperature(l.surface) - ambient.temperature_k) > 0.5) return true;
        if (l.fuel_use_kg_s > 0.0 || l.heater_w > 0.0) return true;
        for (const Heater &h : s.heaters)
            if (h.what.target == l.body) return true;
        return false;
    }

    // The heat paths, from where everything is now.
    void couple() {
        s.contacts.clear();
        s.sights.clear();
        s.sky_fraction.clear();
        s.floor_conductance_w_k.clear();
        std::set<std::pair<std::size_t, std::size_t>> paired;
        std::vector<double> touching(s.lumps.size(), 0.0), floor_area(s.lumps.size(), 0.0);
        // Lumps that join during this pass are coupled in it too: the loop runs
        // to the size the table has reached.
        for (std::size_t a = 0; a < s.lumps.size(); ++a) {
            touching.resize(s.lumps.size(), 0.0);
            floor_area.resize(s.lumps.size(), 0.0);
            const BodyShape *sa = shape(s.lumps[a].body);
            if (sa == nullptr) continue;
            s.lumps[a].area_m2 = sa->area_m2;
            s.lumps[a].volume_m3 = sa->volume_m3;
            s.lumps[a].anchored = sa->anchored;
            coreConductance(s.lumps[a]);
            const bool hot = busy(a);
            const double ta = temperature(s.lumps[a].surface);
            for (const BodyShape &sb : shapes) {
                if (sb.name == sa->name) continue;
                double overlap[3];
                for (int k = 0; k < 3; ++k) {
                    const double ca = k == 0 ? sa->center_m.x : k == 1 ? sa->center_m.y : sa->center_m.z;
                    const double cb = k == 0 ? sb.center_m.x : k == 1 ? sb.center_m.y : sb.center_m.z;
                    const double ha = k == 0 ? sa->half_extent_m.x : k == 1 ? sa->half_extent_m.y : sa->half_extent_m.z;
                    const double hb = k == 0 ? sb.half_extent_m.x : k == 1 ? sb.half_extent_m.y : sb.half_extent_m.z;
                    overlap[k] = std::min(ca + ha, cb + hb) - std::max(ca - ha, cb - hb);
                }
                const int thin = overlap[0] <= overlap[1] ? (overlap[0] <= overlap[2] ? 0 : 2)
                                                          : (overlap[1] <= overlap[2] ? 1 : 2);
                const int u = (thin + 1) % 3, v = (thin + 2) % 3;
                const bool contact = overlap[thin] >= -kTouchGapM && overlap[thin] <= kTouchPenetrationM &&
                                     overlap[u] > 0.001 && overlap[v] > 0.001;
                std::size_t b = lumpOf(sb.name);
                if (contact) {
                    const double area = overlap[u] * overlap[v];
                    // Already coupled from the other end, with both areas counted.
                    if (b != kNone && paired.count({std::min(a, b), std::max(a, b)})) continue;
                    // A face against something is not a face open to the air,
                    // whether or not that something has joined the network.
                    touching[a] += area;
                    if (b == kNone) {
                        if (!hot) continue;
                        b = activate(sb.name);
                        if (b == kNone) continue;
                        touching.resize(s.lumps.size(), 0.0);
                        floor_area.resize(s.lumps.size(), 0.0);
                    }
                    paired.insert({std::min(a, b), std::max(a, b)});
                    const double resistance = 1.0 / ambient.contact_conductance_w_m2_k +
                                              reach(s.lumps[a]) / s.lumps[a].conductivity_w_m_k +
                                              reach(s.lumps[b]) / s.lumps[b].conductivity_w_m_k;
                    s.contacts.push_back({a, b, area, area / resistance});
                    touching[b] += area;
                    continue;
                }
                // Seen across a gap. Each body as an isotropic radiator whose
                // mean projected area is a quarter of its surface (Cauchy), so
                // the pair's exchange area is A_a A_b / (16 pi d^2) -- the same
                // from either end, which is reciprocity. Valid when they are
                // further apart than their size; capped for when they are not.
                const Vec3 gap = sa->center_m - sb.center_m;
                const double ra = std::sqrt(sa->area_m2 / (4.0 * kPi));
                const double rb = std::sqrt(sb.area_m2 / (4.0 * kPi));
                const double distance2 = std::max(dot(gap, gap), (ra + rb) * (ra + rb));
                const double exchange = std::min(sa->area_m2 * sb.area_m2 / (16.0 * kPi * distance2),
                                                 0.2 * std::min(sa->area_m2, sb.area_m2));
                if (!(exchange > 0.0)) continue;
                if (b == kNone) {
                    const double tamb = ambient.temperature_k;
                    const double power = exchange * s.lumps[a].emissivity * kStefanBoltzmannWM2K4 *
                                         std::abs(ta * ta * ta * ta - tamb * tamb * tamb * tamb);
                    if (!hot || power < kJoinPowerW) continue;
                    b = activate(sb.name);
                    if (b == kNone) continue;
                    touching.resize(s.lumps.size(), 0.0);
                    floor_area.resize(s.lumps.size(), 0.0);
                }
                if (!paired.insert({std::min(a, b), std::max(a, b)}).second) continue;
                const double ea = s.lumps[a].emissivity, eb = s.lumps[b].emissivity;
                const double pair = ea > 0.0 && eb > 0.0 ? 1.0 / (1.0 / ea + 1.0 / eb - 1.0) : 0.0;
                s.sights.push_back({a, b, exchange, pair});
            }
            if (sa->center_m.y - sa->half_extent_m.y <= floor_y + kTouchGapM)
                floor_area[a] = 4.0 * sa->half_extent_m.x * sa->half_extent_m.z;
        }
        s.sky_fraction.assign(s.lumps.size(), 1.0);
        s.floor_conductance_w_k.assign(s.lumps.size(), 0.0);
        std::vector<double> seen(s.lumps.size(), 0.0);
        for (const Sight &sight : s.sights) {
            seen[sight.a] += sight.exchange_area_m2;
            seen[sight.b] += sight.exchange_area_m2;
        }
        for (std::size_t i = 0; i < s.lumps.size(); ++i) {
            Lump &l = s.lumps[i];
            const double floor = i < floor_area.size() ? floor_area[i] : 0.0;
            const double touched = i < touching.size() ? touching[i] : 0.0;
            l.exposed_area_m2 = std::max(0.2 * l.area_m2, l.area_m2 - touched - floor);
            s.floor_conductance_w_k[i] = ambient.floor_conductance_w_m2_k * floor;
            s.sky_fraction[i] = l.area_m2 > 0.0 ? std::clamp(1.0 - seen[i] / l.area_m2, 0.1, 1.0) : 1.0;
        }
    }

    // How much of an environment reactant the surroundings hold per m3.
    [[nodiscard]] double environmentDensity(std::size_t substance, int environment) const {
        if (environment < 0) return air[substance] * airDensity();
        const GasRegion &region = s.regions[static_cast<std::size_t>(environment)];
        return region.volume_m3 > 0.0 ? region.gas.kg[substance] / region.volume_m3 : 0.0;
    }

    void applyExtent(Lump &lump, Parcel &p, const Reaction &reaction, double extent, double t) {
        GasRegion *region = lump.environment >= 0 ? &s.regions[static_cast<std::size_t>(lump.environment)]
                                                  : nullptr;
        for (const Term &term : reaction.reactants) {
            const double amount = extent * term.kg_per_kg;
            if (term.supply == Supply::Material) {
                p.kg[term.substance] = std::max(0.0, p.kg[term.substance] - amount);
                continue;
            }
            // From the surroundings, bringing its enthalpy: the surroundings
            // push it in.
            if (region == nullptr) {
                const double brought =
                    amount * specificEnthalpyJKg(model[term.substance], ambient.temperature_k);
                p.internal_energy_j += brought;
                s.ledger.matter_in_j += brought;
                s.ledger.matter_in_kg += amount;
            } else {
                const double brought =
                    amount * specificEnthalpyJKg(model[term.substance], temperature(region->gas));
                region->gas.kg[term.substance] = std::max(0.0, region->gas.kg[term.substance] - amount);
                region->gas.internal_energy_j -= brought;
                p.internal_energy_j += brought;
            }
        }
        for (const Term &term : reaction.products) {
            const double amount = extent * term.kg_per_kg;
            if (term.fate == Fate::Retained) {
                p.kg[term.substance] += amount;
                continue;
            }
            // Leaves at the temperature it was made at, carrying its enthalpy.
            const double carried = amount * specificEnthalpyJKg(model[term.substance], t);
            p.internal_energy_j -= carried;
            if (region == nullptr) {
                s.ledger.matter_out_j += carried;
                s.ledger.matter_out_kg += amount;
            } else {
                region->gas.kg[term.substance] += amount;
                region->gas.internal_energy_j += carried;
            }
        }
    }

    void react(Lump &lump, Parcel &p, bool surface_zone, double dt) {
        if (model.reactions.empty() || massKg(p) <= 0.0) return;
        double remaining = dt;
        for (int round = 0; remaining > 0.0 && round < 4096; ++round) {
            const double t = temperature(p);
            const double c = capacity(p);
            struct Going { std::size_t reaction; double rate; double k; };
            std::vector<Going> going;
            double heating = 0.0;
            for (std::size_t r = 0; r < model.reactions.size(); ++r) {
                const Reaction &reaction = model.reactions[r];
                if (reaction.rate.kind == RateKind::Surface && !surface_zone) continue;
                const std::size_t basis = reaction.reactants.front().substance;
                if (!(p.kg[basis] > 0.0) || t < reaction.rate.minimum_temperature_k) continue;
                const double evaluated = std::min(t, reaction.rate.maximum_temperature_k);
                const double k = reaction.rate.pre_exponential *
                                 std::exp(-reaction.rate.activation_temperature_k / evaluated);
                double rate = 0.0;
                if (reaction.rate.kind == RateKind::Surface) {
                    double flux = k;
                    for (const Term &term : reaction.reactants) {
                        if (term.supply != Supply::Environment) continue;
                        const double density = environmentDensity(term.substance, lump.environment);
                        if (!(density > 0.0)) {
                            flux = 0.0;
                            break;
                        }
                        if (reaction.rate.supply_coefficient_m_s > 0.0) {
                            const double supply =
                                reaction.rate.supply_coefficient_m_s * density / term.kg_per_kg;
                            flux = flux > 0.0 ? 1.0 / (1.0 / flux + 1.0 / supply) : 0.0;
                        }
                    }
                    rate = flux * lump.exposed_area_m2;
                } else {
                    // A volume reaction that needs its surroundings cannot run
                    // where they hold none of what it needs.
                    bool supplied = true;
                    for (const Term &term : reaction.reactants)
                        if (term.supply == Supply::Environment &&
                            !(environmentDensity(term.substance, lump.environment) > 0.0))
                            supplied = false;
                    rate = supplied ? k * p.kg[basis] : 0.0;
                }
                if (!(rate > 0.0)) continue;
                going.push_back({r, rate, k});
                heating += rate * std::abs(quoted_heat[r]);
            }
            if (going.empty()) return;
            double h = remaining;
            if (c > 0.0 && heating * h / c > kReactionStepK)
                h = std::max(remaining / 4096.0, kReactionStepK * c / heating);
            h = std::min(h, remaining);
            for (const Going &g : going) {
                const Reaction &reaction = model.reactions[g.reaction];
                const std::size_t basis = reaction.reactants.front().substance;
                double extent = reaction.rate.kind == RateKind::Volume
                                    ? p.kg[basis] * -std::expm1(-g.k * h)
                                    : g.rate * h;
                for (const Term &term : reaction.reactants) {
                    if (term.supply == Supply::Material) {
                        extent = std::min(extent, p.kg[term.substance] / term.kg_per_kg);
                    } else if (lump.environment >= 0) {
                        const GasRegion &region = s.regions[static_cast<std::size_t>(lump.environment)];
                        extent = std::min(extent, region.gas.kg[term.substance] / term.kg_per_kg);
                    }
                }
                if (!(extent > 0.0)) continue;
                applyExtent(lump, p, reaction, extent, t);
                lump.heat_release_w += extent / dt * quoted_heat[g.reaction];
                if (fuel[basis]) lump.fuel_use_kg_s += extent / dt;
            }
            remaining -= h;
        }
    }

    // The burning front advances into the core as the layer's fuel is used,
    // and brings whatever the core holds with it -- moisture and ash too.
    void replenish(Lump &lump) {
        if (!(lump.layer_fuel_kg > 0.0)) return;
        const double deficit = lump.layer_fuel_kg - fuelIn(lump.surface);
        const double core_fuel = fuelIn(lump.core);
        if (!(deficit > 0.0) || !(core_fuel > 0.0)) return;
        pour(lump.surface, takeShare(lump.core, std::min(1.0, deficit / core_fuel)));
    }

    // An orifice to the surroundings. Incompressible orifice flow, declared:
    // right for modest pressure differences, not for choked flow.
    void vent(GasRegion &region, double dt) {
        if (!region.vent_open || !(region.vent_area_m2 > 0.0) || !(region.volume_m3 > 0.0)) return;
        constexpr double kDischarge = 0.6;
        const double t = temperature(region.gas);
        const double p = pressurePa(model, region.gas, region.volume_m3);
        const double dp = p - ambient.pressure_pa;
        double gas_constant = 0.0;
        const double m = massKg(region.gas);
        for (std::size_t i = 0; i < region.gas.kg.size(); ++i)
            gas_constant += region.gas.kg[i] * gasConstantJKgK(model[i]);
        if (m > 0.0) gas_constant /= m;
        if (dp > 0.0 && m > 0.0 && gas_constant > 0.0 && t > 0.0) {
            const double density = p / (gas_constant * t);
            double out = kDischarge * region.vent_area_m2 * std::sqrt(2.0 * density * dp) * dt;
            // Never past equality in one step.
            out = std::min(out, 0.5 * dp * region.volume_m3 / (gas_constant * t));
            out = std::min(out, 0.5 * m);
            Parcel leaving = takeShare(region.gas, out / m);
            // What leaves a rigid vessel carries its enthalpy: the gas behind
            // it does the flow work, and pays for it.
            double flow_work = 0.0;
            for (std::size_t i = 0; i < leaving.kg.size(); ++i)
                flow_work += leaving.kg[i] * gasConstantJKgK(model[i]) * t;
            region.gas.internal_energy_j -= flow_work;
            s.ledger.matter_out_j += leaving.internal_energy_j + flow_work;
            s.ledger.matter_out_kg += massKg(leaving);
            region.vent_flow_kg_s = out / dt;
        } else if (dp < 0.0 && air_gas_constant > 0.0) {
            const double density = airDensity();
            double in = kDischarge * region.vent_area_m2 * std::sqrt(2.0 * density * -dp) * dt;
            in = std::min(in, 0.5 * -dp * region.volume_m3 / (air_gas_constant * std::max(t, 1.0)));
            double brought = 0.0;
            for (std::size_t i = 0; i < air.size(); ++i) {
                region.gas.kg[i] += in * air[i];
                brought += in * air[i] * specificEnthalpyJKg(model[i], ambient.temperature_k);
            }
            region.gas.internal_energy_j += brought;
            s.ledger.matter_in_j += brought;
            s.ledger.matter_in_kg += in;
            region.vent_flow_kg_s = -in / dt;
        }
    }

    void exchange(double dt) {
        for (Lump &l : s.lumps) l.gained_w = l.lost_w = 0.0;
        for (const Contact &contact : s.contacts) {
            Lump &a = s.lumps[contact.a];
            Lump &b = s.lumps[contact.b];
            const double q = pairTransfer(temperature(a.surface), temperature(b.surface),
                                          capacity(a.surface), capacity(b.surface),
                                          contact.conductance_w_k, dt);
            a.surface.internal_energy_j -= q;
            b.surface.internal_energy_j += q;
            a.gained_w -= q / dt;
            b.gained_w += q / dt;
        }
        for (const Sight &sight : s.sights) {
            Lump &a = s.lumps[sight.a];
            Lump &b = s.lumps[sight.b];
            const double ta = temperature(a.surface), tb = temperature(b.surface);
            const double g = radiationConductance(sight.exchange_area_m2, sight.emissivity, ta, tb);
            const double q = pairTransfer(ta, tb, capacity(a.surface), capacity(b.surface), g, dt);
            a.surface.internal_energy_j -= q;
            b.surface.internal_energy_j += q;
            a.gained_w -= q / dt;
            b.gained_w += q / dt;
        }
        const double tamb = ambient.temperature_k;
        for (std::size_t i = 0; i < s.lumps.size(); ++i) {
            Lump &l = s.lumps[i];
            if (l.core_conductance_w_k > 0.0 && massKg(l.core) > 0.0) {
                const double q = pairTransfer(temperature(l.surface), temperature(l.core),
                                              capacity(l.surface), capacity(l.core),
                                              l.core_conductance_w_k, dt);
                l.surface.internal_energy_j -= q;
                l.core.internal_energy_j += q;
            }
            const double t = temperature(l.surface);
            const double c = capacity(l.surface);
            const double sky = i < s.sky_fraction.size() ? s.sky_fraction[i] : 1.0;
            const double floor = i < s.floor_conductance_w_k.size() ? s.floor_conductance_w_k[i] : 0.0;
            if (l.environment < 0) {
                const double g = ambient.film_coefficient_w_m2_k * l.exposed_area_m2 +
                                 radiationConductance(l.exposed_area_m2 * sky, l.emissivity, t, tamb) +
                                 floor;
                const double q = relaxTransfer(t, tamb, c, g, dt);
                l.surface.internal_energy_j -= q;
                s.ledger.heat_to_surroundings_j += q;
                l.lost_w = q / dt;
            } else {
                // Inside a gas region, its surroundings ARE the region's gas.
                GasRegion &region = s.regions[static_cast<std::size_t>(l.environment)];
                const double tg = temperature(region.gas);
                const double g = ambient.film_coefficient_w_m2_k * l.exposed_area_m2 +
                                 radiationConductance(l.exposed_area_m2, l.emissivity, t, tg);
                const double q = pairTransfer(t, tg, c, capacity(region.gas), g, dt);
                l.surface.internal_energy_j -= q;
                region.gas.internal_energy_j += q;
                l.lost_w = q / dt;
            }
        }
        for (GasRegion &region : s.regions) {
            const double q = relaxTransfer(temperature(region.gas), tamb, capacity(region.gas),
                                           region.wall_conductance_w_k, dt);
            region.gas.internal_energy_j -= q;
            s.ledger.heat_to_surroundings_j += q;
            region.wall_loss_w = q / dt;
        }
    }

    void measure(Ledger &ledger) const {
        double reference = 0.0, total = 0.0, mass = 0.0;
        const auto add = [&](const Parcel &p) {
            reference += referenceEnergyJ(model, p);
            total += p.internal_energy_j;
            mass += massKg(p);
        };
        for (const Lump &l : s.lumps) {
            add(l.surface);
            add(l.core);
        }
        for (const GasRegion &r : s.regions) add(r.gas);
        ledger.reference_j = reference;
        ledger.sensible_j = total - reference;
        ledger.mass_kg = mass;
    }

    // Everything the network holds that nobody told it about is gone: a body
    // that left the world without split() or remove() having been called.
    void forgetMissing() {
        for (std::size_t i = s.lumps.size(); i-- > 0;) {
            if (shape(s.lumps[i].body) != nullptr) continue;
            leave(s.lumps[i]);
            s.lumps.erase(s.lumps.begin() + static_cast<std::ptrdiff_t>(i));
        }
    }

    // Where a piston's face is, and how thick it is along the axis.
    [[nodiscard]] static double extentAlong(const BodyShape &shape, const Vec3 &axis) {
        return shape.half_extent_m.x * std::abs(axis.x) + shape.half_extent_m.y * std::abs(axis.y) +
               shape.half_extent_m.z * std::abs(axis.z);
    }

    // What rests on a body, and on what rests on it: the load a piston carries.
    [[nodiscard]] double restingMass(const BodyShape &base) const {
        std::vector<const BodyShape *> below{&base};
        std::set<std::string> counted{base.name};
        double mass = 0.0;
        while (!below.empty()) {
            const BodyShape *under = below.back();
            below.pop_back();
            const double top = under->center_m.y + under->half_extent_m.y;
            for (const BodyShape &other : shapes) {
                if (other.anchored || counted.count(other.name)) continue;
                const double bottom = other.center_m.y - other.half_extent_m.y;
                if (std::abs(bottom - top) > kTouchPenetrationM) continue;
                const double ox = std::min(under->center_m.x + under->half_extent_m.x,
                                           other.center_m.x + other.half_extent_m.x) -
                                  std::max(under->center_m.x - under->half_extent_m.x,
                                           other.center_m.x - other.half_extent_m.x);
                const double oz = std::min(under->center_m.z + under->half_extent_m.z,
                                           other.center_m.z + other.half_extent_m.z) -
                                  std::max(under->center_m.z - under->half_extent_m.z,
                                           other.center_m.z - other.half_extent_m.z);
                if (ox <= 0.001 || oz <= 0.001) continue;
                mass += other.mass_kg;
                counted.insert(other.name);
                below.push_back(&other);
            }
        }
        return mass;
    }
};

ThermoWorld::ThermoWorld(Model model) : impl_(std::make_unique<Impl>(std::move(model))) {}
ThermoWorld::~ThermoWorld() = default;

const Model &ThermoWorld::model() const { return impl_->model; }

void ThermoWorld::setAmbient(Ambient ambient) {
    require(impl_->s.lumps.empty() && impl_->s.regions.empty(),
            "the surroundings are set before anything is declared");
    require(std::isfinite(ambient.temperature_k) && ambient.temperature_k > 0.0,
            "the surroundings need a temperature above absolute zero");
    require(std::isfinite(ambient.pressure_pa) && ambient.pressure_pa > 0.0,
            "the surroundings need a pressure");
    require(ambient.film_coefficient_w_m2_k >= 0.0 && ambient.floor_conductance_w_m2_k >= 0.0 &&
                ambient.contact_conductance_w_m2_k > 0.0,
            "conductances are not negative, and contact conductance is positive");
    impl_->ambient = std::move(ambient);
    impl_->derive();
}

const Ambient &ThermoWorld::ambient() const { return impl_->ambient; }

void ThermoWorld::refresh(const std::vector<BodyShape> &bodies, double floor_y_m) {
    Impl &w = *impl_;
    w.shapes = bodies;
    w.shape_of.clear();
    for (std::size_t i = 0; i < w.shapes.size(); ++i) w.shape_of.emplace(w.shapes[i].name, i);
    w.floor_y = floor_y_m;
    w.forgetMissing();
    w.couple();
}

void ThermoWorld::declareContents(const ContentsDeclaration &d) {
    Impl &w = *impl_;
    const BodyShape *shape = w.shape(d.body);
    require(shape != nullptr, "there is nothing called \"" + d.body + "\" to hold contents");
    std::vector<std::pair<std::size_t, double>> fractions;
    if (d.mass_fraction.empty()) {
        const auto composition = w.model.composition_of.find(shape->material);
        require(composition != w.model.composition_of.end(),
                d.body + " is " + shape->material + ", which the model has no composition for: "
                         "say what it contains");
        fractions = composition->second;
    } else {
        double sum = 0.0;
        for (const auto &[id, fraction] : d.mass_fraction) {
            require(std::isfinite(fraction) && fraction >= 0.0,
                    d.body + ": every fraction is finite and not negative");
            if (fraction > 0.0) fractions.emplace_back(w.model.index(id), fraction);
            sum += fraction;
        }
        require(sum > 0.0, d.body + ": contents need something in them");
        for (auto &entry : fractions) entry.second /= sum;
    }
    const double t = d.temperature_k > 0.0 ? d.temperature_k : w.ambient.temperature_k;
    require(std::isfinite(t) && t <= w.model.maximum_temperature_k,
            d.body + ": a temperature inside the model's range");
    Lump lump = w.makeLump(*shape, fractions, t, d.layer_depth_m, true);
    if (!d.environment.empty()) {
        lump.environment = w.regionOf(d.environment);
        require(lump.environment >= 0, d.body + ": there is no gas region called " + d.environment);
    }
    const std::size_t existing = w.lumpOf(d.body);
    if (existing != kNone) {
        w.leave(w.s.lumps[existing]);
        w.s.lumps[existing] = std::move(lump);
        w.join(w.s.lumps[existing]);
    } else {
        w.s.lumps.push_back(std::move(lump));
        w.join(w.s.lumps.back());
    }
    w.couple();
}

void ThermoWorld::declareGasRegion(const GasRegionDeclaration &d) {
    Impl &w = *impl_;
    require(!d.name.empty(), "a gas region needs a name");
    require(w.regionOf(d.name) < 0, "there is already a gas region called " + d.name);
    require(w.shape(d.name) == nullptr, d.name + " is already the name of a body");
    std::vector<double> fractions(w.model.size(), 0.0);
    double sum = 0.0;
    for (const auto &[id, fraction] : d.mass_fraction) {
        const std::size_t i = w.model.index(id);
        require(w.model[i].phase == Phase::Gas, d.name + ": " + id + " is not a gas");
        require(std::isfinite(fraction) && fraction >= 0.0, d.name + ": fractions are not negative");
        fractions[i] += fraction;
        sum += fraction;
    }
    if (d.mass_fraction.empty()) {
        fractions = w.air;
        sum = 1.0;
    }
    require(sum > 0.0, d.name + ": a gas region needs some gas");
    for (double &f : fractions) f /= sum;

    GasRegion region;
    region.name = d.name;
    const Vec3 axis = normalized(d.axis, Vec3{0.0, 1.0, 0.0});
    double area = d.area_m2;
    const BodyShape *piston = nullptr;
    if (!d.piston.empty()) {
        piston = w.shape(d.piston);
        require(piston != nullptr, d.name + ": there is nothing called " + d.piston + " to push on");
        require(!piston->anchored, d.name + ": " + d.piston + " is anchored and cannot move");
        if (!(area > 0.0)) area = piston->volume_m3 / (2.0 * Impl::extentAlong(*piston, axis));
    }
    double volume = d.volume_m3;
    if (!(volume > 0.0) && d.height_m > 0.0 && area > 0.0) volume = d.height_m * area;
    require(std::isfinite(volume) && volume > 0.0, d.name + ": a gas region needs a volume or a height");
    const double t = d.temperature_k > 0.0 ? d.temperature_k : w.ambient.temperature_k;
    double p = d.pressure_pa;
    if (d.balance) {
        require(piston != nullptr && area > 0.0, d.name + ": only a region with a piston can balance it");
        const double load = piston->mass_kg + w.restingMass(*piston);
        p = w.ambient.pressure_pa + load * kGravityM_S2 * std::max(0.0, axis.y) / area;
    }
    require(std::isfinite(p) && p > 0.0, d.name + ": a gas region needs a pressure, or balance");
    double gas_constant = 0.0;
    for (std::size_t i = 0; i < fractions.size(); ++i) gas_constant += fractions[i] * gasConstantJKgK(w.model[i]);
    const double mass = p * volume / (gas_constant * t);
    std::vector<double> kg(w.model.size(), 0.0);
    for (std::size_t i = 0; i < kg.size(); ++i) kg[i] = fractions[i] * mass;
    region.gas = parcelAt(w.model, std::move(kg), t);
    region.volume_m3 = volume;
    if (piston != nullptr) {
        PistonBoundary boundary;
        boundary.body = d.piston;
        boundary.container = d.container;
        if (!d.container.empty())
            require(w.shape(d.container) != nullptr, d.name + ": there is nothing called " + d.container);
        boundary.axis = axis;
        boundary.area_m2 = area;
        boundary.base_volume_m3 = volume;
        boundary.minimum_volume_m3 = 0.02 * volume;
        const Vec3 face = piston->center_m - axis * Impl::extentAlong(*piston, axis);
        boundary.base_m = face - axis * (volume / area);
        region.piston = boundary;
    }
    const double height = area > 0.0 ? volume / area : std::cbrt(volume);
    const double side = area > 0.0 ? std::sqrt(area) : std::cbrt(volume);
    region.wall_conductance_w_k =
        d.wall_conductance_w_k >= 0.0
            ? d.wall_conductance_w_k
            : w.ambient.film_coefficient_w_m2_k * (2.0 * side * side + 4.0 * side * height);
    region.vent_area_m2 = std::max(0.0, d.vent_area_m2);
    region.vent_open = d.vent_open;
    if (w.s.opened) {
        w.s.ledger.joined_j += region.gas.internal_energy_j;
        w.s.ledger.joined_kg += massKg(region.gas);
    }
    w.s.regions.push_back(std::move(region));
}

unsigned ThermoWorld::heat(const HeaterDeclaration &d) {
    Impl &w = *impl_;
    require(std::isfinite(d.power_w) && d.power_w >= 0.0 && d.power_w <= 1.0e8,
            "a heater's power is between 0 and 100 MW");
    require(std::isfinite(d.seconds) && d.seconds > 0.0 && d.seconds <= 1.0e6,
            "a heater runs for a positive time");
    require(std::isfinite(d.start_s) && d.start_s >= 0.0, "a heater starts at a time on the clock");
    if (w.regionOf(d.target) < 0 && w.lumpOf(d.target) == kNone) {
        require(w.shape(d.target) != nullptr, "there is nothing called \"" + d.target + "\" to heat");
        require(w.activate(d.target) != kNone,
                d.target + " is made of something the model cannot hold: declare its contents");
        w.couple();
    }
    Heater heater{w.s.next_heater++, d};
    w.s.heaters.push_back(heater);
    return heater.id;
}

void ThermoWorld::setVent(const std::string &region, bool open) {
    const int index = impl_->regionOf(region);
    require(index >= 0, "there is no gas region called " + region);
    impl_->s.regions[static_cast<std::size_t>(index)].vent_open = open;
}

std::vector<Push> ThermoWorld::pushes() {
    Impl &w = *impl_;
    std::vector<Push> out;
    for (GasRegion &region : w.s.regions) {
        if (!region.piston || w.shape(region.piston->body) == nullptr) continue;
        PistonBoundary &piston = *region.piston;
        const double p = pressurePa(w.model, region.gas, region.volume_m3);
        piston.pushed_pressure_pa = p;
        piston.pushed_force_n = piston.axis * ((p - w.ambient.pressure_pa) * piston.area_m2);
        out.push_back({piston.body, piston.pushed_force_n});
        if (!piston.container.empty() && w.shape(piston.container) != nullptr)
            out.push_back({piston.container, -piston.pushed_force_n});
    }
    return out;
}

void ThermoWorld::advance(double dt_s, const std::vector<Moved> &moved) {
    Impl &w = *impl_;
    require(std::isfinite(dt_s) && dt_s > 0.0, "a step needs a positive dt");
    if (!w.s.opened) {
        w.measure(w.s.ledger);
        w.s.ledger.initial_j = w.s.ledger.storedJ();
        w.s.ledger.initial_mass_kg = w.s.ledger.mass_kg;
        w.s.opened = true;
    }
    for (Lump &l : w.s.lumps) l.heat_release_w = l.fuel_use_kg_s = l.heater_w = 0.0;
    for (GasRegion &r : w.s.regions) r.heater_w = r.vent_flow_kg_s = 0.0;

    // Boundary work: the gas pays for exactly the force that was applied, over
    // exactly the displacement that happened. The mechanics received F.dx and
    // this is F.dx; the two cannot disagree because they are the same product.
    for (GasRegion &region : w.s.regions) {
        if (!region.piston) continue;
        PistonBoundary &piston = *region.piston;
        const Vec3 relative = find(moved, piston.body) - find(moved, piston.container);
        const double ds = dot(relative, piston.axis);
        const double p = piston.pushed_pressure_pa > 0.0
                             ? piston.pushed_pressure_pa
                             : pressurePa(w.model, region.gas, region.volume_m3);
        const double by_gas = p * piston.area_m2 * ds;
        const double to_atmosphere = w.ambient.pressure_pa * piston.area_m2 * ds;
        region.gas.internal_energy_j -= by_gas;
        w.s.ledger.work_to_bodies_j += by_gas - to_atmosphere;
        w.s.ledger.work_to_atmosphere_j += to_atmosphere;
        piston.work_to_bodies_j += by_gas - to_atmosphere;
        piston.work_to_atmosphere_j += to_atmosphere;
        piston.stroke_m += ds;
        piston.pushed_pressure_pa = 0.0;
        region.volume_m3 =
            std::max(piston.minimum_volume_m3, piston.base_volume_m3 + piston.area_m2 * piston.stroke_m);
        const double floor = referenceEnergyJ(w.model, region.gas) +
                             heatCapacityJK(w.model, region.gas) * kColdestGasK;
        if (region.gas.internal_energy_j < floor) {
            w.s.ledger.numerical_j += floor - region.gas.internal_energy_j;
            region.gas.internal_energy_j = floor;
        }
    }

    // Heaters: external work, in over the part of this step each one is on for.
    const double from = w.s.time_s, to = w.s.time_s + dt_s;
    for (const Heater &heater : w.s.heaters) {
        const double on = std::max(0.0, std::min(to, heater.what.start_s + heater.what.seconds) -
                                            std::max(from, heater.what.start_s));
        if (!(on > 0.0)) continue;
        const double energy = heater.what.power_w * on;
        const int region = w.regionOf(heater.what.target);
        if (region >= 0) {
            w.s.regions[static_cast<std::size_t>(region)].gas.internal_energy_j += energy;
            w.s.regions[static_cast<std::size_t>(region)].heater_w += energy / dt_s;
        } else {
            const std::size_t lump = w.lumpOf(heater.what.target);
            if (lump == kNone) continue;   // aimed at something that is gone
            w.s.lumps[lump].surface.internal_energy_j += energy;
            w.s.lumps[lump].heater_w += energy / dt_s;
        }
        w.s.ledger.heater_in_j += energy;
    }
    w.s.heaters.erase(std::remove_if(w.s.heaters.begin(), w.s.heaters.end(),
                                     [&](const Heater &h) { return h.what.start_s + h.what.seconds <= to; }),
                      w.s.heaters.end());

    for (GasRegion &region : w.s.regions) w.vent(region, dt_s);
    for (Lump &lump : w.s.lumps) {
        w.react(lump, lump.surface, true, dt_s);
        if (massKg(lump.core) > 0.0) w.react(lump, lump.core, false, dt_s);
        w.replenish(lump);
    }
    w.exchange(dt_s);
    w.s.time_s = to;

    const auto outside = [&](const Parcel &p) {
        if (massKg(p) <= 0.0) return false;
        const double t = w.temperature(p);
        return t < w.model.minimum_temperature_k || t > w.model.maximum_temperature_k;
    };
    bool out = false;
    for (const Lump &l : w.s.lumps) out = out || outside(l.surface) || outside(l.core);
    for (const GasRegion &r : w.s.regions) out = out || outside(r.gas);
    if (out) ++w.s.ledger.out_of_range_steps;
}

void ThermoWorld::split(const std::string &body,
                        const std::vector<std::pair<std::string, double>> &pieces) {
    Impl &w = *impl_;
    const std::size_t index = w.lumpOf(body);
    if (index == kNone || pieces.empty()) return;
    if (pieces.size() == 1 && pieces.front().first == body) return;
    double total = 0.0;
    for (const auto &[name, share] : pieces) {
        require(std::isfinite(share) && share >= 0.0, "a piece's share is not negative");
        total += share;
    }
    require(total > 0.0, "a split needs somewhere for the matter to go");
    Lump parent = std::move(w.s.lumps[index]);
    w.s.lumps.erase(w.s.lumps.begin() + static_cast<std::ptrdiff_t>(index));
    double left = 1.0;
    for (std::size_t k = 0; k < pieces.size(); ++k) {
        const double share = pieces[k].second / total;
        // The last piece takes whatever is left, so nothing is lost to rounding
        // and nothing is made by it.
        const bool last = k + 1 == pieces.size();
        const double of_remaining = last ? 1.0 : (left > 0.0 ? std::min(1.0, share / left) : 1.0);
        Lump piece = parent;
        piece.body = pieces[k].first;
        piece.surface = takeShare(parent.surface, of_remaining);
        piece.core = takeShare(parent.core, of_remaining);
        piece.layer_fuel_kg = parent.layer_fuel_kg * share;
        piece.area_m2 = parent.area_m2 * std::cbrt(share * share);
        piece.exposed_area_m2 = piece.area_m2;
        piece.volume_m3 = parent.volume_m3 * share;
        piece.mirrored_mass_kg = -1.0;   // the host has not set this mass yet
        left -= share;
        const std::size_t existing = w.lumpOf(piece.body);
        if (existing != kNone) {
            pour(w.s.lumps[existing].surface, piece.surface);
            pour(w.s.lumps[existing].core, piece.core);
            w.s.lumps[existing].mirrored_mass_kg = -1.0;
        } else {
            w.s.lumps.push_back(std::move(piece));
        }
    }
    // What was attached to the body goes with its largest piece: a heater under
    // a log keeps heating what is left of the log, and a gas pushing on a piston
    // keeps pushing on it. Left naming a body that is gone, a heater stopped
    // heating and a gas stopped pushing the moment a blade parted what they were
    // on. Neither says WHERE on the body it acts, so which piece takes it is a
    // declared choice, and it is the largest.
    std::size_t largest = 0;
    for (std::size_t k = 1; k < pieces.size(); ++k)
        if (pieces[k].second > pieces[largest].second) largest = k;
    const std::string heir = pieces[largest].first;
    for (Heater &heater : w.s.heaters)
        if (heater.what.target == body) heater.what.target = heir;
    for (GasRegion &region : w.s.regions) {
        if (!region.piston) continue;
        if (region.piston->body == body) region.piston->body = heir;
        if (region.piston->container == body) region.piston->container = heir;
    }
    w.couple();
}

void ThermoWorld::remove(const std::string &body) {
    Impl &w = *impl_;
    const std::size_t index = w.lumpOf(body);
    if (index == kNone) return;
    w.leave(w.s.lumps[index]);
    w.s.lumps.erase(w.s.lumps.begin() + static_cast<std::ptrdiff_t>(index));
    w.s.heaters.erase(std::remove_if(w.s.heaters.begin(), w.s.heaters.end(),
                                     [&](const Heater &h) { return h.what.target == body; }),
                      w.s.heaters.end());
    w.couple();
}

const ThermoState &ThermoWorld::state() const { return impl_->s; }

void ThermoWorld::restore(const ThermoState &state) { impl_->s = state; }

double ThermoWorld::timeS() const { return impl_->s.time_s; }

bool ThermoWorld::active() const {
    const ThermoState &s = impl_->s;
    return !s.lumps.empty() || !s.regions.empty() || !s.heaters.empty();
}

bool ThermoWorld::holds(const std::string &body) const { return impl_->lumpOf(body) != kNone; }

std::vector<BodyHeat> ThermoWorld::bodies() const {
    const Impl &w = *impl_;
    std::vector<BodyHeat> out;
    out.reserve(w.s.lumps.size());
    for (const Lump &l : w.s.lumps) {
        BodyHeat heat;
        heat.body = l.body;
        heat.material = l.material;
        heat.temperature_k = w.temperature(l.surface);
        heat.core_temperature_k = massKg(l.core) > 0.0 ? w.temperature(l.core) : heat.temperature_k;
        heat.mass_kg = Impl::lumpMass(l);
        heat.fuel_kg = w.fuelIn(l.surface) + w.fuelIn(l.core);
        heat.heat_release_w = l.heat_release_w;
        heat.fuel_use_kg_s = l.fuel_use_kg_s;
        if (l.fuel_use_kg_s > 1.0e-9) heat.remaining_s = heat.fuel_kg / l.fuel_use_kg_s;
        heat.heater_w = l.heater_w;
        heat.gained_w = l.gained_w;
        heat.lost_w = l.lost_w;
        heat.reacting = l.fuel_use_kg_s > 0.0 || std::abs(l.heat_release_w) > 1.0;
        heat.declared = l.declared;
        for (std::size_t i = 0; i < w.model.size(); ++i) {
            const double kg = l.surface.kg[i] + l.core.kg[i];
            if (kg > 1.0e-9) heat.contents_kg.emplace_back(w.model[i].id, kg);
        }
        out.push_back(std::move(heat));
    }
    return out;
}

std::vector<RegionState> ThermoWorld::regions() const {
    const Impl &w = *impl_;
    std::vector<RegionState> out;
    for (const GasRegion &r : w.s.regions) {
        RegionState state;
        state.name = r.name;
        state.temperature_k = w.temperature(r.gas);
        state.volume_m3 = r.volume_m3;
        state.pressure_pa = pressurePa(w.model, r.gas, r.volume_m3);
        state.mass_kg = massKg(r.gas);
        state.moles = gasMoles(w.model, r.gas);
        for (std::size_t i = 0; i < w.model.size(); ++i)
            if (r.gas.kg[i] > 1.0e-12) state.contents_kg.emplace_back(w.model[i].id, r.gas.kg[i]);
        if (r.piston) {
            state.piston = r.piston->body;
            state.axis = r.piston->axis;
            state.base_m = r.piston->base_m;
            state.area_m2 = r.piston->area_m2;
            state.height_m = r.volume_m3 / r.piston->area_m2;
            state.stroke_m = r.piston->stroke_m;
            state.force_n = (state.pressure_pa - w.ambient.pressure_pa) * r.piston->area_m2;
            state.work_to_bodies_j = r.piston->work_to_bodies_j;
            state.work_to_atmosphere_j = r.piston->work_to_atmosphere_j;
        }
        state.heater_w = r.heater_w;
        state.wall_loss_w = r.wall_loss_w;
        state.vent_open = r.vent_open && r.vent_area_m2 > 0.0;
        state.vent_flow_kg_s = r.vent_flow_kg_s;
        out.push_back(std::move(state));
    }
    return out;
}

Ledger ThermoWorld::ledger() const {
    Ledger ledger = impl_->s.ledger;
    impl_->measure(ledger);
    if (!impl_->s.opened) {
        ledger.initial_j = ledger.storedJ();
        ledger.initial_mass_kg = ledger.mass_kg;
    }
    return ledger;
}

std::vector<std::pair<std::string, double>> ThermoWorld::massesToMirror(double relative) {
    std::vector<std::pair<std::string, double>> out;
    for (Lump &l : impl_->s.lumps) {
        const double mass = Impl::lumpMass(l);
        if (l.mirrored_mass_kg >= 0.0 && std::abs(mass - l.mirrored_mass_kg) <= relative * mass) continue;
        if (!(mass > 0.0)) continue;
        l.mirrored_mass_kg = mass;
        out.emplace_back(l.body, mass);
    }
    return out;
}

std::vector<std::string> ThermoWorld::limitations() {
    return {
        "Constant heat capacities over the model's declared range (150-3000 K); no dissociation",
        "Every body is one lump, or one surface layer over one core when it conducts too poorly "
        "to be one temperature; there is no temperature field inside a body",
        "Heat paths come from bounding boxes as bodies are turned now: contact conduction where "
        "boxes meet face to face, radiation between separated bodies by a point-source view "
        "factor (Cauchy mean projected area), capped when they are close",
        "The surroundings are an infinite reservoir at a fixed temperature, pressure and "
        "composition; there is no airflow, plume, smoke or flame gas phase",
        "Gas regions are zero-dimensional ideal-gas mixtures with constant heat capacities",
        "Pressure boundaries apply a force held constant over each accepted step (the pressure "
        "at its start); the gas is charged exactly that force times the displacement, so the "
        "work always agrees and the time discretisation is first order",
        "Openings are incompressible orifices; choked flow is not modelled",
        "The wood model is a DECLARED SIMPLIFIED model with demonstration parameters: not "
        "validated against ventilation, moisture, geometry or heat-loss variations",
        "Bodies do not shrink as they burn: mass and composition change, shape does not",
        "Temperature does not yet change any mechanical property or cause any failure",
    };
}

} // namespace banjo::thermo
