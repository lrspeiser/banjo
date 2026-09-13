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
    const double composition = std::clamp(matter.composition_factor, 0.0, 1.0);

    s.layer_m = matter.layered ? std::max(0.0, matter.layer_depth_m) : 0.0;
    s.consumed_m = recessionDepthM(box_m, matter.consumed_fraction);
    s.surface = zone(law, matter.surface_k, matter.peak_surface_k, composition);
    s.core = matter.layered ? zone(law, matter.core_k, matter.peak_core_k, composition) : s.surface;
    const ZoneFactors surface_cooled =
        zone(law, kReferenceTemperatureK, matter.peak_surface_k, composition);
    const ZoneFactors core_cooled =
        matter.layered ? zone(law, kReferenceTemperatureK, matter.peak_core_k, composition)
                       : surface_cooled;

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
    s.stiffness_if_cooled = areal(surface_cooled.stiffness, core_cooled.stiffness);
    s.tension_if_cooled = areal(surface_cooled.tension, core_cooled.tension);
    s.shear_if_cooled = areal(surface_cooled.shear, core_cooled.shear);
    s.bending_if_cooled = bent(surface_cooled.tension, core_cooled.tension);

    // Char: the layer once its hottest passed the char point, the whole of
    // what is left once the core's has.
    const bool charred_layer = law.char_k > 0.0 && matter.peak_surface_k >= law.char_k;
    const bool charred_core =
        law.char_k > 0.0 && (matter.layered ? matter.peak_core_k : matter.peak_surface_k) >= law.char_k;
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
