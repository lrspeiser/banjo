#include "fastlattice/PreciseRigidScene.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>

namespace banjo::fastlattice {
namespace {
using json = nlohmann::json;
void require(bool ok, const char *message) {
    if (!ok) throw std::invalid_argument(message);
}
void fields(const json &j, std::initializer_list<const char *> allowed) {
    require(j.is_object(), "precise rigid entry must be an object");
    for (auto it = j.begin(); it != j.end(); ++it) {
        bool known = false;
        for (const char *key : allowed) known |= it.key() == key;
        require(known, "unknown precise rigid field");
    }
}
double number(const json &j, double low, double high) {
    require(j.is_number(), "precise rigid values must be SI numbers");
    const double v = j.get<double>();
    require(std::isfinite(v) && v >= low && v <= high, "precise rigid SI value outside supported bounds");
    return v;
}
Vec3 vector(const json &j, double limit) {
    require(j.is_array() && j.size() == 3, "precise rigid vector needs three SI numbers");
    return {number(j[0], -limit, limit), number(j[1], -limit, limit), number(j[2], -limit, limit)};
}
json vec(Vec3 v) { return {v.x, v.y, v.z}; }
MaterialPreset material(const json &j) {
    for (auto p : {MaterialPreset::Glass, MaterialPreset::Oak, MaterialPreset::Iron, MaterialPreset::Concrete})
        if (j == std::string(materialPresetName(p))) return p;
    throw std::invalid_argument("unsupported precise rigid material");
}
Quat unitQuaternion(const json &q) {
    require(q.is_array() && q.size() == 4, "precise rigid orientation needs w,x,y,z");
    const Quat r{number(q[0], -1, 1), number(q[1], -1, 1), number(q[2], -1, 1), number(q[3], -1, 1)};
    require(std::abs(r.w*r.w + r.x*r.x + r.y*r.y + r.z*r.z - 1) <= 1e-9,
            "precise rigid quaternion must already be normalized");
    return r;
}
Quat conjugate(Quat q) { return {q.w, -q.x, -q.y, -q.z}; }

// A part as it sits in the body's frame, for measuring: what it is, which way
// back to its own frame, what it is made of, and the box round it.
struct Solid {
    const RigidCompoundPart *part{};
    Quat inverse;
    double density{};
    Vec3 lo, hi;
    [[nodiscard]] bool inside(Vec3 p) const {
        return part->geometry.contains(inverse.rotate(p - part->center_local_m));
    }
    [[nodiscard]] bool around(Vec3 p) const {
        return p.x >= lo.x && p.x <= hi.x && p.y >= lo.y && p.y <= hi.y && p.z >= lo.z && p.z <= hi.z;
    }
};

// Mass, volume, first moment, and second moment about the frame's origin.
struct Moments {
    double mass{}, volume{};
    Vec3 first{};
    Mat3 second{};
    void add(double m, Vec3 at, const Mat3 &own, double v) {
        mass += m;
        volume += v;
        first = first + m * at;
        const double c[3]{at.x, at.y, at.z};
        for (unsigned a = 0; a < 3; ++a)
            for (unsigned k = 0; k < 3; ++k)
                second.m[a][k] += own.m[a][k] + m * ((a == k ? dot(at, at) : 0) - c[a] * c[k]);
    }
};

// Where a part runs into one listed before it, that space is the earlier
// part's: take it back out of the later part's share. Each overlap is measured
// on a grid fine for that overlap -- 24 cells across its thinnest side, never
// finer than 0.2 mm -- so an axle's end inside a wheel's hub is resolved to a
// small fraction of its 20-odd cubic centimetres, and parts that only touch
// (as every box compound so far does) cost nothing and change nothing.
void takeBackWhatEarlierPartsClaim(const std::vector<Solid> &solids, Moments &moments) {
    constexpr double kCellsAcross = 24.0, kFinestM = 0.0002, kPairBudget = 2.0e6, kBodyBudget = 2.0e7;
    double spent = 0;
    for (std::size_t j = 1; j < solids.size(); ++j) {
        const Solid &later = solids[j];
        for (std::size_t i = 0; i < j; ++i) {
            const Solid &earlier = solids[i];
            const Vec3 lo{std::max(later.lo.x, earlier.lo.x), std::max(later.lo.y, earlier.lo.y),
                          std::max(later.lo.z, earlier.lo.z)};
            const Vec3 hi{std::min(later.hi.x, earlier.hi.x), std::min(later.hi.y, earlier.hi.y),
                          std::min(later.hi.z, earlier.hi.z)};
            const Vec3 span = hi - lo;
            if (!(span.x > 1e-9 && span.y > 1e-9 && span.z > 1e-9)) continue;
            double h = std::max(kFinestM, std::min({span.x, span.y, span.z}) / kCellsAcross);
            const auto cells = [&](double side) { return std::max(1.0, std::ceil(side / h)); };
            double count = cells(span.x) * cells(span.y) * cells(span.z);
            if (count > kPairBudget) {
                h *= std::cbrt(count / kPairBudget);
                count = cells(span.x) * cells(span.y) * cells(span.z);
            }
            spent += count;
            require(spent <= kBodyBudget, "precise compound overlaps are too large to measure; let its parts meet rather than fill each other");
            const int nx = int(cells(span.x)), ny = int(cells(span.y)), nz = int(cells(span.z));
            const Vec3 step{span.x / nx, span.y / ny, span.z / nz};
            const double dv = step.x * step.y * step.z, dm = later.density * dv;
            // Each sample is a small box of matter, with a turn of its own:
            // leave it out and a grid of point masses under-counts the second
            // moment by a cell's width squared.
            Mat3 cell;
            cell.m[0][0] = -dm * (step.y * step.y + step.z * step.z) / 12;
            cell.m[1][1] = -dm * (step.x * step.x + step.z * step.z) / 12;
            cell.m[2][2] = -dm * (step.x * step.x + step.y * step.y) / 12;
            for (int a = 0; a < nx; ++a)
                for (int b = 0; b < ny; ++b)
                    for (int c = 0; c < nz; ++c) {
                        const Vec3 p{lo.x + (a + 0.5) * step.x, lo.y + (b + 0.5) * step.y, lo.z + (c + 0.5) * step.z};
                        if (!later.inside(p) || !earlier.inside(p)) continue;
                        // A point inside a part listed before this earlier one
                        // too is that part's, and is taken back on its turn.
                        bool before = false;
                        for (std::size_t k = 0; k < i && !before; ++k)
                            before = solids[k].around(p) && solids[k].inside(p);
                        if (!before) moments.add(-dm, p, cell, -dv);
                    }
        }
    }
}
}

std::vector<PreciseRigidBody> readPreciseRigidScene(const std::string &text) {
    if (text.empty()) return {};
    const json source = json::parse(text);
    require(source.is_array() && source.size() <= 32, "precise rigid scene allows at most 32 bodies");
    std::vector<PreciseRigidBody> bodies;
    std::set<std::string> names;
    std::size_t shape_count = 0;
    for (const auto &j : source) {
        fields(j, {"name", "material", "parts", "position_m", "orientation_wxyz", "velocity_m_s", "spin_rad_s", "color_rgba"});
        PreciseRigidBody b;
        require(j.contains("name") && j["name"].is_string(), "precise rigid body needs a name");
        b.name = j["name"].get<std::string>();
        require(!b.name.empty() && b.name.size() <= 120 && names.insert(b.name).second,
                "precise rigid names must be nonempty and unique (at most 120 bytes)");
        for (unsigned char c : b.name) require(c >= 32 && c != 127, "precise rigid name contains control characters");
        require(j.contains("material") && j.contains("position_m") && j.contains("parts"),
                "precise rigid body needs material, position_m and parts");
        b.material = material(j["material"]);
        b.made_of = makeReferenceMaterial(b.material);
        const Vec3 origin = vector(j["position_m"], 190);
        b.initial.linear_velocity_m_s = vector(j.value("velocity_m_s", json{0, 0, 0}), 20);
        b.initial.angular_velocity_rad_s = vector(j.value("spin_rad_s", json{0, 0, 0}), 20);
        const json q = j.value("orientation_wxyz", json{1, 0, 0, 0});
        const Quat rotation = unitQuaternion(q);
        b.initial.orientation_world = rotation;
        if (j.contains("color_rgba")) {
            require(j["color_rgba"].is_number_integer(), "precise rigid color must be an integer");
            const auto color = j["color_rgba"].get<std::int64_t>();
            require(color >= 0 && color <= 0xffffffffLL, "precise rigid color outside RGBA bounds");
            b.color_rgba = static_cast<std::uint32_t>(color);
        }
        const auto &parts = j["parts"];
        require(parts.is_array() && !parts.empty() && parts.size() <= 64, "precise compound needs 1..64 parts");
        shape_count += parts.size();
        require(shape_count <= 256, "precise rigid scene exceeds 256 collision parts");
        for (const auto &p : parts) {
            fields(p, {"shape", "dimensions_m", "center_local_m", "rotation_wxyz", "material", "name"});
            require(p.contains("dimensions_m") && p.contains("center_local_m"),
                    "precise part needs dimensions_m and center_local_m");
            RigidCompoundPart part;
            const json shape = p.value("shape", json("box"));
            require(shape == "box" || shape == "cylinder", "precise part shape must be box or cylinder");
            part.geometry.kind = shape == "cylinder" ? PrimitiveKind::Cylinder : PrimitiveKind::Box;
            part.geometry.dimensions_m = vector(p["dimensions_m"], 6);
            const Vec3 d = part.geometry.dimensions_m;
            require(std::min({d.x, d.y, d.z}) >= .001, "precise part dimensions must be 1..6000 mm");
            if (part.geometry.kind == PrimitiveKind::Cylinder)
                require(std::abs(d.x - d.z) <= 1e-9 * std::max(1.0, d.x),
                        "a precise cylinder is sized [diameter, length, diameter] about its own y axis");
            part.center_local_m = vector(p["center_local_m"], 6);
            part.rotation_local = unitQuaternion(p.value("rotation_wxyz", json{1, 0, 0, 0}));
            const MaterialPreset made = p.contains("material") ? material(p["material"]) : b.material;
            if (made != b.material) part.material = makeReferenceMaterial(made);
            std::string part_name;
            if (p.contains("name")) {
                require(p["name"].is_string(), "precise part name must be a string");
                part_name = p["name"].get<std::string>();
                require(!part_name.empty() && part_name.size() <= 80, "precise part names are 1..80 bytes");
                for (unsigned char c : part_name) require(c >= 32 && c != 127, "precise part name contains control characters");
            }
            b.parts.push_back(part);
            b.part_materials.push_back(made);
            b.part_names.push_back(std::move(part_name));
        }

        // Measured from each part's own material, and the union counted once.
        std::vector<Solid> solids;
        Moments moments;
        for (std::size_t i = 0; i < b.parts.size(); ++i) {
            const RigidCompoundPart &part = b.parts[i];
            const double density = makeReferenceMaterial(b.part_materials[i]).density_kg_m3;
            const double volume = part.geometry.volume(), mass = density * volume;
            moments.add(mass, part.center_local_m, rotateInertia(part.geometry.inertia(mass), part.rotation_local), volume);
            Solid solid{&part, conjugate(part.rotation_local), density, {}, {}};
            const Vec3 reach{part.geometry.extent({1, 0, 0}, part.rotation_local),
                             part.geometry.extent({0, 1, 0}, part.rotation_local),
                             part.geometry.extent({0, 0, 1}, part.rotation_local)};
            solid.lo = part.center_local_m - reach;
            solid.hi = part.center_local_m + reach;
            solids.push_back(solid);
        }
        takeBackWhatEarlierPartsClaim(solids, moments);
        require(moments.mass > 0 && moments.volume > 0, "precise compound has no matter");

        // One rigid thing: every part meets another, touching or within 1 mm.
        // Two things that do not meet are two bodies, and need a joint.
        constexpr double kMeetM = 0.001;
        std::vector<std::vector<unsigned>> neighbors(b.parts.size());
        for (unsigned a = 0; a < b.parts.size(); ++a)
            for (unsigned k = 0; k < a; ++k) {
                const Solid &one = solids[a], &two = solids[k];
                if (one.lo.x > two.hi.x + kMeetM || two.lo.x > one.hi.x + kMeetM ||
                    one.lo.y > two.hi.y + kMeetM || two.lo.y > one.hi.y + kMeetM ||
                    one.lo.z > two.hi.z + kMeetM || two.lo.z > one.hi.z + kMeetM)
                    continue;
                if (JoltWorld::partsWithin(b.parts[a], b.parts[k], kMeetM)) {
                    neighbors[a].push_back(k);
                    neighbors[k].push_back(a);
                }
            }
        std::vector<bool> seen(b.parts.size()); std::vector<unsigned> pending{0}; seen[0] = true;
        for (unsigned i = 0; i < pending.size(); ++i)
            for (unsigned other : neighbors[pending[i]])
                if (!seen[other]) { seen[other] = true; pending.push_back(other); }
        require(pending.size() == b.parts.size(), "precise compound parts must meet; separate parts need joints");

        // Re-centred on its centre of mass, which is where the body stands.
        const Vec3 centre = (1.0 / moments.mass) * moments.first;
        b.mass_kg = moments.mass;
        b.volume_m3 = moments.volume;
        const double c[3]{centre.x, centre.y, centre.z};
        for (unsigned a = 0; a < 3; ++a)
            for (unsigned k = 0; k < 3; ++k)
                b.inertia.m[a][k] = moments.second.m[a][k] - moments.mass * ((a == k ? dot(centre, centre) : 0) - c[a] * c[k]);
        Vec3 lo{1e9, 1e9, 1e9}, hi{-1e9, -1e9, -1e9};
        for (const Solid &s : solids) {
            lo = {std::min(lo.x, s.lo.x), std::min(lo.y, s.lo.y), std::min(lo.z, s.lo.z)};
            hi = {std::max(hi.x, s.hi.x), std::max(hi.y, s.hi.y), std::max(hi.z, s.hi.z)};
        }
        b.dimensions_m = hi - lo;
        for (RigidCompoundPart &part : b.parts) part.center_local_m = part.center_local_m - centre;
        b.initial.center_of_mass_world_m = origin + rotation.rotate(centre);
        // As given, so reading it again makes the same body.
        b.definition_json = json{{"name", b.name}, {"material", materialPresetName(b.material)},
            {"parts", parts}, {"position_m", vec(origin)},
            {"orientation_wxyz", q}, {"velocity_m_s", vec(b.initial.linear_velocity_m_s)},
            {"spin_rad_s", vec(b.initial.angular_velocity_rad_s)}, {"color_rgba", b.color_rgba}}.dump();
        bodies.push_back(std::move(b));
    }
    return bodies;
}
} // namespace banjo::fastlattice
