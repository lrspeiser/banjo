#include "fracture/PieceGeometry.hpp"

#include <algorithm>
#include <cstdint>
#include <set>
#include <tuple>

namespace banjo {

std::vector<VoxelBox> mergeCellsIntoBoxes(std::span<const GridCoord> cells) {
    const auto key = [](const GridCoord &c) { return std::make_tuple(c.z, c.y, c.x); };
    std::set<std::tuple<int, int, int>> remaining;
    for (const GridCoord &cell : cells) remaining.insert(key(cell));
    const auto present = [&](int x, int y, int z) { return remaining.contains(std::make_tuple(z, y, x)); };

    std::vector<VoxelBox> boxes;
    while (!remaining.empty()) {
        const auto [z0, y0, x0] = *remaining.begin();
        // Extend along x.
        int x1 = x0;
        while (present(x1 + 1, y0, z0)) ++x1;
        // Extend the row along y while every cell of the next row is present.
        int y1 = y0;
        for (;;) {
            bool full = true;
            for (int x = x0; x <= x1 && full; ++x) full = present(x, y1 + 1, z0);
            if (!full) break;
            ++y1;
        }
        // Extend the slab along z while every cell of the next slab is present.
        int z1 = z0;
        for (;;) {
            bool full = true;
            for (int y = y0; y <= y1 && full; ++y)
                for (int x = x0; x <= x1 && full; ++x) full = present(x, y, z1 + 1);
            if (!full) break;
            ++z1;
        }
        for (int z = z0; z <= z1; ++z)
            for (int y = y0; y <= y1; ++y)
                for (int x = x0; x <= x1; ++x) remaining.erase(std::make_tuple(z, y, x));
        boxes.push_back({{x0, y0, z0}, {x1, y1, z1}});
    }
    return boxes;
}

} // namespace banjo
