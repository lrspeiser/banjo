#pragma once
#include "fracture/ActiveMatter.hpp"
#include <span>
#include <vector>

namespace banjo {
// A declared local, three-dimensional translational material support. The
// caller owns connectivity/region selection. This is an affine surface-traction
// reduction, not a new constitutive law, cell-spin DOF or rigid projection.
struct MaterialContactStencil {
    ActiveNodeState point; // Virtual contact mass/velocity at the actual surface.
    std::vector<double> weights;
};
// Minimum kinetic-norm affine weights: sum(w)=1 and sum(w*x)=surface. Small
// signed extrapolation admits a face outside the cell-centre convex hull.
// 4..64 movable nodes, <=100 m local radius, <=3 radii extrapolation, |w|<=4.
// Rank-deficient/clamped/spinning/nonfinite inputs explicitly refuse.
[[nodiscard]] MaterialContactStencil makeMaterialContactStencil(
    std::span<const ActiveNodeState> nodes,Vec3 surface_world_m);
// Actual nodal impulse updates, preserving positions/history/masses. The
// virtual work identity and force/moment reproduction are validated at build.
[[nodiscard]] std::vector<Vec3> materialContactVelocities(
    std::span<const ActiveNodeState> nodes,const MaterialContactStencil &stencil,
    Vec3 impulse_n_s);
}
