#pragma once

#include "core/Math.hpp"
#include "matter/Lattice.hpp"

#include <span>
#include <vector>

namespace banjo {

// An axis-aligned run of whole cells, inclusive on both ends.
struct VoxelBox {
    GridCoord minimum{};
    GridCoord maximum{};

    [[nodiscard]] unsigned cellCount() const {
        return static_cast<unsigned>(maximum.x - minimum.x + 1) *
               static_cast<unsigned>(maximum.y - minimum.y + 1) *
               static_cast<unsigned>(maximum.z - minimum.z + 1);
    }
};

// Greedy merge of a set of grid cells into as few boxes as this order finds:
// runs along x, then rows into slabs along y, then slabs into blocks along z.
// Every cell is covered exactly once, so a rigid piece built from the result
// has exactly the piece's volume; the count is bounded by the cell count and
// is far below it for compact pieces (a solid block is one box).
[[nodiscard]] std::vector<VoxelBox> mergeCellsIntoBoxes(std::span<const GridCoord> cells);

} // namespace banjo
