#include "optics/OpticalProperties.hpp"

namespace banjo::optics {
namespace {

OpticalProperties rough(double absorptance, std::string_view source) {
    OpticalProperties p;
    p.absorptance = absorptance;
    p.source = source;
    return p;
}

OpticalProperties metal(double absorptance, double polished_visible, double polished_infrared,
                        std::string_view source) {
    OpticalProperties p = rough(absorptance, source);
    p.polishable = true;
    p.polished_reflectance = {polished_visible, polished_infrared};
    return p;
}

OpticalProperties clear(double refractive_index, double visible_per_m, double infrared_per_m,
                        std::string_view source) {
    OpticalProperties p;
    p.transparent = true;
    p.refractive_index = refractive_index;
    p.absorption_per_m = {visible_per_m, infrared_per_m};
    p.absorptance = 0.0;
    p.source = source;
    return p;
}

} // namespace

OpticalProperties opticalProperties(MaterialPreset preset) {
    switch (preset) {
    case MaterialPreset::Glass:
        // The catalogue's glass is annealed soda lime float glass. n = 1.526 is
        // Duffie and Beckman's figure for it (Solar Engineering of Thermal
        // Processes, Table 5.1.1).
        //
        // The absorption, band by band, from what a maker measures through a
        // sheet: Pilkington Optifloat Clear transmits 0.87 of visible light and
        // 0.72 of sunlight (taken as its 6 mm sheet). Its two faces reflect
        // about 0.08 between them (n = 1.52), so inside it keeps 0.948 of the
        // visible light, which is 9 per metre, and -- with sunlight 0.46
        // visible -- 0.65 of the infrared, which is 72 per metre. As one
        // number for sunlight through a thin cover that is about 42 per metre,
        // where Duffie and Beckman's worked example uses 32 (Example 5.3.1), and
        // low-iron "water white" glass is about 4 (De Soto et al. 2006).
        return clear(1.526, 9.0, 72.0,
                     "n 1.526 (Duffie and Beckman, Table 5.1.1); absorption 9 /m visible and 72 /m infrared, from "
                     "Pilkington Optifloat Clear's 0.87 light and 0.72 solar transmittance (6 mm) less its two "
                     "faces' reflection");
    case MaterialPreset::Ice:
        // n = 1.31 for ice Ih in visible light (1.309 at 589 nm). Visible: near
        // the clear end of the 0.6 to 16 per metre Grenfell and Maykut measured
        // at 500 nm in Arctic ice (J. Glaciology 18, 1977), which runs from
        // clear blue ice to white ice full of bubbles. Infrared: ice's own
        // absorption, 4 pi k / wavelength from Warren and Brandt's imaginary
        // index (J. Geophys. Res. 113, 2008), is about 22 per metre at 1.03 um
        // and thousands beyond 1.4 um; 100 per metre stands for the band, which
        // ice takes in within its first few centimetres.
        return clear(1.31, 1.5, 100.0,
                     "n 1.31 (ice Ih at 589 nm); absorption 1.5 /m visible (clear end of Grenfell and Maykut 1977, "
                     "500 nm) and 100 /m infrared (Warren and Brandt 2008: 22 /m at 1.03 um, thousands beyond "
                     "1.4 um)");
    case MaterialPreset::Aluminum:
        // Polished: the normal-incidence reflectance R = ((n-1)^2 + k^2) /
        // ((n+1)^2 + k^2) of Rakic's optical constants for aluminium (Appl.
        // Opt. 34, 1995): 0.92 at 450 nm and 0.91 at 560 nm; 0.90 at 910 nm
        // and 0.97 at 1.5 um. Rough: Engineering ToolBox gives a solar
        // absorptance of 0.30 for commercially "polished" aluminium sheet, which
        // is a sheet finish, not a mirror.
        return metal(0.30, 0.92, 0.93,
                     "polished reflectance 0.92 visible and 0.93 infrared from Rakic's optical constants (Appl. Opt. "
                     "34, 1995); rough solar absorptance 0.30 (Engineering ToolBox, aluminium sheet)");
    case MaterialPreset::Iron:
        // Polished: the same, from Johnson and Christy's optical constants for
        // iron (Phys. Rev. B 9, 1974): 0.50 at 450 nm, 0.51 at 550 nm; 0.58 at
        // 890 nm and 0.69 at 1.4 um. Rough: 0.65, what solar absorptance tables
        // give for galvanised iron (Engineering ToolBox 0.64, IES 0.65); none
        // was found for bare, rusting iron, which is darker.
        return metal(0.65, 0.51, 0.62,
                     "polished reflectance 0.51 visible and 0.62 infrared from Johnson and Christy's optical "
                     "constants (Phys. Rev. B 9, 1974); rough solar absorptance 0.65 (galvanised iron, Engineering "
                     "ToolBox 0.64 and IES 0.65; no figure found for bare iron)");
    case MaterialPreset::Oak:
        // Wood exposed outdoors: 0.40, 0.31 to 0.57 (Kim et al., inverse method,
        // Jeonbuk National University), rising with density and darkness; oak
        // is a dense, mid-brown hardwood, so near the top of that.
        return rough(0.5, "solar absorptance 0.5: wood measured 0.31-0.57 (Kim et al., inverse method), higher for "
                          "dense, darker wood");
    case MaterialPreset::Concrete:
        return rough(0.60, "solar absorptance 0.60 (Engineering ToolBox, concrete; RESNET 0.60 for concrete tile)");
    case MaterialPreset::Ceramic:
        // No figure found for alumina; porcelain's.
        return rough(0.50, "solar absorptance 0.50 (Engineering ToolBox, porcelain; none found for alumina)");
    case MaterialPreset::Rubber:
        return rough(0.65, "solar absorptance 0.65 (Engineering ToolBox, soft grey rubber)");
    }
    return rough(1.0, "unknown material: taken as black");
}

OpticalProperties groundOpticalProperties() { return opticalProperties(MaterialPreset::Concrete); }

} // namespace banjo::optics
