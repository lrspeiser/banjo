#include "water/CompoundWaterSurface.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace banjo::water {
namespace {
constexpr double pi = 3.14159265358979323846;
constexpr double eps = 1e-10;
using Polygon = std::vector<Vec3>;
struct Plane { Vec3 normal; double distance; };
struct Solid { std::vector<Plane> planes; std::vector<Polygon> faces; Vec3 low,high; };
Quat inverse(Quat q) { return {q.w, -q.x, -q.y, -q.z}; }

Polygon clipped(const Polygon &polygon, const Plane &plane, bool inside) {
    Polygon out;
    for (std::size_t k = 0; k < polygon.size(); ++k) {
        const Vec3 a = polygon[k], b = polygon[(k + 1) % polygon.size()];
        const double da = dot(plane.normal, a) - plane.distance;
        const double db = dot(plane.normal, b) - plane.distance;
        const bool ai = inside ? da <= eps : da > eps;
        const bool bi = inside ? db <= eps : db > eps;
        if (ai) out.push_back(a);
        if (ai != bi) out.push_back(a + (b - a) * (da / (da - db)));
    }
    return out;
}
Solid solid(const CompoundWaterPart &part, double patch_m) {
    Solid out;
    const auto d=part.geometry.dimensions_m;
    for (double x : {d.x,d.y,d.z}) if (!std::isfinite(x) || x<.001 || x>6)
        throw std::invalid_argument("compound water dimensions must be 1..6000 mm");
    for (double x : {part.center_local_m.x,part.center_local_m.y,part.center_local_m.z})
        if (!std::isfinite(x) || std::abs(x)>32) throw std::invalid_argument("compound water part offset outside bounds");
    const auto q=part.rotation_local;
    const double norm=q.w*q.w+q.x*q.x+q.y*q.y+q.z*q.z;
    if (!std::isfinite(norm) || std::abs(norm-1)>1e-8)
        throw std::invalid_argument("compound water rotation must be normalized");
    const auto point = [&](Vec3 p) { return part.center_local_m + part.rotation_local.rotate(p); };
    const auto plane = [&](Vec3 n, Vec3 p) {
        const Vec3 normal = part.rotation_local.rotate(n);
        out.planes.push_back({normal, dot(normal, point(p))});
    };
    const auto face = [&](Vec3 a, Vec3 b, Vec3 c, Vec3 d) {
        out.faces.push_back({point(a), point(b), point(c), point(d)});
    };
    const auto rectangle = [&](Vec3 centre, Vec3 u, Vec3 v, double a, double b) {
        const int nu = std::clamp(int(std::ceil(a / patch_m)), 1, 24);
        const int nv = std::clamp(int(std::ceil(b / patch_m)), 1, 24);
        for (int i = 0; i < nu; ++i) for (int j = 0; j < nv; ++j) {
            const Vec3 base = centre + u * (-a / 2 + a * i / nu) + v * (-b / 2 + b * j / nv);
            face(base, base + u * (a / nu), base + u * (a / nu) + v * (b / nv), base + v * (b / nv));
        }
    };
    const Vec3 h = part.geometry.dimensions_m / 2;
    const Vec3 ex{1,0,0}, ey{0,1,0}, ez{0,0,1};
    if (part.geometry.kind == PrimitiveKind::Box) {
        plane(ex, {h.x,0,0}); plane(-ex, {-h.x,0,0});
        plane(ey, {0,h.y,0}); plane(-ey, {0,-h.y,0});
        plane(ez, {0,0,h.z}); plane(-ez, {0,0,-h.z});
        rectangle({h.x,0,0}, ey, ez, 2*h.y, 2*h.z);
        rectangle({-h.x,0,0}, ez, ey, 2*h.z, 2*h.y);
        rectangle({0,h.y,0}, ez, ex, 2*h.z, 2*h.x);
        rectangle({0,-h.y,0}, ex, ez, 2*h.x, 2*h.z);
        rectangle({0,0,h.z}, ex, ey, 2*h.x, 2*h.y);
        rectangle({0,0,-h.z}, ey, ex, 2*h.y, 2*h.x);
    } else if (part.geometry.kind == PrimitiveKind::Cylinder) {
        const int n = std::clamp(int(std::ceil(2*pi*h.x/patch_m)), 48, 128);
        // Preserve pi*r*r exactly in the polygon's area, rather than losing
        // buoyancy with an inscribed cylinder. Radius error <= 0.143% at n=48.
        const double r = h.x * std::sqrt(2*pi/(n*std::sin(2*pi/n)));
        const int ny = std::clamp(int(std::ceil(2*h.y/patch_m)), 1, 24);
        const int nr = std::clamp(int(std::ceil(r/patch_m)), 1, 24);
        plane(ey, {0,h.y,0}); plane(-ey, {0,-h.y,0});
        for (int k = 0; k < n; ++k) {
            const double a = 2*pi*k/n, b = 2*pi*(k+1)/n;
            const Vec3 u{r*std::cos(a),0,r*std::sin(a)}, v{r*std::cos(b),0,r*std::sin(b)};
            plane({std::cos((a+b)/2),0,std::sin((a+b)/2)}, u);
            for (int j = 0; j < ny; ++j) {
                const Vec3 low{0,-h.y+2*h.y*j/ny,0}, high{0,-h.y+2*h.y*(j+1)/ny,0};
                face(u+low, u+high, v+high, v+low);
            }
            for (int j = 0; j < nr; ++j) {
                const double low = double(j)/nr, high = double(j+1)/nr;
                face(low*u+Vec3{0,h.y,0}, low*v+Vec3{0,h.y,0}, high*v+Vec3{0,h.y,0}, high*u+Vec3{0,h.y,0});
                face(low*v+Vec3{0,-h.y,0}, low*u+Vec3{0,-h.y,0}, high*u+Vec3{0,-h.y,0}, high*v+Vec3{0,-h.y,0});
            }
        }
    } else throw std::invalid_argument("compound water supports boxes and cylinders");
    const double inf=std::numeric_limits<double>::infinity();
    out.low={inf,inf,inf}; out.high={-inf,-inf,-inf};
    for (const auto &f:out.faces) for (const auto &p:f) {
        out.low={std::min(out.low.x,p.x),std::min(out.low.y,p.y),std::min(out.low.z,p.z)};
        out.high={std::max(out.high.x,p.x),std::max(out.high.y,p.y),std::max(out.high.z,p.z)};
    }
    return out;
}
}

std::string compoundWaterKey(const std::vector<CompoundWaterPart> &parts) {
    std::ostringstream key;
    key << std::hexfloat << parts.size();
    for (const auto &p : parts) {
        key << '|' << int(p.geometry.kind);
        for (double x : {p.geometry.dimensions_m.x,p.geometry.dimensions_m.y,p.geometry.dimensions_m.z,
                         p.center_local_m.x,p.center_local_m.y,p.center_local_m.z,
                         p.rotation_local.w,p.rotation_local.x,p.rotation_local.y,p.rotation_local.z}) key << '|' << x;
    }
    return key.str();
}

std::vector<WaterCoupling::Patch> compoundWaterSurface(const std::vector<CompoundWaterPart> &parts, double patch_m) {
    if (parts.empty() || parts.size() > 64 || !(patch_m > 0) || !std::isfinite(patch_m))
        throw std::invalid_argument("compound water needs 1..64 parts and a finite positive patch size");
    std::vector<Solid> solids;
    for (const auto &p : parts) solids.push_back(solid(p, std::max(.02,patch_m)));
    std::vector<WaterCoupling::Patch> result;
    for (std::size_t i = 0; i < solids.size(); ++i) for (const auto &face : solids[i].faces) {
        Vec3 normal{};
        for (std::size_t k=1; k+1<face.size(); ++k) normal += cross(face[k]-face[0],face[k+1]-face[0]);
        if (length(normal) < 1e-14) continue;
        normal = normalized(normal);
        std::vector<Polygon> exposed{face};
        for (std::size_t j=0; j<solids.size() && !exposed.empty(); ++j) {
            if (i == j) continue;
            if (solids[i].high.x<solids[j].low.x-eps || solids[i].low.x>solids[j].high.x+eps ||
                solids[i].high.y<solids[j].low.y-eps || solids[i].low.y>solids[j].high.y+eps ||
                solids[i].high.z<solids[j].low.z-eps || solids[i].low.z>solids[j].high.z+eps) continue;
            // Earlier parts own duplicate outward faces. Opposed faces at
            // a touching interface are covered on both sides and removed.
            bool earlier_owns=false;
            if (j > i) for (const auto &p : solids[j].planes)
                earlier_owns |= dot(p.normal,normal)>1-1e-12 && std::abs(dot(p.normal,face[0])-p.distance)<eps;
            if (earlier_owns) continue;
            std::vector<Polygon> next;
            for (auto remainder : exposed) for (const auto &p : solids[j].planes) {
                auto outside=clipped(remainder,p,false);
                if (outside.size()>=3) next.push_back(std::move(outside));
                remainder=clipped(remainder,p,true);
                if (remainder.size()<3) break;
            }
            exposed=std::move(next);
            if (exposed.size()>100000) throw std::invalid_argument("compound water surface exceeds polygon budget");
        }
        for (const auto &p : exposed) for (std::size_t k=1; k+1<p.size(); ++k) {
            const double area=.5*length(cross(p[k]-p[0],p[k+1]-p[0]));
            if (area<1e-14) continue;
            WaterCoupling::Patch patch{{p[0],p[k],p[k+1],p[k+1]},normal,area};
            result.push_back(patch);
            if (result.size()>1000000) throw std::invalid_argument("compound water surface exceeds patch budget");
        }
    }
    return result;
}

std::vector<std::pair<double,double>> compoundVerticalSpans(const BodyInWater &b, double x, double z) {
    std::vector<std::pair<double,double>> out;
    if (!b.parts_local) return out;
    const Vec3 body_o=inverse(b.orientation).rotate(Vec3{x,0,z}-b.com_m);
    const Vec3 body_d=inverse(b.orientation).rotate(Vec3{0,1,0});
    for (const auto &p : *b.parts_local) {
        const Vec3 o=inverse(p.rotation_local).rotate(body_o-p.center_local_m);
        const Vec3 d=inverse(p.rotation_local).rotate(body_d);
        const Vec3 h=p.geometry.dimensions_m/2;
        double lo=-std::numeric_limits<double>::infinity(), hi=-lo;
        const auto slab=[&](double at,double direction,double half) {
            if (std::abs(direction)<1e-12) { if (std::abs(at)>half) hi=lo-1; return; }
            const double a=(-half-at)/direction,c=(half-at)/direction;
            lo=std::max(lo,std::min(a,c)); hi=std::min(hi,std::max(a,c));
        };
        slab(o.y,d.y,h.y);
        if (p.geometry.kind==PrimitiveKind::Box) { slab(o.x,d.x,h.x); slab(o.z,d.z,h.z); }
        else if (p.geometry.kind==PrimitiveKind::Cylinder) {
            const double a=d.x*d.x+d.z*d.z, c=o.x*o.x+o.z*o.z-h.x*h.x;
            if (a<1e-24) { if (c>0) hi=lo-1; }
            else {
                const double q=o.x*d.x+o.z*d.z, disc=q*q-a*c;
                if (disc<0) hi=lo-1;
                else { lo=std::max(lo,(-q-std::sqrt(disc))/a); hi=std::min(hi,(-q+std::sqrt(disc))/a); }
            }
        } else throw std::invalid_argument("compound water supports boxes and cylinders");
        if (lo<=hi) out.emplace_back(lo,hi);
    }
    std::sort(out.begin(),out.end());
    return out;
}
}
