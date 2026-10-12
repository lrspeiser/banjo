#include "water/FallingWater.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <unordered_map>

namespace banjo::water {
namespace {

// Wendland C2 in 3D, support kSupport, and minus its radial derivative: the
// kernel and gradient the fluid wheel uses.
double kernel(double r) {
    const double h = FallingWater::kSupport, q = r / h;
    return q >= 1.0 ? 0.0 : 21.0 / (2.0 * std::numbers::pi * h * h * h) * std::pow(1.0 - q, 4) * (1.0 + 4.0 * q);
}
double minusGradient(double r) {
    const double h = FallingWater::kSupport, q = r / h;
    return q >= 1.0 ? 0.0 : 210.0 / (std::numbers::pi * h * h * h * h) * q * std::pow(1.0 - q, 3);
}
double pressure(double rho) {
    const double c = FallingWater::kSoundSpeed;
    return c * c * std::max(0.0, rho - FallingWater::kDensity);
}

// Parcels by the cube of side kSupport they are in, so each looks only at
// the 27 cubes around its own for neighbours.
struct Cells {
    std::unordered_map<std::int64_t, std::vector<std::size_t>> at;
    static std::int64_t key(int i, int j, int k) {
        return (static_cast<std::int64_t>(i) * 73856093) ^ (static_cast<std::int64_t>(j) * 19349663) ^
               (static_cast<std::int64_t>(k) * 83492791);
    }
    static int cell(double x) { return static_cast<int>(std::floor(x / FallingWater::kSupport)); }
    explicit Cells(const std::vector<Parcel> &parcels) {
        for (std::size_t i = 0; i < parcels.size(); ++i) {
            const Vec3 &x = parcels[i].x_m;
            at[key(cell(x.x), cell(x.y), cell(x.z))].push_back(i);
        }
    }
    template <class F> void around(const Vec3 &x, F &&f) const {
        const int ci = cell(x.x), cj = cell(x.y), ck = cell(x.z);
        for (int i = ci - 1; i <= ci + 1; ++i)
            for (int j = cj - 1; j <= cj + 1; ++j)
                for (int k = ck - 1; k <= ck + 1; ++k) {
                    const auto found = at.find(key(i, j, k));
                    if (found == at.end()) continue;
                    for (const std::size_t other : found->second) f(other);
                }
    }
};

}  // namespace

void FallingWater::addSpout(const Spout &spout) {
    const double d = length(spout.direction);
    if (spout.name.empty()) throw std::invalid_argument("a spout needs a name");
    if (!(d > 0.0) || !std::isfinite(d)) throw std::invalid_argument("spout '" + spout.name + "' needs a direction");
    if (!(spout.speed_m_s >= 0.0) || !(spout.speed_m_s <= kMaxSpeed))
        throw std::invalid_argument("spout '" + spout.name + "' speed must be 0 to 30 m/s");
    if (!(spout.discharge_m3_s >= 0.0) || !(spout.discharge_m3_s <= 0.05) ||
        (spout.reservoir_area_m2==0 && spout.discharge_m3_s==0))
        throw std::invalid_argument("spout '" + spout.name + "' discharge must be above 0 and at most 0.05 m^3/s");
    if (!(spout.from_s >= 0.0) || !(spout.until_s > spout.from_s))
        throw std::invalid_argument("spout '" + spout.name + "' must stop after it starts");
    if (!(spout.initial_volume_m3 >= 0.0))
        throw std::invalid_argument("spout '" + spout.name + "' volume must be nonnegative");
    if (!std::isfinite(spout.opening_fraction) || spout.opening_fraction<0 || spout.opening_fraction>1)
        throw std::invalid_argument("spout opening must be between zero and one");
    if (spout.reservoir_area_m2 != 0) {
        if (spout.speed_m_s!=0 || spout.discharge_m3_s!=0)
            throw std::invalid_argument("gravity reservoir speed and discharge are derived from its head and opening");
        if (!std::isfinite(spout.initial_volume_m3) || !std::isfinite(spout.reservoir_area_m2) ||
            spout.reservoir_area_m2<=0 || !std::isfinite(spout.outlet_area_m2) || spout.outlet_area_m2<=0 ||
            spout.outlet_area_m2>spout.reservoir_area_m2 || !std::isfinite(spout.head_offset_m) || spout.head_offset_m<0 ||
            !std::isfinite(spout.contraction_coefficient) || spout.contraction_coefficient<=0 || spout.contraction_coefficient>1 ||
            std::sqrt(2*9.81*head(spout,spout.initial_volume_m3))>kMaxSpeed ||
            spout.contraction_coefficient*spout.outlet_area_m2*std::sqrt(2*9.81*head(spout,spout.initial_volume_m3))>.05)
            throw std::invalid_argument("a gravity reservoir needs finite volume, positive bounded areas and valid head");
        if (spout.reservoir_floor_m && (!std::isfinite(spout.reservoir_floor_m->x) || !std::isfinite(spout.reservoir_floor_m->y) ||
            !std::isfinite(spout.reservoir_floor_m->z) || std::abs(spout.reservoir_floor_m->y-spout.at_m.y-spout.head_offset_m)>1e-9))
            throw std::invalid_argument("reservoir floor must be finite and agree with the outlet head offset");
    } else if (spout.outlet_area_m2 != 0 || spout.head_offset_m != 0) {
        throw std::invalid_argument("an outlet area and head offset need a gravity reservoir");
    }
    if (spout.receiver_bounds_m) {
        const auto &b=*spout.receiver_bounds_m;
        if (!std::all_of(b.begin(),b.end(),[](double x){return std::isfinite(x);}) || !(b[0]<b[1]) || !(b[2]<b[3]))
            throw std::invalid_argument("receiver bounds are xmin,xmax,zmin,zmax");
    }
    for (const Spout &s : spouts_)
        if (s.name == spout.name) throw std::invalid_argument("two spouts are called '" + spout.name + "'");
    Spout kept = spout;
    kept.direction = spout.direction / d;
    spouts_.push_back(kept);
    owed_m3_.push_back(0.0);
    accounts_.push_back(SpoutAccount{.remaining_m3 = kept.initial_volume_m3});
}

bool FallingWater::setValve(const std::string &name, bool open) {
    for (Spout &s : spouts_) if (s.name == name) { s.valve_open = open; return true; }
    return false;
}

bool FallingWater::setOpening(const std::string &name, double fraction) {
    if (!std::isfinite(fraction) || fraction<0 || fraction>1) return false;
    for (Spout &s:spouts_) if (s.name==name && s.reservoir_area_m2>0) {s.opening_fraction=fraction;return true;}
    return false;
}
double FallingWater::head(const Spout &s, double volume) {
    return s.reservoir_area_m2>0?s.head_offset_m+std::max(0.0,volume)/s.reservoir_area_m2:0.0;
}
double FallingWater::rate(const Spout &s, double volume) {
    if (!s.valve_open || volume+1e-15<kVolume) return 0;
    return s.reservoir_area_m2>0?s.contraction_coefficient*s.outlet_area_m2*s.opening_fraction*std::sqrt(2*9.81*head(s,volume)):s.discharge_m3_s;
}

double FallingWater::residual() const {
    return ledger_.poured_m3 - ledger_.landed_m3 - ledger_.ran_off_m3 - inFlight();
}

double FallingWater::energyResidual() const {
    double flight = 0;
    for (const Parcel &q : parcels_) flight += kMass * (0.5 * lengthSquared(q.v_m_s) + 9.81*q.x_m.y);
    return ledger_.source_energy_j + ledger_.pressure_viscous_work_j + ledger_.numerical_correction_j
        - ledger_.body_work_j - ledger_.contact_loss_j - ledger_.receiver_energy_j - ledger_.runoff_energy_j - flight;
}
Vec3 FallingWater::momentumResidual() const {
    Vec3 flight{};
    for (const Parcel &q : parcels_) flight += q.v_m_s * kMass;
    return ledger_.source_impulse_n_s + ledger_.gravity_impulse_n_s - ledger_.body_impulse_n_s
        - ledger_.receiver_impulse_n_s - ledger_.runoff_impulse_n_s - flight;
}

FallingWater::Plan FallingWater::plan(double time_s, double dt_s, const SurfacesNear &near,
                                      const LandingHeight &landing, double floor_y_m) const {
    if (!(dt_s > 0.0)) throw std::invalid_argument("falling water needs a positive step");
    Plan p;
    p.parcels = parcels_;
    p.owed_m3 = owed_m3_;
    p.accounts = accounts_;
    p.ledger = ledger_;
    const Vec3 g{0.0, -9.81, 0.0};

    // Substeps short enough for the pressure waves between parcels: a quarter
    // of the kernel's support per sound crossing, as in the wheel experiment.
    double fastest = 0.0;
    for (const Parcel &q : p.parcels) fastest = std::max(fastest, length(q.v_m_s));
    for (const Spout &s : spouts_) fastest = std::max(fastest, s.reservoir_area_m2>0?
        std::sqrt(2*9.81*head(s,s.initial_volume_m3)):s.speed_m_s);
    fastest += 9.81 * dt_s;
    const int n = std::max(1, static_cast<int>(std::ceil(dt_s / (0.25 * kSupport / (kSoundSpeed + fastest)))));
    const double sub = dt_s / n;
    p.substeps = n;

    // The surfaces near each parcel, asked once for the whole step from the
    // bodies as they stand: as far as the parcel can travel in it. Within the
    // step each surface moves on with its own velocity.
    const double reach_extra = 2.0 * kRadius;
    std::vector<std::vector<NearSurface>> surfaces;
    surfaces.reserve(p.parcels.size());
    for (const Parcel &q : p.parcels)
        surfaces.push_back(near(q.x_m, kRadius, (length(q.v_m_s) + 9.81 * dt_s) * dt_s + reach_extra));

    // Per body: the impulse the parcels gave back, and its moment about the
    // world's origin, so a host can turn it into a force and a torque about
    // the body's own centre (torque = moment - centre x impulse).
    struct Pushed {
        Vec3 impulse{}, moment{};
    };
    std::unordered_map<std::uint64_t, Pushed> pushed;
    std::vector<std::uint64_t> pushed_order;

    for (int tick = 0; tick < n; ++tick) {
        const double t0 = time_s + tick * sub, t1 = t0 + sub;
        // Water leaving each spout in this substep, a parcel at a time, each
        // where water that left when it did would be by now.
        for (std::size_t k = 0; k < spouts_.size(); ++k) {
            const Spout &s = spouts_[k];
            const double before=p.accounts[k].remaining_m3;
            const double discharge=rate(s,before);
            const Vec3 floor=s.reservoir_floor_m.value_or(s.at_m+Vec3{0,s.head_offset_m,0});
            if (s.reservoir_area_m2>0) {
                p.accounts[k].reservoir_gravity_impulse_n_s+=g*(1000*before*sub);
                p.accounts[k].reservoir_gravity_moment_n_m_s+=cross(floor,g*(1000*before*sub));
            }
            if (!(discharge>0)) continue;
            const double open = std::max(t0, s.from_s), shut = std::min(t1, s.until_s);
            if (!(shut > open)) continue;
            p.owed_m3[k] = std::min(p.accounts[k].remaining_m3,
                                  p.owed_m3[k] + discharge * (shut - open));
            while (p.owed_m3[k] + 1e-15 >= kVolume && p.accounts[k].remaining_m3 + 1e-15 >= kVolume) {
                p.owed_m3[k] -= kVolume;
                auto &account = p.accounts[k];
                if (std::isfinite(account.remaining_m3)) account.remaining_m3 = std::max(0.0, account.remaining_m3 - kVolume);
                account.emitted_m3 += kVolume;
                // Mid-volume head pays exactly the decrease in the fixed
                // reservoir's gravitational energy for this accepted parcel.
                const double speed=s.reservoir_area_m2>0?
                    std::sqrt(2*9.81*head(s,account.remaining_m3+kVolume*.5)):s.speed_m_s;
                account.emitted_source_energy_j += kMass * (9.81 * s.at_m.y + 0.5 * speed * speed);
                account.emitted_momentum_n_s += s.direction * (kMass * speed);
                account.emitted_moment_n_m_s += cross(s.at_m,s.direction*(kMass*speed));
                const double age = std::min(shut - open, p.owed_m3[k] / discharge);
                if (s.reservoir_area_m2>0) {
                    account.reservoir_gravity_impulse_n_s-=g*(kMass*age);
                    account.reservoir_gravity_moment_n_m_s-=cross(floor,g*(kMass*age));
                }
                Parcel q;
                q.spout = static_cast<std::uint32_t>(k);
                q.v_m_s = s.direction * speed + g * age;
                q.x_m = s.at_m + s.direction * (speed * age) + g * (0.5 * age * age);
                p.ledger.source_energy_j += kMass * (9.81*s.at_m.y + 0.5*speed*speed);
                p.ledger.source_impulse_n_s += s.direction * (kMass*speed);
                p.ledger.gravity_impulse_n_s += g * (kMass*age);
                p.parcels.push_back(q);
                surfaces.push_back(near(q.x_m, kRadius, (speed + 9.81 * dt_s) * dt_s + reach_extra));
                p.ledger.poured_m3 += kVolume;
                ++p.ledger.parcels_poured;
                if (p.parcels.size() > kMaxParcels)
                    throw std::runtime_error("more falling water in the air than 2000 parcels; step refused");
            }
        }
        if (p.parcels.empty()) continue;

        // Density, then the pair forces: pressure and a viscous term, central
        // and equal and opposite, so the pairs move no momentum anywhere.
        const Cells cells(p.parcels);
        const std::size_t count = p.parcels.size();
        std::vector<double> density(count, kMass * kernel(0.0));
        for (std::size_t i = 0; i < count; ++i)
            cells.around(p.parcels[i].x_m, [&](std::size_t j) {
                if (j <= i) return;
                const double d = length(p.parcels[i].x_m - p.parcels[j].x_m);
                if (d >= kSupport) return;
                const double w = kMass * kernel(d);
                density[i] += w;
                density[j] += w;
            });
        std::vector<Vec3> force(count);
        for (std::size_t i = 0; i < count; ++i)
            cells.around(p.parcels[i].x_m, [&](std::size_t j) {
                if (j <= i) return;
                const Vec3 r = p.parcels[i].x_m - p.parcels[j].x_m;
                const double d = length(r);
                if (d < 1e-10 || d >= kSupport) return;
                const Vec3 axis = r / d, dv = p.parcels[i].v_m_s - p.parcels[j].v_m_s;
                const double grad = minusGradient(d);
                const double pr = kMass * kMass *
                                  (pressure(density[i]) / (density[i] * density[i]) +
                                   pressure(density[j]) / (density[j] * density[j])) * grad;
                const double visc = -10.0 * kViscosity * kMass * kMass / (density[i] * density[j]) * dot(dv, r) /
                                    (d * d + 0.01 * kSupport * kSupport) * grad;
                const Vec3 f = axis * (pr + visc);
                force[i] += f;
                force[j] -= f;
            });

        for (std::size_t i = 0; i < count; ++i) {
            Parcel &q = p.parcels[i];
            const Vec3 before_v = q.v_m_s;
            const double before_e = kMass*(0.5*lengthSquared(q.v_m_s) + 9.81*q.x_m.y);
            q.v_m_s += (force[i] / kMass + g) * sub;
            q.x_m += q.v_m_s * sub;
            p.ledger.gravity_impulse_n_s += g * (kMass*sub);
            // Pair-force work uses trapezoidal velocity. The remainder is
            // the explicit integrator's potential-energy correction, reported
            // separately rather than passed off as physical damping.
            const double pair_work = dot(force[i], (before_v+q.v_m_s)*0.5)*sub;
            p.ledger.pressure_viscous_work_j += pair_work;
            p.ledger.numerical_correction_j += kMass*(0.5*lengthSquared(q.v_m_s)+9.81*q.x_m.y)-before_e-pair_work;
            // Bodies: frictionless, and no bounce. Speed into a surface goes;
            // speed along it stays; the body gets the impulse back.
            for (const NearSurface &s : surfaces[i]) {
                if (!s.named) continue;   // the ground: joining the river is below
                const Vec3 point = s.point_m + s.velocity_m_s * (t1 - time_s);
                const double depth = kRadius - dot(q.x_m - point, s.normal);
                if (!(depth > 0.0)) continue;
                const double closing = dot(q.v_m_s - s.velocity_m_s, s.normal);
                if (closing < 0.0) {
                    const Vec3 impulse = s.normal * (-kMass * closing);
                    q.v_m_s += impulse / kMass;
                    p.ledger.contact_loss_j += 0.5 * kMass * closing * closing;
                    p.ledger.body_work_j -= dot(impulse, s.velocity_m_s);
                    p.ledger.body_impulse_n_s -= impulse;
                    auto [at, fresh] = pushed.try_emplace(s.body);
                    if (fresh) pushed_order.push_back(s.body);
                    at->second.impulse -= impulse;
                    at->second.moment -= cross(point, impulse);
                }
                q.x_m += s.normal * depth;
                p.ledger.numerical_correction_j += kMass*9.81*s.normal.y*depth;
            }
            if (!(length(q.v_m_s) <= kMaxSpeed) || !std::isfinite(lengthSquared(q.x_m)))
                throw std::runtime_error("a parcel of falling water left its admitted speed; step refused");
        }

        // Into the river where its underside reaches the water (or the dry
        // ground); off the world below the floor where there is no river.
        std::size_t kept = 0;
        for (std::size_t i = 0; i < p.parcels.size(); ++i) {
            const Parcel &q = p.parcels[i];
            const std::optional<double> height = landing(q.x_m.x, q.x_m.z);
            if (height && q.x_m.y - kRadius <= *height) {
                p.landings.push_back({q.x_m, q.v_m_s * kMass, kVolume});
                p.ledger.landed_m3 += kVolume;
                p.accounts[q.spout].landed_m3 += kVolume;
                const auto &bounds=spouts_[q.spout].receiver_bounds_m;
                if (!bounds || (q.x_m.x >= (*bounds)[0] && q.x_m.x <= (*bounds)[1] &&
                                q.x_m.z >= (*bounds)[2] && q.x_m.z <= (*bounds)[3]))
                    p.accounts[q.spout].received_m3 += kVolume;
                p.ledger.receiver_energy_j += kMass*(0.5*lengthSquared(q.v_m_s)+9.81*q.x_m.y);
                p.ledger.receiver_impulse_n_s += q.v_m_s*kMass;
                continue;
            }
            if (!height && q.x_m.y < floor_y_m) {
                p.ledger.ran_off_m3 += kVolume;
                p.accounts[q.spout].ran_off_m3 += kVolume;
                p.ledger.runoff_energy_j += kMass*(0.5*lengthSquared(q.v_m_s)+9.81*q.x_m.y);
                p.ledger.runoff_impulse_n_s += q.v_m_s*kMass;
                continue;
            }
            if (kept != i) {
                p.parcels[kept] = p.parcels[i];
                surfaces[kept] = std::move(surfaces[i]);
            }
            ++kept;
        }
        p.parcels.resize(kept);
        surfaces.resize(kept);
    }

    for (const std::uint64_t body : pushed_order) {
        const Pushed &s = pushed.at(body);
        p.pushes.push_back({body, s.impulse, s.moment});
    }
    return p;
}

void FallingWater::accept(Plan &&plan) {
    parcels_ = std::move(plan.parcels);
    owed_m3_ = std::move(plan.owed_m3);
    accounts_ = std::move(plan.accounts);
    ledger_ = plan.ledger;
}

}  // namespace banjo::water
