"""Lossless canonical-grid box encoding shared by admission and native trials.

A box is a compact cell-set encoding, NOT a cheaper mechanical model.
"""
from __future__ import annotations

Grid = tuple[int, int, int]
Box = tuple[Grid, Grid]
MAX_SCENE_BOXES = 240
MAX_SCENE_CELLS = 16000

def decompose_cells(cells: set[Grid]) -> list[Box]:
    """Greedy exact rectangular decomposition; every input cell appears once."""
    left = set(cells)
    boxes: list[Box] = []
    while left:
        x0, y0, z0 = min(left)
        x1 = x0
        while (x1 + 1, y0, z0) in left:
            x1 += 1

        y1 = y0
        while True:
            ny = y1 + 1
            if all((x, ny, z0) in left for x in range(x0, x1 + 1)):
                y1 = ny
            else:
                break

        z1 = z0
        while True:
            nz = z1 + 1
            if all((x, y, nz) in left
                   for x in range(x0, x1 + 1)
                   for y in range(y0, y1 + 1)):
                z1 = nz
            else:
                break

        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    left.remove((x, y, z))
        boxes.append(((x0, y0, z0), (x1, y1, z1)))
    return boxes


def cells_from_boxes(boxes: list[Box]) -> set[Grid]:
    out: set[Grid] = set()
    for lo, hi in boxes:
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    out.add((x, y, z))
    return out
