#pragma once

#include "fracture/ActiveMatter.hpp"
#include "modal/SymmetricEigen.hpp"

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

namespace banjo::modal {

struct ModalBasisOptions {
    // A mode whose omega^2 is at or below this fraction of the lattice's
    // largest omega^2 at creation is treated as rigid (zero frequency) and
    // evolves as free motion. Roundoff on a spectrum that spans 1e14 rad^2/s^2
    // leaves rigid modes at ~1e-2, and no elastic mode of a tile sits within
    // nine decades of the fastest one.
    double rigid_relative_threshold{1e-9};
    // Keep only this fraction of the modes (the lowest frequencies) after each
    // decomposition. 1 keeps the exact basis. Below 1 the basis is a reduced
    // model: evolution stays exact within the retained span, but the strain
    // field and every update are truncated. This is the low-rank axis of the
    // research question and exists to be measured, not to be shipped.
    double retained_fraction{1.0};
};

struct ModalBuildTimings {
    double assemble_s{};
    double decompose_s{};
};

// One linearised extension gradient of a bond over the free degrees of
// freedom: up to six non-zero entries (three per free end).
struct BondGradient {
    std::uint32_t dof[6]{};
    double value[6]{};
    unsigned count{};
    double stiffness_n_m{};
};

// The linearised elastic system of one ActiveMatter about its reference
// configuration, restricted to its free nodes and diagonalised:
//     K phi_i = omega_i^2 M phi_i,  phi^T M phi = I.
// A bond touching a fixed node contributes stiffness to its free end only.
// The basis is built once from the bonds alive at construction and can be
// downdated one bond at a time when the shared criterion breaks a bond, or
// rebuilt from scratch as a validation baseline.
//
// Storage is phi itself (dofs x modes, row-major), so a field evaluation
// u = phi q walks contiguous rows and a bond's perturbation z = phi^T g needs
// only the six rows the bond touches. Column order is creation order and is
// not re-sorted after updates; omegaSquared()[k] belongs to column k.
class ModalBasis {
public:
    static constexpr std::uint32_t kFixed = std::numeric_limits<std::uint32_t>::max();

    ModalBasis(const ActiveMatter &matter, std::vector<std::uint32_t> free_nodes,
               const ModalBasisOptions &options = {}, ModalBuildTimings *timings = nullptr);

    [[nodiscard]] std::size_t dofs() const { return 3U * free_nodes_.size(); }
    [[nodiscard]] std::size_t modes() const { return omega2_.size(); }
    [[nodiscard]] bool truncated() const { return omega2_.size() < dofs(); }
    [[nodiscard]] const std::vector<std::uint32_t> &freeNodes() const { return free_nodes_; }
    // kFixed when the node is not free.
    [[nodiscard]] std::uint32_t freeIndexOf(std::uint32_t node) const { return free_index_[node]; }
    [[nodiscard]] const std::vector<double> &freeNodeMasses() const { return mass_; }
    [[nodiscard]] const std::vector<double> &omegaSquared() const { return omega2_; }
    [[nodiscard]] double omegaSquaredMaxAtCreation() const { return omega2_max_creation_; }
    [[nodiscard]] double rigidThreshold() const { return rigid_threshold_; }
    [[nodiscard]] bool isRigidMode(std::size_t mode) const { return omega2_[mode] <= rigid_threshold_; }
    [[nodiscard]] std::size_t rigidModeCount() const;
    [[nodiscard]] const DenseMatrix &phi() const { return phi_; }

    // Linearised extension gradient and stiffness of a bond (from the rest
    // geometry the criterion also uses).
    [[nodiscard]] BondGradient bondGradient(const ActiveMatter &matter, std::uint32_t bond) const;

    // Rank-one downdate: remove the bond's stiffness from the basis. Every
    // vector in co_transform is a modal-coordinate state (q, qdot, modal
    // force) and is rotated into the new basis so its physical meaning is
    // unchanged. The bond's aliveness in `matter` is not touched here.
    RankOneUpdateStats removeBond(const ActiveMatter &matter, std::uint32_t bond,
                                  const std::vector<std::vector<double> *> &co_transform);

    // Full re-decomposition for the bonds currently alive in `matter`.
    // Co-transformed states are re-projected through physical space.
    void rebuild(const ActiveMatter &matter, const std::vector<std::vector<double> *> &co_transform,
                 ModalBuildTimings *timings = nullptr);

    // u = phi q over the free dofs.
    void displacement(const std::vector<double> &q, std::vector<double> &u) const;
    // q = phi^T M x for a physical vector x over the free dofs (position or velocity).
    void project(const std::vector<double> &x, std::vector<double> &q) const;
    // q = phi^T x for a physical force/impulse vector x over the free dofs.
    void projectForce(const std::vector<double> &x, std::vector<double> &q) const;
    // The displacement of free node `node_free` for modal amplitudes q.
    [[nodiscard]] Vec3 nodeDisplacement(const std::vector<double> &q, std::uint32_t node_free) const;
    // Add an impulse applied at a free node to the modal velocity: qdot += phi_node^T J.
    void addNodeImpulse(std::vector<double> &qdot, std::uint32_t node_free, const Vec3 &impulse) const;

    // Dense stiffness assembled for the live bonds (mass-scaled A = M^-1/2 K M^-1/2).
    // Diagnostics only.
    [[nodiscard]] DenseMatrix assembleScaledStiffness(const ActiveMatter &matter) const;
    // Residual of the stored basis against a freshly assembled matrix. O(n^3).
    [[nodiscard]] double residualAgainst(const ActiveMatter &matter) const;
    [[nodiscard]] double orthogonalityDefect() const;

private:
    void decompose(const ActiveMatter &matter, ModalBuildTimings *timings);

    std::vector<std::uint32_t> free_nodes_;
    std::vector<std::uint32_t> free_index_;
    std::vector<double> mass_;
    std::vector<double> omega2_;
    DenseMatrix phi_;
    double omega2_max_creation_{};
    double rigid_threshold_{};
    ModalBasisOptions options_;
};

} // namespace banjo::modal
