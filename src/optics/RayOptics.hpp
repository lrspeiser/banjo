#pragma once

// Geometric optics: rays of light, followed from where they start through
// reflections and refractions until they are absorbed, scattered or leave
// (docs/optics-checkpoint.md).
//
// Each ray carries power, in watts. At every surface the power is shared out
// by the surface's laws, and every share is put somewhere on one ledger:
//
//     sent = absorbed by bodies + absorbed by the ground + escaped + scattered
//            + split off too faint to follow + still going at the bounce limit
//            + residual
//
// and the residual is rounding and nothing else.
//
// The laws, and nothing else, decide where light goes:
//
// - Reflection: the angle out equals the angle in, about the surface's normal.
// - Refraction: Snell's law, n1 sin(i) = n2 sin(t). Past the critical angle,
//   going from the denser side, nothing is transmitted (total internal
//   reflection).
// - Fresnel's equations for the share reflected at a smooth surface between two
//   transparent media, for unpolarised light (the mean of the s and p shares).
// - Beer and Lambert's law inside a transparent body: the power falls as
//   exp(-absorption x path length), and what is lost is absorbed by the body.
//
// It knows nothing of the world it runs in: the host answers where a ray meets
// a surface and what that surface is (Scene). What it does not model -- light
// as a wave (no diffraction or interference), colour (no dispersion: one index
// for all of the light), polarisation (each split treats the light as
// unpolarised), and scattered light, which is counted where it is scattered and
// not followed -- is in the checkpoint document.
#include "core/Math.hpp"

#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace banjo::optics {

// Light's power in two bands, watts: visible (with the little ultraviolet) and
// near infrared. One geometry for both -- no dispersion: a ray of both bands
// bends as one -- but each band is absorbed at its own rate, because glass and
// ice pass visible light and soak up the infrared (docs/optics-checkpoint.md).
inline constexpr std::size_t kBands = 2;
using Power = std::array<double, kBands>;
[[nodiscard]] inline double total(const Power &p) { return p[0] + p[1]; }
[[nodiscard]] inline Power scaled(const Power &p, double k) { return {p[0] * k, p[1] * k}; }

// The law of reflection: `along` turned back about `normal` (unit vectors; the
// normal may face either way).
[[nodiscard]] Vec3 reflect(const Vec3 &along, const Vec3 &normal);

// Snell's law and Fresnel's equations at a smooth surface, light going from a
// medium of index `n_from` into one of `n_to`. `toward` is the unit normal
// facing back the way the light came (dot(along, toward) < 0).
struct Refraction {
    bool total{};            // total internal reflection: nothing goes through
    Vec3 along{};            // the way the transmitted light goes, when it does
    double reflectance{};    // the share reflected (1 when total)
    double cos_incidence{};  // the cosine of the angle of incidence
};
[[nodiscard]] Refraction refract(const Vec3 &along, const Vec3 &toward, double n_from, double n_to);

// The share of unpolarised light a smooth surface reflects, at incidence
// cos_incidence, from index n_from into n_to (1 past the critical angle).
[[nodiscard]] double fresnelReflectance(double cos_incidence, double n_from, double n_to);

// What a surface does with the light reaching it, band by band.
struct Surface {
    // Smooth and transparent: Fresnel splits it at the surface, Snell bends what
    // goes in, and Beer-Lambert absorbs it on the way through.
    bool transparent{};
    double refractive_index{1.0};
    Power absorption_per_m{};
    // Opaque: `specular` of it is reflected as from a mirror, `absorbed` is
    // absorbed, and the rest is scattered in every direction (counted, not
    // followed).
    Power specular{};
    Power absorbed{1.0, 1.0};
};

// Where a ray meets a surface. `body` is the host's index of what it met, or -1
// for the ground (or anything else that is not one of the host's bodies).
struct Meeting {
    bool hit{};
    int body{-1};
    double distance_m{};
    Vec3 point_m{};
    Vec3 normal{};           // the surface's outward normal there, unit
};

// ---- lenses (docs/light-spots.md, "Lenses") ----------------------------------
//
// A lens is a disc of a clear material with two spherical faces, given in its
// own frame: its axis is z, its middle the origin, the front face's vertex at
// z = -t/2 and the back face's at z = +t/2, its rim a cylinder of radius
// `aperture_m`. Each face's radius is signed the lensmaker's way: positive
// when the face's centre of curvature lies on the +z side of it, so a lens
// that bulges both ways (biconvex) has a positive front radius and a negative
// back one, and one hollow both ways (biconcave) the other way round. Zero is
// a flat face. The faces are traced exactly as spheres -- nothing about the
// lens is declared but its shape, so where it brings light to a focus is what
// Snell's law at its two faces makes of that shape.
struct Lens {
    double front_radius_m{};
    double back_radius_m{};
    double thickness_m{};        // on its axis, vertex to vertex
    double aperture_m{};         // the disc's radius
};

// "" when a lens can be made: a positive aperture and thickness, each curved
// face wider than the aperture, and some glass left at the rim.
[[nodiscard]] std::string lensProblem(const Lens &lens);
// How far a face stands from its vertex along the axis at a distance r from
// the axis (the sag, signed: +z positive).
[[nodiscard]] double lensFaceZ(double radius_m, double vertex_z, double r);
// Its thickness at the rim.
[[nodiscard]] double lensEdgeThicknessM(const Lens &lens);
// The lensmaker's equation for a thick lens in air of index n:
//     1/f = (n - 1) [1/R1 - 1/R2 + (n - 1) t / (n R1 R2)],
// and its back focal distance, from the back vertex to the focus,
//     BFD = f (1 - (n - 1) t / (n R1)).
// A flat face is an infinite radius. Negative for a lens that spreads light:
// then the focus is virtual, that far before the back vertex.
[[nodiscard]] double lensFocalLengthM(const Lens &lens, double n);
[[nodiscard]] double lensBackFocalDistanceM(const Lens &lens, double n);
// Where a ray meets the lens's surface, in the lens's own frame: the first
// place along it, past `from`, where it crosses a face or the rim within
// `reach_m` -- going in from outside, or out from inside. The normal is the
// surface's outward one.
[[nodiscard]] Meeting meetLens(const Lens &lens, const Vec3 &from, const Vec3 &along, double reach_m);

// The host's answers.
class Scene {
public:
    virtual ~Scene() = default;
    // The nearest surface along a ray travelling through the air, within
    // `reach_m`; `ignore` is a body the ray is to pass through (a lamp's own
    // fitting), or -1.
    virtual Meeting toSurface(const Vec3 &from, const Vec3 &along, double reach_m, int ignore) = 0;
    // Where a ray travelling inside `body` reaches its surface again.
    virtual Meeting outOf(int body, const Vec3 &from, const Vec3 &along, double reach_m) = 0;
    [[nodiscard]] virtual Surface surface(int body) const = 0;   // body >= 0; the ground is -1
    // Light arriving at a surface from the air, before the surface does
    // anything to it: what a light sensor on that surface reads.
    virtual void arrives(int body, const Vec3 &at, const Vec3 &along, const Vec3 &normal, const Power &power_w) {
        (void)body; (void)at; (void)along; (void)normal; (void)power_w;
    }
};

// One ray as it starts.
struct Ray {
    Vec3 from{};
    Vec3 along{};            // unit
    Power power_w{};
    // The bundle of light the ray stands for: its cross-section where it
    // starts (a sun ray's square of the grid), and the solid angle it spreads
    // into (a lamp's ray, a point source's share of its cone). Its section a
    // distance d along its way is section + spread d^2 -- through plane mirrors
    // exactly, through a lens not (a lens's focus is found from where the rays
    // land, not from this). What a lit spot's size is reckoned from.
    double section_m2{};
    double spread_sr{};
    int ignore{-1};          // a body it starts inside and passes out of unhindered
    unsigned light{};        // which light sent it, for the drawn paths
    bool drawn{};            // keep its path, to draw
    // Sunlight: before it is followed into the scene, look back toward the sun
    // from where it starts, and anything there (a hill beyond the scene) has
    // shaded it: absorbed by the ground.
    bool from_sky{};
};

struct Settings {
    // How many surfaces a ray (and anything split off it) may meet before it is
    // given up, its power counted as still going.
    unsigned bounce_limit{16};
    // A part split off at a surface -- the weaker of a reflection and a
    // refraction -- is followed only while it carries at least this share of
    // the power its ray started with (both bands together); a fainter one is
    // counted, not followed.
    double follow_share{0.02};
    // As far as a ray is looked along before it is said to have left.
    double reach_m{200.0};
    // How far off a surface a ray starts again after meeting it, so that it
    // does not meet the same surface where it stands.
    double offset_m{1.0e-6};
    // How far an escaping ray's last drawn segment runs.
    double drawn_escape_m{2.0};
};

// Both bands together, watts.
struct Ledger {
    double sent_w{};
    double absorbed_w{};        // by the host's bodies
    double ground_w{};          // by the ground, or by anything not a body
    double escaped_w{};
    double scattered_w{};
    double unfollowed_w{};      // split off too faint to follow
    double bounce_limit_w{};
    [[nodiscard]] double residualW() const {
        return sent_w - (absorbed_w + ground_w + escaped_w + scattered_w + unfollowed_w + bounce_limit_w);
    }
};

// A drawn ray: where it went, corner to corner, and the power on each leg.
struct Path {
    unsigned light{};
    std::vector<Vec3> points;
    std::vector<double> power_w;   // one per leg: points.size() - 1, both bands
};

// Where light was absorbed, one record each time a ray gives some of its power
// to a body: what the host needs to say WHERE a body is heated, not only how
// much (docs/light-spots.md). The records of a body add up to its absorbed_w.
struct Absorption {
    int body{-1};
    Vec3 at{};               // the surface point; through a clear body, where the leg inside starts
    Vec3 along{};            // the way the light was going
    Vec3 normal{};           // at a surface: its normal there, facing back toward the light
    double power_w{};        // both bands
    double section_m2{};     // the ray's bundle's cross-section here, across its way (Ray)
    // Absorbed on the way through a clear body (Beer and Lambert) rather than
    // at its surface: how long the leg inside is, and each band's power where
    // it starts and the rate it is absorbed at, so the host can say how much
    // of it each part of the leg took.
    bool through{};
    double length_m{};
    Power entering_w{};
    Power per_m{};
};

struct Result {
    Ledger ledger;
    std::vector<double> absorbed_w;   // by body index, both bands
    std::vector<Absorption> absorptions;
    std::vector<Path> paths;
    std::size_t rays{}, legs{}, casts{};
    // Rays that came into a body across a sharp edge and found themselves
    // already out of it: they went on through the air.
    std::size_t grazed{};
};

// Follow every ray. `bodies` is how many bodies the host's indices run to.
[[nodiscard]] Result trace(Scene &scene, std::size_t bodies, const std::vector<Ray> &rays,
                           const Settings &settings);

} // namespace banjo::optics
