// Plate bending for matter one cell thick (LatticePhysics plateBendingStrain).
//
// A neighbourhood that lies in a plane cannot measure anything through the
// plane, so a sheet one cell thick used to read a blow struck flat at it as
// almost nothing: the strain it could state was the membrane strain, and
// bending is not that. The curvature of the sheet is recoverable from how far
// each neighbour has moved out of the plane, and a plate of thickness h strains
// its outermost fibre by (h/2) times that curvature.
//
// What these checks pin, in the order they matter:
//
//   1. a rigid motion produces NO bending strain, at every node including the
//      edges and corners -- the property the in-plane projection was written to
//      protect, and the one a curvature fitted carelessly destroys first;
//   2. a sheet bent to a known curvature reports that curvature's strain;
//   3. it is the tensile fibre that is reported, whichever way the sheet's
//      stored normal happens to point;
//   4. matter two cells thick is left exactly alone, because it measures its
//      own bending and needs none of this.

#include "fastlattice/LatticePhysics.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo::fastlattice;
using banjo::fastlattice::V3;

void require(bool ok, const std::string &what) {
    if (!ok) throw std::runtime_error(what);
}

void close(double got, double want, double tolerance, const std::string &what) {
    if (!(std::fabs(got - want) <= tolerance))
        throw std::runtime_error(what + ": " + std::to_string(got) + " against " +
                                 std::to_string(want) + " (tolerance " +
                                 std::to_string(tolerance) + ")");
}

// A block of nodes on a cubic grid, bonded to every neighbour within two cells,
// which is the reach the world's own lattice uses. `layers` of 1 is a sheet one
// cell thick; 3 is solid matter that measures its own bending.
struct Block {
    static constexpr double kCell = 0.02;
    int across, layers;
    std::vector<double> x0, u, rinv, strain, node_unmeasured, nbr_rest, nbr_weight;
    std::vector<std::uint8_t> node_valid, node_dirty, nbr_alive;
    std::vector<std::uint32_t> nbr_bond, nbr_other;
    std::uint32_t max_degree = 0;

    Block(int across_in, int layers_in) : across(across_in), layers(layers_in) {
        const std::uint32_t n = count();
        for (int y = 0; y < layers; ++y)
            for (int z = 0; z < across; ++z)
                for (int x = 0; x < across; ++x) {
                    x0.push_back(x * kCell);
                    x0.push_back(y * kCell);
                    x0.push_back(z * kCell);
                }
        u.assign(3 * n, 0.0);
        rinv.assign(9 * n, 0.0);
        strain.assign(6 * n, 0.0);
        node_unmeasured.assign(3 * n, 0.0);
        node_valid.assign(n, 0);
        node_dirty.assign(n, 1);

        // Every pair within two cells, both ways round.
        std::vector<std::vector<std::uint32_t>> neighbours(n);
        for (std::uint32_t a = 0; a < n; ++a)
            for (std::uint32_t b = 0; b < n; ++b) {
                if (a == b) continue;
                const double dx = x0[3 * b] - x0[3 * a];
                const double dy = x0[3 * b + 1] - x0[3 * a + 1];
                const double dz = x0[3 * b + 2] - x0[3 * a + 2];
                const double d2 = dx * dx + dy * dy + dz * dz;
                if (d2 <= (2.0 * kCell) * (2.0 * kCell) + 1e-12) neighbours[a].push_back(b);
            }
        for (const auto &list : neighbours)
            max_degree = std::max<std::uint32_t>(max_degree, static_cast<std::uint32_t>(list.size()));

        nbr_bond.assign(static_cast<std::size_t>(max_degree) * n, kNoBond);
        nbr_other.assign(static_cast<std::size_t>(max_degree) * n, 0);
        nbr_rest.assign(3 * static_cast<std::size_t>(max_degree) * n, 0.0);
        nbr_weight.assign(static_cast<std::size_t>(max_degree) * n, 0.0);
        nbr_alive.assign(static_cast<std::size_t>(max_degree) * n, 0);
        std::uint32_t bond = 0;
        for (std::uint32_t a = 0; a < n; ++a)
            for (std::size_t k = 0; k < neighbours[a].size(); ++k) {
                const std::uint32_t b = neighbours[a][k];
                const std::size_t slot = k * n + a;
                nbr_bond[slot] = bond++;
                nbr_other[slot] = b;
                const double dx = x0[3 * b] - x0[3 * a];
                const double dy = x0[3 * b + 1] - x0[3 * a + 1];
                const double dz = x0[3 * b + 2] - x0[3 * a + 2];
                nbr_rest[3 * slot] = dx;
                nbr_rest[3 * slot + 1] = dy;
                nbr_rest[3 * slot + 2] = dz;
                nbr_weight[slot] = 1.0 / (dx * dx + dy * dy + dz * dz);
                nbr_alive[slot] = 1;
            }
    }

    [[nodiscard]] std::uint32_t count() const {
        return static_cast<std::uint32_t>(across) * static_cast<std::uint32_t>(across) *
               static_cast<std::uint32_t>(layers);
    }
    [[nodiscard]] std::uint32_t at(int x, int y, int z) const {
        return static_cast<std::uint32_t>(x + across * z + across * across * y);
    }

    LatticeArrays<double> arrays() {
        LatticeArrays<double> L{};
        L.node_count = count();
        L.max_degree = max_degree;
        L.x0 = x0.data();
        L.u = u.data();
        L.rinv = rinv.data();
        L.strain = strain.data();
        L.node_unmeasured = node_unmeasured.data();
        L.node_valid = node_valid.data();
        L.node_dirty = node_dirty.data();
        L.nbr_bond = nbr_bond.data();
        L.nbr_other = nbr_other.data();
        L.nbr_rest = nbr_rest.data();
        L.nbr_weight = nbr_weight.data();
        L.nbr_alive = nbr_alive.data();
        L.rank_deficient_nodes = nullptr;
        return L;
    }

    // Every node's strain, with plate bending on or off. A yield of zero is a
    // material that cannot yield, which is what every brittle one compiles to.
    std::vector<double> strainsWith(double half_thickness, double yield = 0.0) {
        node_dirty.assign(count(), 1);
        strain.assign(6 * count(), 0.0);
        LatticeArrays<double> L = arrays();
        for (std::uint32_t i = 0; i < L.node_count; ++i)
            nodeStrain<double>(L, i, /*direct=*/false, half_thickness, yield);
        return strain;
    }

    void moveEachNode(const std::function<void(double, double, double, double *)> &put) {
        for (std::uint32_t i = 0; i < count(); ++i)
            put(x0[3 * i], x0[3 * i + 1], x0[3 * i + 2], &u[3 * i]);
    }
};

// The largest absolute difference between two strain fields.
double worstGap(const std::vector<double> &a, const std::vector<double> &b) {
    double worst = 0.0;
    for (std::size_t k = 0; k < a.size() && k < b.size(); ++k)
        worst = std::max(worst, std::fabs(a[k] - b[k]));
    return worst;
}

double worst(const std::vector<double> &a) {
    double out = 0.0;
    for (const double v : a) out = std::max(out, std::fabs(v));
    return out;
}

// 1. A rigid motion is not a strain, and must not become one.
void aRigidMotionBendsNothing() {
    for (const double angle : {0.0, 0.05, 0.3, 1.0}) {
        Block sheet(7, 1);
        const double c = std::cos(angle), s = std::sin(angle);
        // A turn about z, which tips the sheet's plane out of its rest plane,
        // plus a translation. Every node moves; none of it is deformation.
        sheet.moveEachNode([&](double x, double y, double z, double *out) {
            out[0] = (c * x - s * y) - x + 0.031;
            out[1] = (s * x + c * y) - y - 0.017;
            out[2] = 0.0 * z + 0.004;
        });
        const std::vector<double> without = sheet.strainsWith(0.0);
        const std::vector<double> with = sheet.strainsWith(Block::kCell / 2);
        require(worst(without) < 1e-12,
                "a rigid motion strains nothing even before plate bending (angle " +
                    std::to_string(angle) + "): " + std::to_string(worst(without)));
        require(worstGap(without, with) < 1e-12,
                "a rigid motion must add no bending strain (angle " + std::to_string(angle) +
                    "): " + std::to_string(worstGap(without, with)));
    }
    std::cout << "  a rigid motion bends nothing\n";
}

// 2. A sheet bent to a known curvature reports (h/2) * curvature.
void aKnownCurvatureIsReported() {
    const double kappa = 0.8;          // 1/m, a gentle bow over a 120 mm sheet
    Block sheet(7, 1);
    // y = (1/2) kappa x^2: cylindrical bending about z, curved along x only.
    sheet.moveEachNode([&](double x, double, double, double *out) {
        const double from_middle = x - 3 * Block::kCell;
        out[0] = 0.0;
        out[1] = 0.5 * kappa * from_middle * from_middle;
        out[2] = 0.0;
    });
    const std::vector<double> without = sheet.strainsWith(0.0);
    const std::vector<double> with = sheet.strainsWith(Block::kCell / 2);

    // The middle node, whose neighbourhood is symmetric, is the one the fit is
    // exact at. Its bending strain is (h/2) * kappa along x and nothing across.
    const std::uint32_t middle = sheet.at(3, 0, 3);
    const double want = (Block::kCell / 2) * kappa;
    close(with[6 * middle] - without[6 * middle], want, 1e-9 + 1e-6 * want,
          "bending strain along the curved axis");
    close(with[6 * middle + 2] - without[6 * middle + 2], 0.0, 1e-9,
          "bending strain across the curved axis");
    close(with[6 * middle + 4] - without[6 * middle + 4], 0.0, 1e-9,
          "bending shear on a cylindrically bent sheet");
    // And nowhere in the sheet is it wildly more than the middle: an edge node
    // has fewer neighbours and a poorer fit, not a different answer.
    for (std::uint32_t i = 0; i < sheet.count(); ++i)
        require(std::fabs(with[6 * i] - without[6 * i]) < 3.0 * want,
                "an edge node's bending strain stays the same size as the middle's");
    std::cout << "  a known curvature is reported, " << want << " at the middle\n";
}

// 3. Which face the normal points out of is arbitrary, so the answer may not
//    depend on it: the fibre in tension is the one reported either way.
void theTensileFibreIsTheOneReported() {
    const double kappa = 0.8;
    double along[2] = {0.0, 0.0};
    for (int which = 0; which < 2; ++which) {
        Block sheet(7, 1);
        const double sign = which == 0 ? 1.0 : -1.0;
        sheet.moveEachNode([&](double x, double, double, double *out) {
            const double from_middle = x - 3 * Block::kCell;
            out[0] = 0.0;
            out[1] = sign * 0.5 * kappa * from_middle * from_middle;
            out[2] = 0.0;
        });
        const std::vector<double> without = sheet.strainsWith(0.0);
        const std::vector<double> with = sheet.strainsWith(Block::kCell / 2);
        const std::uint32_t middle = sheet.at(3, 0, 3);
        along[which] = with[6 * middle] - without[6 * middle];
    }
    close(along[0], along[1], 1e-9, "a sheet bowed either way reports the same fibre");
    require(along[0] > 0.0, "the fibre reported is the one in tension");
    std::cout << "  the tensile fibre is reported whichever way it is bowed\n";
}

// 4. Matter two cells thick measures its own bending and must be untouched.
void thickMatterIsLeftAlone() {
    for (const int layers : {2, 3}) {
        Block block(5, layers);
        block.moveEachNode([&](double x, double y, double z, double *out) {
            const double from_middle = x - 2 * Block::kCell;
            out[0] = 0.002 * z;
            out[1] = 0.4 * from_middle * from_middle;
            out[2] = -0.001 * y;
        });
        const std::vector<double> without = block.strainsWith(0.0);
        const std::vector<double> with = block.strainsWith(Block::kCell / 2);
        require(worstGap(without, with) == 0.0,
                "matter " + std::to_string(layers) +
                    " cells thick must be bit-for-bit what it was: " +
                    std::to_string(worstGap(without, with)));
    }
    std::cout << "  matter two and three cells thick is left exactly alone\n";
}

// 5. Stretching a sheet in its own plane is membrane, not bending.
void inPlaneStretchAddsNoBending() {
    Block sheet(7, 1);
    sheet.moveEachNode([&](double x, double, double z, double *out) {
        out[0] = 0.01 * x;
        out[1] = 0.0;
        out[2] = -0.004 * z;
    });
    const std::vector<double> without = sheet.strainsWith(0.0);
    const std::vector<double> with = sheet.strainsWith(Block::kCell / 2);
    require(worst(without) > 1e-4, "the stretch itself is a strain");
    require(worstGap(without, with) < 1e-12,
            "an in-plane stretch must add no bending: " + std::to_string(worstGap(without, with)));
    std::cout << "  an in-plane stretch adds no bending\n";
}

// 6. A material that yields does not go on straining its surface elastically.
//    Past first yield the section yields there and the extra curvature becomes
//    a permanent rotation -- a dent, not a crack. Without this the term drives
//    the failure criterion straight past the yield, and the Workshop's oak,
//    iron and aluminium tables came back "held" because the fibre broke bonds
//    that were then all put back.
void aYieldingMaterialSaturatesAtItsYield() {
    const double kappa = 4.0;                     // far past yield at 10 mm
    const double yield = 0.0012;                  // about iron's, 250 MPa / 211 GPa
    Block sheet(7, 1);
    sheet.moveEachNode([&](double x, double, double, double *out) {
        const double from_middle = x - 3 * Block::kCell;
        out[0] = 0.0;
        out[1] = 0.5 * kappa * from_middle * from_middle;
        out[2] = 0.0;
    });
    const std::vector<double> without = sheet.strainsWith(0.0);
    const std::vector<double> brittle = sheet.strainsWith(Block::kCell / 2);
    const std::vector<double> ductile = sheet.strainsWith(Block::kCell / 2, yield);
    const std::uint32_t middle = sheet.at(3, 0, 3);

    const double unheld = brittle[6 * middle] - without[6 * middle];
    const double capped = ductile[6 * middle] - without[6 * middle];
    close(unheld, (Block::kCell / 2) * kappa, 1e-6, "a material that cannot yield takes it all");
    close(capped, yield, 1e-9, "a material that yields stops at its yield");
    require(capped < unheld, "the cap is doing something at this curvature");
    // And it is a cap, not a scaling: a gentle bow well under the yield is
    // reported whole, whatever the material can do afterwards.
    Block gentle(7, 1);
    const double small = 0.05;                    // (h/2) * kappa = 5e-4, under the yield
    gentle.moveEachNode([&](double x, double, double, double *out) {
        const double from_middle = x - 3 * Block::kCell;
        out[0] = 0.0;
        out[1] = 0.5 * small * from_middle * from_middle;
        out[2] = 0.0;
    });
    const std::vector<double> loose = gentle.strainsWith(Block::kCell / 2);
    const std::vector<double> held = gentle.strainsWith(Block::kCell / 2, yield);
    close(held[6 * middle], loose[6 * middle], 1e-12,
          "under its yield a bow is reported whole");
    std::cout << "  a yielding material saturates at its yield, " << yield
              << " against " << unheld << " uncapped\n";
}

}  // namespace

int main() {
    try {
        aRigidMotionBendsNothing();
        aKnownCurvatureIsReported();
        theTensileFibreIsTheOneReported();
        thickMatterIsLeftAlone();
        inPlaneStretchAddsNoBending();
        aYieldingMaterialSaturatesAtItsYield();
    } catch (const std::exception &error) {
        std::cerr << "plate bending: " << error.what() << "\n";
        return 1;
    }
    std::cout << "plate bending: every check passed\n";
    return 0;
}
