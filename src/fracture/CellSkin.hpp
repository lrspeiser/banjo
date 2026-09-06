#pragma once
#include "core/Math.hpp"
#include <array>
#include <cstdint>
#include <span>
#include <vector>

namespace banjo {
struct SkinCell {
    std::uint32_t id{},component{};
    std::array<int,3> grid{};
    Vec3 reference_center_m{},center_world_m{};
    // Current half-edge vectors supplied by the physical representation.
    std::array<Vec3,3> half_axes_world_m{};
};
struct SkinFaceLink {std::uint32_t a{},b{};bool live{};}; // stable cell IDs
struct SkinFace {
    unsigned cell_index{},component{},axis{};bool positive{},fracture{};
    std::array<unsigned,4> corners{}; // shared vertex indices, outward winding
};
struct CellSkinTopology {
    std::uint64_t revision{};
    unsigned vertex_count{};
    std::vector<std::uint32_t> cell_ids;
    std::vector<std::uint32_t> components;
    std::vector<std::array<int,3>> grids;
    std::vector<std::array<unsigned,8>> corner_vertices;
    std::vector<SkinFace> faces;
};
struct CellSkinTriangle {
    std::array<Vec3,3> positions_world_m;
    unsigned component{},source_cell{};
    bool fracture_surface{};
};
struct CellSkinMesh {
    std::uint64_t revision{};
    unsigned exposed_faces{},fracture_faces{};
    std::vector<CellSkinTriangle> triangles;
};
// Bounded, blocky render-only skin. Rebuild topology on accepted face-link or
// component changes; evaluate positions on motion without rebuilding topology.
// Does not mutate physics or invent fracture/forces. No smooth-surface claim.
CellSkinTopology buildCellSkinTopology(std::span<const SkinCell> cells,
    std::span<const SkinFaceLink> face_links,std::uint64_t revision);
CellSkinMesh evaluateCellSkin(const CellSkinTopology &topology,std::span<const SkinCell> cells);
}
