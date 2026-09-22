#include "thermo/ThermalMechanics.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace banjo::thermo {
namespace {

constexpr double kC = 273.15;   // degrees Celsius to kelvin

// A curve from the source's own table, which is in degrees Celsius.
ReductionCurve celsius(std::initializer_list<std::pair<double, double>> table) {
    ReductionCurve curve;
    for (const auto &[c, factor] : table) curve.points.emplace_back(c + kC, factor);
    return curve;
}

double component(const Vec3 &v, int axis) { return axis == 0 ? v.x : axis == 1 ? v.y : v.z; }

std::vector<MechanicalLaw> makeLaws() {
    std::vector<MechanicalLaw> laws;

    // ---- oak ------------------------------------------------------------
    {
        MechanicalLaw oak;
        oak.material = "oak";
        oak.id = "timber, EN 1995-1-2 Annex B";
        oak.version = "1";
        oak.provenance = Provenance::ReferenceDerived;
        oak.source =
            "EN 1995-1-2:2004 Annex B, Figure B.2 (strength parallel to grain: tension 0.65, "
            "compression 0.25 and shear 0.40 at 100 degC, all 0 at 300 degC) and Figure B.3 "
            "(modulus of elasticity in tension 0.50 at 100 degC, 0 at 300 degC); the char line "
            "is the 300 degC isotherm (3.4.2). These are the SOFTWOOD curves: EN 1995-1-2 "
            "gives none for hardwood, so for oak they are an assumption, not a validation";
        oak.load_bearing = "dry wood";
        oak.reference_fraction = 0.88;   // oak is 0.88 dry wood in the thermal model
        oak.stiffness = celsius({{20.0, 1.0}, {100.0, 0.50}, {300.0, 0.0}});
        oak.tension = celsius({{20.0, 1.0}, {100.0, 0.65}, {300.0, 0.0}});
        oak.compression = celsius({{20.0, 1.0}, {100.0, 0.25}, {300.0, 0.0}});
        oak.shear = celsius({{20.0, 1.0}, {100.0, 0.40}, {300.0, 0.0}});
        oak.char_k = 300.0 + kC;
        // Pyrolysis of the hemicelluloses begins near 200 degC, and what it
        // takes does not come back. How much is lost between there and char
        // is a DEMONSTRATION shape: straight down to nothing at 300 degC.
        oak.permanent = celsius({{200.0, 1.0}, {300.0, 0.0}});
        oak.permanent_source =
            "demonstration: nothing lost for good below 200 degC (where pyrolysis begins), "
            "falling linearly to nothing at the 300 degC char line";
        oak.recovers = true;
        oak.supported_from_k = kReferenceTemperatureK;
        oak.supported_to_k = 300.0 + kC;    // beyond it the zone is char: 0, and supported
        oak.recovery_to_k = 300.0 + kC;
        oak.not_modelled = {
            "the softwood curves stand in for oak: EN 1995-1-2 gives none for hardwood",
            "strength perpendicular to the grain, and any direction but along it",
            "moisture's own effect on strength beyond what the curves already contain; a "
            "body declared with less dry wood than oak's 0.88 carries less in proportion "
            "(a demonstration rule of mixtures)",
            "char keeps no strength at all here (the Eurocode convention); real char keeps "
            "a little",
            "the loss that stays after cooling from between 200 and 300 degC is a "
            "demonstration value",
            "creep under load at temperature beyond what the curves contain"};
        laws.push_back(std::move(oak));
    }

    // ---- iron -----------------------------------------------------------
    {
        MechanicalLaw iron;
        iron.material = "iron";
        iron.id = "carbon steel, EN 1993-1-2 Table 3.1";
        iron.version = "1";
        iron.provenance = Provenance::ReferenceDerived;
        iron.source =
            "EN 1993-1-2:2005 Table 3.1, carbon steel: effective yield strength k_y (1.0 up "
            "to 400 degC, 0.78 at 500, 0.47 at 600, 0.23 at 700, 0.11 at 800, 0 at 1200) for "
            "every strength, and the slope of the linear elastic range k_E (0.9 at 200 degC, "
            "0.7 at 400, 0.31 at 600, 0.09 at 800) for stiffness. The catalogue's iron is "
            "given carbon steel's curves: wrought and cast iron are not covered by the standard";
        iron.load_bearing = "iron";
        iron.reference_fraction = 1.0;
        iron.stiffness = celsius({{20.0, 1.0},    {100.0, 1.0},   {200.0, 0.9},    {300.0, 0.8},
                                  {400.0, 0.7},   {500.0, 0.6},   {600.0, 0.31},   {700.0, 0.13},
                                  {800.0, 0.09},  {900.0, 0.0675}, {1000.0, 0.045}, {1100.0, 0.0225},
                                  {1200.0, 0.0}});
        const ReductionCurve yield = celsius({{20.0, 1.0},   {400.0, 1.0},   {500.0, 0.78},
                                              {600.0, 0.47}, {700.0, 0.23},  {800.0, 0.11},
                                              {900.0, 0.06}, {1000.0, 0.04}, {1100.0, 0.02},
                                              {1200.0, 0.0}});
        iron.tension = yield;
        iron.compression = yield;
        iron.shear = yield;
        iron.char_k = 0.0;
        iron.recovers = true;
        iron.supported_from_k = kReferenceTemperatureK;
        iron.supported_to_k = 1200.0 + kC;
        // Structural steel cooled from below about 600 degC regains its room
        // temperature properties. From hotter, what it keeps depends on the
        // steel and is not modelled: it is let recover, and said to be outside.
        iron.recovery_to_k = 600.0 + kC;
        iron.not_modelled = {
            "carbon steel's curves stand in for the catalogue's iron",
            "what iron keeps after being heated past 600 degC: it is let recover fully, "
            "which is outside what the model supports",
            "creep at temperature, and thermal expansion (a later, separate increment)"};
        laws.push_back(std::move(iron));
    }

    // ---- concrete -------------------------------------------------------
    {
        MechanicalLaw concrete;
        concrete.material = "concrete";
        concrete.id = "concrete, EN 1992-1-2 Table 3.1";
        concrete.version = "1";
        concrete.provenance = Provenance::ReferenceDerived;
        concrete.source =
            "EN 1992-1-2:2004 Table 3.1, siliceous aggregate, for compression (0.95 at 200 "
            "degC, 0.75 at 400, 0.45 at 600, 0.15 at 800, 0 at 1200); 3.2.2.2 for tension (1.0 "
            "to 100 degC, falling linearly to 0 at 600). Shear follows tension, declared";
        concrete.load_bearing = "concrete";
        concrete.reference_fraction = 1.0;
        concrete.compression = celsius({{20.0, 1.0},  {100.0, 1.0},  {200.0, 0.95}, {300.0, 0.85},
                                        {400.0, 0.75}, {500.0, 0.60}, {600.0, 0.45}, {700.0, 0.30},
                                        {800.0, 0.15}, {900.0, 0.08}, {1000.0, 0.04}, {1100.0, 0.01},
                                        {1200.0, 0.0}});
        concrete.tension = celsius({{20.0, 1.0}, {100.0, 1.0}, {600.0, 0.0}});
        concrete.shear = concrete.tension;
        // Concrete does not regain strength when it cools -- it loses a little
        // more, which is not modelled. The peak governs.
        concrete.recovers = false;
        concrete.supported_from_k = kReferenceTemperatureK;
        concrete.supported_to_k = 1200.0 + kC;
        concrete.recovery_to_k = 0.0;
        concrete.not_modelled = {
            "its stiffness: held at its room-temperature value",
            "spalling",
            "the further loss of strength that comes with cooling"};
        laws.push_back(std::move(concrete));
    }

    // ---- ice ------------------------------------------------------------
    //
    // A law with no curves. Ice melts (thermo/Thermochemistry.cpp, "melting of
    // ice"), and what melts must leave the body -- its section, its mass, the
    // shape it collides and is drawn with -- exactly as what burns leaves an
    // oak beam. That is decided by the load-bearing matter used, which only a
    // law names. The law says nothing else: the strength the catalogue gives
    // ice holds at every temperature up to its melting point.
    {
        MechanicalLaw ice;
        ice.material = "ice";
        ice.id = "ice, melting only";
        ice.version = "1";
        ice.provenance = Provenance::Demonstration;
        ice.source =
            "no temperature dependence is declared for ice's strength or stiffness: the "
            "catalogue's values hold up to the melting point. The law names ice as its own "
            "load-bearing matter, so what melts is taken out of the section, the mass and the "
            "shape";
        ice.load_bearing = "ice";
        ice.reference_fraction = 1.0;
        ice.gone = "melted";
        ice.char_k = 0.0;
        ice.recovers = true;
        // Ice exists only up to its melting point, and nothing here changes
        // with temperature below it.
        ice.supported_from_k = 0.0;
        ice.supported_to_k = 273.15;
        ice.recovery_to_k = 273.15;
        ice.not_modelled = {
            "ice is stronger and stiffer the colder it is: not modelled, the catalogue's values "
            "hold at every temperature up to melting",
            "creep: ice flows under a sustained load",
            "brine, trapped air and grain size",
            "meltwater held on or in the ice: it runs off as it melts"};
        laws.push_back(std::move(ice));
    }
    return laws;
}

// One zone: the factor at the temperature it is at, limited by what its
// hottest moment took for good.
ZoneFactors zone(const MechanicalLaw &law, double t, double peak, double composition) {
    if (law.char_k > 0.0 && peak >= law.char_k) return {0.0, 0.0, 0.0, 0.0};
    const double lasting = law.permanent.empty() ? 1.0 : law.permanent.at(peak);
    const auto one = [&](const ReductionCurve &curve) {
        double f = curve.at(t);
        if (!law.recovers) f = std::min(f, curve.at(peak));
        return std::clamp(std::min(f, lasting), 0.0, 1.0) * composition;
    };
    return {one(law.stiffness), one(law.tension), one(law.compression), one(law.shear)};
}

double modulus(double breadth, double depth) { return breadth * depth * depth / 6.0; }

std::string kelvin(double t) {
    char text[32];
    std::snprintf(text, sizeof text, "%.0f K", t);
    return text;
}

}  // namespace

double ReductionCurve::at(double temperature_k) const {
    if (points.empty()) return 1.0;
    if (!(temperature_k > points.front().first)) return points.front().second;
    if (temperature_k >= points.back().first) return points.back().second;
    for (std::size_t i = 1; i < points.size(); ++i) {
        if (temperature_k > points[i].first) continue;
        const auto &[t0, f0] = points[i - 1];
        const auto &[t1, f1] = points[i];
        return t1 > t0 ? f0 + (f1 - f0) * (temperature_k - t0) / (t1 - t0) : f1;
    }
    return points.back().second;
}

const std::vector<MechanicalLaw> &mechanicalLaws() {
    static const std::vector<MechanicalLaw> laws = makeLaws();
    return laws;
}

const MechanicalLaw *lawFor(std::string_view material) {
    for (const MechanicalLaw &law : mechanicalLaws())
        if (law.material == material) return &law;
    return nullptr;
}

double recessionDepthM(const Vec3 &box_m, double consumed_fraction) {
    const double share = std::clamp(consumed_fraction, 0.0, 1.0);
    if (!(share > 0.0)) return 0.0;
    const double a = std::max(0.0, box_m.x), b = std::max(0.0, box_m.y), c = std::max(0.0, box_m.z);
    const double whole = a * b * c;
    if (!(whole > 0.0)) return 0.0;
    // (a - 2x)(b - 2x)(c - 2x) = (1 - share) a b c: every face in by the same
    // depth. Falls monotonically in x, so bisection finds it.
    const double target = (1.0 - share) * whole;
    double low = 0.0, high = 0.5 * std::min({a, b, c});
    for (int k = 0; k < 80; ++k) {
        const double x = 0.5 * (low + high);
        const double left = std::max(0.0, a - 2.0 * x) * std::max(0.0, b - 2.0 * x) *
                            std::max(0.0, c - 2.0 * x);
        if (left > target) low = x;
        else high = x;
    }
    return 0.5 * (low + high);
}

MaterialField materialField(const MechanicalLaw *law, const MatterState &matter, const Vec3 &box_m,
                            bool round) {
    MaterialField f;
    f.box_m = round ? Vec3{box_m.x, box_m.x, box_m.x} : box_m;
    f.round = round;
    f.surface_kg = matter.surface_kg;
    f.core_kg = matter.core_kg;
    f.layered = matter.layered;
    f.layer_m = matter.layered ? std::max(0.0, matter.layer_depth_m) : 0.0;
    if (law == nullptr) return f;   // every factor one, nothing burned: as it was built
    f.has_law = true;
    const double composition = std::clamp(matter.composition_factor, 0.0, 1.0);
    // A sphere's volume goes as its diameter cubed exactly as its box's does,
    // so the same depth takes the same share of either.
    f.consumed_m = recessionDepthM(f.box_m, matter.consumed_fraction);
    f.surface = zone(*law, matter.surface_k, matter.peak_surface_k, composition);
    f.core = matter.layered ? zone(*law, matter.core_k, matter.peak_core_k, composition) : f.surface;
    f.surface_cooled = zone(*law, kReferenceTemperatureK, matter.peak_surface_k, composition);
    f.core_cooled = matter.layered
                        ? zone(*law, kReferenceTemperatureK, matter.peak_core_k, composition)
                        : f.surface_cooled;
    // Char: the layer once its hottest passed the char point, the whole of what
    // is left once the core's has.
    f.surface_char = law->char_k > 0.0 && matter.peak_surface_k >= law->char_k;
    f.core_char = law->char_k > 0.0 &&
                  (matter.layered ? matter.peak_core_k : matter.peak_surface_k) >= law->char_k;
    return f;
}

namespace {
// Half extents of the reference box inset by `depth` on every face.
Vec3 insetHalf(const MaterialField &f, double depth) {
    return {std::max(0.0, 0.5 * f.box_m.x - depth), std::max(0.0, 0.5 * f.box_m.y - depth),
            std::max(0.0, 0.5 * f.box_m.z - depth)};
}
double overlap(double centre, double half_cube, double half_box) {
    return std::max(0.0, std::min(centre + half_cube, half_box) - std::max(centre - half_cube, -half_box));
}
// The volume a cube shares with a box centred at the origin: separable, so exact.
double cubeInBox(const Vec3 &at, double cell, const Vec3 &half) {
    const double h = 0.5 * cell;
    return overlap(at.x, h, half.x) * overlap(at.y, h, half.y) * overlap(at.z, h, half.z);
}
constexpr double kPiValue = 3.14159265358979323846;
}  // namespace

Vec3 remainingBox(const MaterialField &f) { return 2.0 * insetHalf(f, f.consumed_m); }

double remainingVolumeM3(const MaterialField &f) {
    const Vec3 d = remainingBox(f);
    return f.round ? kPiValue * d.x * d.x * d.x / 6.0 : d.x * d.y * d.z;
}

double coreVolumeM3(const MaterialField &f) {
    if (!f.layered) return 0.0;
    const Vec3 d = 2.0 * insetHalf(f, f.consumed_m + f.layer_m);
    return f.round ? kPiValue * d.x * d.x * d.x / 6.0 : d.x * d.y * d.z;
}

CellShare cellShare(const MaterialField &f, const Vec3 &at, double cell_m) {
    CellShare share;
    if (!(cell_m > 0.0)) return share;
    if (!f.round) {
        // Against what the cell held cold: the part of it inside the box as it
        // was. So a cell nothing has happened to is exactly whole, whatever the
        // grid made of the box's edge.
        const double cold = cubeInBox(at, cell_m, insetHalf(f, 0.0));
        if (cold > 0.0) {
            const double left = f.consumed_m > 0.0 ? cubeInBox(at, cell_m, insetHalf(f, f.consumed_m)) : cold;
            const double core =
                f.layered ? cubeInBox(at, cell_m, insetHalf(f, f.consumed_m + f.layer_m)) : 0.0;
            const double remaining = left >= cold ? 1.0 : left / cold;
            share.core = std::min(remaining, core / cold);
            share.surface = remaining - share.core;
            return share;
        }
    }
    // A sphere, or a cell the box does not reach: sampled, 4 x 4 x 4 points,
    // against the same count cold. Radial depth for a sphere.
    constexpr int kSamples = 4;
    const double radius = 0.5 * f.box_m.x;
    const Vec3 half = insetHalf(f, 0.0);
    int cold = 0, left = 0, core = 0;
    for (int i = 0; i < kSamples; ++i)
        for (int j = 0; j < kSamples; ++j)
            for (int k = 0; k < kSamples; ++k) {
                const Vec3 p = at + cell_m * Vec3{(i + 0.5) / kSamples - 0.5, (j + 0.5) / kSamples - 0.5,
                                                  (k + 0.5) / kSamples - 0.5};
                const double depth =
                    f.round ? radius - length(p)
                            : std::min({half.x - std::abs(p.x), half.y - std::abs(p.y), half.z - std::abs(p.z)});
                if (depth < 0.0) continue;
                ++cold;
                if (depth < f.consumed_m) continue;
                ++left;
                if (f.layered && depth >= f.consumed_m + f.layer_m) ++core;
            }
    if (cold == 0) {
        // A cell wholly outside the reference: judged by its centre alone.
        const double depth = f.round ? radius - length(at)
                                     : std::min({half.x - std::abs(at.x), half.y - std::abs(at.y),
                                                 half.z - std::abs(at.z)});
        const bool gone = depth < f.consumed_m && f.consumed_m > 0.0;
        const bool deep = f.layered && depth >= f.consumed_m + f.layer_m;
        share.surface = gone || deep ? 0.0 : 1.0;
        share.core = !gone && deep ? 1.0 : 0.0;
        return share;
    }
    share.core = static_cast<double>(core) / cold;
    share.surface = static_cast<double>(left - core) / cold;
    return share;
}

ZoneFactors cellFactors(const MaterialField &f, const CellShare &share) {
    const auto mix = [&](double on_surface, double in_core) {
        if (on_surface == in_core) return on_surface * share.remaining();
        return on_surface * share.surface + in_core * share.core;
    };
    return {mix(f.surface.stiffness, f.core.stiffness), mix(f.surface.tension, f.core.tension),
            mix(f.surface.compression, f.core.compression), mix(f.surface.shear, f.core.shear)};
}

double cellMassKg(const MaterialField &f, const CellShare &share, double cell_m) {
    // What is left is spread evenly over the volume left (declared): the
    // network knows how much each zone holds, not how it is spread inside it.
    const double volume = remainingVolumeM3(f);
    const double mass = f.surface_kg + f.core_kg;
    if (!(volume > 0.0)) return 0.0;
    return mass / volume * share.remaining() * cell_m * cell_m * cell_m;
}

ZoneFactors bondFactors(const ZoneFactors &a, const ZoneFactors &b) {
    const auto series = [](double x, double y) {
        if (x == y) return x;
        return x > 0.0 && y > 0.0 ? 2.0 * x * y / (x + y) : 0.0;
    };
    return {series(a.stiffness, b.stiffness), std::min(a.tension, b.tension),
            std::min(a.compression, b.compression), std::min(a.shear, b.shear)};
}

FieldMassProperties massProperties(const MaterialField &f) {
    FieldMassProperties out;
    out.mass_kg = f.surface_kg + f.core_kg;
    const Vec3 d = remainingBox(f);
    if (f.round) {
        const double r = 0.5 * d.x;
        const double i = 0.4 * out.mass_kg * r * r;
        out.inertia_kg_m2 = {i, i, i};
    } else {
        const double k = out.mass_kg / 12.0;
        out.inertia_kg_m2 = {k * (d.y * d.y + d.z * d.z), k * (d.x * d.x + d.z * d.z),
                             k * (d.x * d.x + d.y * d.y)};
    }
    return out;
}

double outsideRemainingM(const MaterialField &f, const Vec3 &at) {
    const Vec3 half = insetHalf(f, f.consumed_m);
    if (f.round) return std::max(0.0, length(at) - half.x);
    const double dx = std::max(0.0, std::abs(at.x) - half.x), dy = std::max(0.0, std::abs(at.y) - half.y),
                 dz = std::max(0.0, std::abs(at.z) - half.z);
    // A box burned to nothing along one axis is gone however near the point is.
    if (!(half.x > 0.0) || !(half.y > 0.0) || !(half.z > 0.0))
        return std::max({dx, dy, dz, 1.0e-3});
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

double outsideReferenceM(const MaterialField &f, const Vec3 &at) {
    const Vec3 half = insetHalf(f, 0.0);
    if (f.round) return std::max(0.0, length(at) - half.x);
    const double dx = std::max(0.0, std::abs(at.x) - half.x), dy = std::max(0.0, std::abs(at.y) - half.y),
                 dz = std::max(0.0, std::abs(at.z) - half.z);
    return std::sqrt(dx * dx + dy * dy + dz * dz);
}

SectionState evaluateSection(const MechanicalLaw &law, const MatterState &matter, const Vec3 &box_m,
                             int length_axis, int depth_axis) {
    SectionState s;
    const int along = std::clamp(length_axis, 0, 2);
    const int u = (along + 1) % 3, v = (along + 2) % 3;
    int depth = depth_axis;
    if (depth != u && depth != v) depth = component(box_m, v) >= component(box_m, u) ? v : u;
    const int breadth = depth == u ? v : u;
    s.breadth_m = std::max(0.0, component(box_m, breadth));
    s.depth_m = std::max(0.0, component(box_m, depth));

    // The section is the material field integrated over a rectangle across the
    // load: the same field a lattice cell averages over its cube and the
    // collision shape is cut from. Nothing below reads the state any other way.
    const MaterialField field = materialField(&law, matter, box_m, false);
    s.layer_m = field.layer_m;
    s.consumed_m = field.consumed_m;
    s.surface = field.surface;
    s.core = field.core;
    const ZoneFactors surface_cooled = field.surface_cooled;
    const ZoneFactors core_cooled = field.core_cooled;

    // The rings. What burned is gone; inside it the surface layer; inside
    // that, when there is one, the core.
    const double B = s.breadth_m, H = s.depth_m;
    const double B1 = std::max(0.0, B - 2.0 * s.consumed_m);
    const double H1 = std::max(0.0, H - 2.0 * s.consumed_m);
    const double B2 = matter.layered ? std::max(0.0, B1 - 2.0 * s.layer_m) : 0.0;
    const double H2 = matter.layered ? std::max(0.0, H1 - 2.0 * s.layer_m) : 0.0;
    const double whole = B * H;
    const double outer = B1 * H1, inner = B2 * H2, ring = outer - inner;
    const auto areal = [&](double on_surface, double in_core) {
        return whole > 0.0 ? (on_surface * ring + in_core * inner) / whole : 0.0;
    };
    const double z0 = modulus(B, H);
    const auto bent = [&](double on_surface, double in_core) {
        return z0 > 0.0 ? (on_surface * (modulus(B1, H1) - modulus(B2, H2)) +
                           in_core * modulus(B2, H2)) / z0
                        : 0.0;
    };
    s.axial_stiffness = areal(s.surface.stiffness, s.core.stiffness);
    s.tension = areal(s.surface.tension, s.core.tension);
    s.compression = areal(s.surface.compression, s.core.compression);
    s.shear = areal(s.surface.shear, s.core.shear);
    s.bending = bent(s.surface.tension, s.core.tension);
    s.bending_compression = bent(s.surface.compression, s.core.compression);
    s.stiffness_if_cooled = areal(surface_cooled.stiffness, core_cooled.stiffness);
    s.tension_if_cooled = areal(surface_cooled.tension, core_cooled.tension);
    s.shear_if_cooled = areal(surface_cooled.shear, core_cooled.shear);
    s.bending_if_cooled = bent(surface_cooled.tension, core_cooled.tension);
    s.bending_compression_if_cooled = bent(surface_cooled.compression, core_cooled.compression);

    // Char: the layer once its hottest passed the char point, the whole of
    // what is left once the core's has.
    const bool charred_layer = field.surface_char;
    const bool charred_core = field.core_char;
    const double half = 0.5 * std::min(B1, H1);
    if (charred_core) s.char_m = half;
    else if (charred_layer) s.char_m = std::min(s.layer_m, half);
    s.sound_breadth_m = std::max(0.0, B1 - 2.0 * s.char_m);
    s.sound_depth_m = std::max(0.0, H1 - 2.0 * s.char_m);

    // Supported, or said not to be.
    const auto check = [&](double t, double peak, const char *where) {
        if (!s.supported) return;
        if (t < law.supported_from_k - 0.5) {
            s.supported = false;
            s.outside = std::string(where) + " at " + kelvin(t) + ", below the " +
                        kelvin(law.supported_from_k) + " the law starts at: cold is not modelled";
            return;
        }
        const bool char_answers = law.char_k > 0.0 && peak >= law.char_k;
        if (!char_answers && law.supported_to_k > 0.0 && t > law.supported_to_k + 0.5) {
            s.supported = false;
            s.outside = std::string(where) + " at " + kelvin(t) + ", above the " +
                        kelvin(law.supported_to_k) + " the law is supported to";
            return;
        }
        if (law.recovers && !char_answers && peak > law.recovery_to_k + 0.5 && t < peak - 1.0) {
            s.supported = false;
            s.outside = std::string(where) + " cooling from " + kelvin(peak) + ", hotter than the " +
                        kelvin(law.recovery_to_k) +
                        " below which what it keeps after cooling is modelled";
        }
    };
    check(matter.surface_k, matter.peak_surface_k, "the surface");
    if (matter.layered) check(matter.core_k, matter.peak_core_k, "the core");
    return s;
}

}  // namespace banjo::thermo
