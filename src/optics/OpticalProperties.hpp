#pragma once

// What each catalogue material does to light (docs/optics-checkpoint.md).
//
// One place, with where each number came from. Light here is two bands --
// visible (with the little ultraviolet) and near infrared -- because the
// materials that let light through treat them very differently: ordinary glass
// passes nine tenths of visible light through a hand's breadth of itself and
// soaks up most of the infrared, and ice does the same more so. One geometry
// serves both bands (there is no dispersion: one refractive index), and a rough
// surface's absorptance is one number for both (no figure by band was found).
//
// A surface does one of three things with the light that reaches it:
//
// - TRANSPARENT (glass, ice): it is smooth, so light is split at it by Fresnel's
//   equations into a reflected part and a part bent into it by Snell's law; the
//   bent part is absorbed as it goes through by Beer and Lambert's law, at
//   `absorption_per_m` for its band, and split again where it leaves.
// - POLISHED (a mirror finish on a metal): it reflects `polished_reflectance` of
//   what reaches it as from a mirror, by the law of reflection, and absorbs the
//   rest.
// - ROUGH (everything else, and a metal that has not been polished): it absorbs
//   `absorptance` of what reaches it and scatters the rest back in every
//   direction. Scattered light is counted, not followed (the engine traces only
//   light that goes one way).
#include "material/MaterialCatalog.hpp"

#include <array>
#include <string_view>

namespace banjo::optics {

// How sunlight's power divides between the two bands at the ground: "around 52
// to 55 percent infrared (above 700 nm), 42 to 43 percent visible (400 to 700
// nm), and 3 to 5 percent ultraviolet" (Wikipedia, "Sunlight", from the ASTM
// G173 reference spectrum). The ultraviolet goes with the visible band.
inline constexpr double kSunVisibleShare = 0.46;

struct OpticalProperties {
    bool transparent{};
    // Transparent: the refractive index, and how fast light of each band
    // (visible, infrared) is absorbed going through it, per metre of path.
    double refractive_index{1.0};
    std::array<double, 2> absorption_per_m{};
    // Whether a mirror finish can be put on it (a metal), and the share of the
    // light of each band reaching a polished surface it reflects as a mirror.
    bool polishable{};
    std::array<double, 2> polished_reflectance{};
    // A rough surface's share absorbed, both bands; the rest is scattered.
    double absorptance{1.0};
    // Where the numbers came from, in words.
    std::string_view source;
};

[[nodiscard]] OpticalProperties opticalProperties(MaterialPreset preset);

// The ground of every room is rock or concrete, and is treated as concrete: a
// rough surface that absorbs its share and scatters the rest.
[[nodiscard]] OpticalProperties groundOpticalProperties();

} // namespace banjo::optics
