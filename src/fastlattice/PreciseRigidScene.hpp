#pragma once

#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <string>
#include <vector>

namespace banjo::fastlattice {
// Exact shapes are a distinct physical representation, not a compressed lattice.
// Internal failure and thermal response are deliberately absent.
//
// A body is made of boxes and cylinders, each turned as it is drawn and each of
// its own material if need be -- an iron axle through oak wheels is one rigid
// wheelset. Parts may overlap, as an axle runs into a wheel's hub: where they
// do, the FIRST part listed owns the shared space (the Workshop's own rule for
// a cell two parts claim), so no matter is counted twice. Parts are given about
// any origin; the body is measured from its material and re-centred on its
// centre of mass, which is where `initial` puts it.
struct PreciseRigidBody {
    std::string name;
    MaterialPreset material{};
    MaterialDefinition made_of;                     // the body's own material, defined
    std::uint32_t color_rgba{0x9fd3ffffU};
    std::vector<RigidCompoundPart> parts;          // about the centre of mass
    std::vector<MaterialPreset> part_materials;     // one per part
    std::vector<std::string> part_names;            // one per part; may be empty strings
    RigidSnapshot initial;
    double mass_kg{};
    double volume_m3{};                            // of the union, overlaps once
    Mat3 inertia{};
    Vec3 dimensions_m{};
    std::string definition_json;
};
std::vector<PreciseRigidBody> readPreciseRigidScene(const std::string &json_array);
} // namespace banjo::fastlattice
