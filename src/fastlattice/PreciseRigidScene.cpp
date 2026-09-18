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
        b.name = j.at("name").get<std::string>();
        require(!b.name.empty() && b.name.size() <= 120 && names.insert(b.name).second,
                "precise rigid names must be nonempty and unique (at most 120 bytes)");
        for (unsigned char c : b.name) require(c >= 32 && c != 127, "precise rigid name contains control characters");
        b.material = material(j.at("material"));
        b.initial.center_of_mass_world_m = vector(j.at("position_m"), 190);
        b.initial.linear_velocity_m_s = vector(j.value("velocity_m_s", json{0, 0, 0}), 20);
        b.initial.angular_velocity_rad_s = vector(j.value("spin_rad_s", json{0, 0, 0}), 20);
        const json q = j.value("orientation_wxyz", json{1, 0, 0, 0});
        require(q.is_array() && q.size() == 4, "precise rigid orientation needs w,x,y,z");
        const Quat rotation{number(q[0], -1, 1), number(q[1], -1, 1), number(q[2], -1, 1), number(q[3], -1, 1)};
        require(std::abs(rotation.w*rotation.w + rotation.x*rotation.x + rotation.y*rotation.y + rotation.z*rotation.z - 1) <= 1e-9,
                "precise rigid quaternion must already be normalized");
        b.initial.orientation_world = rotation;
        if (j.contains("color_rgba")) {
            require(j["color_rgba"].is_number_integer(), "precise rigid color must be an integer");
            const auto color = j["color_rgba"].get<std::int64_t>();
            require(color >= 0 && color <= 0xffffffffLL, "precise rigid color outside RGBA bounds");
            b.color_rgba = static_cast<std::uint32_t>(color);
        }
        const auto &parts = j.at("parts");
        require(parts.is_array() && !parts.empty() && parts.size() <= 64, "precise compound needs 1..64 boxes");
        shape_count += parts.size();
        require(shape_count <= 256, "precise rigid scene exceeds 256 collision boxes");
        const double density = makeReferenceMaterial(b.material).density_kg_m3;
        Vec3 weighted{}, lo{1e9,1e9,1e9}, hi{-1e9,-1e9,-1e9};
        for (const auto &p : parts) {
            fields(p, {"dimensions_m", "center_local_m"});
            RigidCompoundPart part;
            part.geometry.kind = PrimitiveKind::Box;
            part.geometry.dimensions_m = vector(p.at("dimensions_m"), 6);
            const Vec3 d = part.geometry.dimensions_m;
            require(std::min({d.x,d.y,d.z}) >= .001, "precise box dimensions must be 1..6000 mm");
            part.center_local_m = vector(p.at("center_local_m"), 6);
            const Vec3 c = part.center_local_m;
            const double mass = density * part.geometry.volume();
            b.mass_kg += mass;
            weighted = weighted + mass*c;
            const Mat3 own = part.geometry.inertia(mass);
            const double v[3]{c.x,c.y,c.z};
            for (unsigned a=0;a<3;++a) for (unsigned k=0;k<3;++k)
                b.inertia.m[a][k] += own.m[a][k] + mass*((a==k ? dot(c,c) : 0)-v[a]*v[k]);
            lo = {std::min(lo.x,c.x-d.x/2),std::min(lo.y,c.y-d.y/2),std::min(lo.z,c.z-d.z/2)};
            hi = {std::max(hi.x,c.x+d.x/2),std::max(hi.y,c.y+d.y/2),std::max(hi.z,c.z+d.z/2)};
            b.parts.push_back(part);
        }
        require(length(weighted/b.mass_kg) <= 1e-9, "precise compound coordinates must be about its material-derived centre of mass");
        std::vector<std::vector<unsigned>> neighbors(b.parts.size());
        for (unsigned a=0;a<b.parts.size();++a) for (unsigned k=0;k<a;++k) {
            const auto &p = b.parts[a]; const auto &other = b.parts[k];
            const Vec3 h = (p.geometry.dimensions_m+other.geometry.dimensions_m)/2;
            const Vec3 d = p.center_local_m-other.center_local_m;
            const double overlap[3]{h.x-std::abs(d.x),h.y-std::abs(d.y),h.z-std::abs(d.z)};
            require(!(overlap[0]>1e-10 && overlap[1]>1e-10 && overlap[2]>1e-10), "precise compound boxes overlap; an exact solid union is required");
            unsigned positive = 0; bool touch = true;
            for (double o : overlap) { positive += o>1e-10; touch = touch && o>=-1e-10; }
            if (touch && positive>=2) { neighbors[a].push_back(k); neighbors[k].push_back(a); }
        }
        std::vector<bool> seen(b.parts.size()); std::vector<unsigned> pending{0}; seen[0]=true;
        for (unsigned i=0;i<pending.size();++i) for (unsigned other : neighbors[pending[i]])
            if (!seen[other]) { seen[other]=true; pending.push_back(other); }
        require(pending.size()==b.parts.size(), "precise compound must be face connected; separate parts need joints");
        b.dimensions_m = hi-lo;
        b.definition_json = json{{"name",b.name},{"material",materialPresetName(b.material)},
            {"parts",parts},{"position_m",vec(b.initial.center_of_mass_world_m)},
            {"orientation_wxyz",q},{"velocity_m_s",vec(b.initial.linear_velocity_m_s)},
            {"spin_rad_s",vec(b.initial.angular_velocity_rad_s)},{"color_rgba",b.color_rgba}}.dump();
        bodies.push_back(std::move(b));
    }
    return bodies;
}
} // namespace banjo::fastlattice
