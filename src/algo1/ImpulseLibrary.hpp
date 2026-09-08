#pragma once

// Algorithm 1: the precomputed impulse-response library.
//
// Everything in this header is computed once, when the object is created, and
// depends only on the object (plate, cell size, support, material) -- never on
// the strike. That is the point: change the drop height or the strike point and
// the library is reused unchanged; change the plate and it is rebuilt and
// cached on disk.
//
// The library holds three things, in the order the algorithm needs them:
//
//   1. Mass-normalised eigenpairs of the intact lattice, K phi_i = w_i^2 M phi_i
//      with phi^T M phi = I, over the free degrees of freedom. Every mode is an
//      independent oscillator with a closed form, so the elastic wave is never
//      integrated.
//   2. Bond-mode amplitudes a(b,i) = g_b . phi_i / L_b -- "how much mode i
//      strains bond b". g_b is the linearised extension gradient of the bond,
//      six non-zero entries. One dense (bonds x modes) block; the whole screen
//      is one matrix-vector product against it.
//   3. Compliance columns c_b = K^+ g_b for every bond -- "how the whole plate
//      moves when bond b lets go". These are the S*D columns of the Woodbury
//      identity, so a crack update never touches an eigenvector.
//
// K is only positive definite when the lattice has three-dimensional bond
// connectivity. A plate one cell thick at horizon 2 has every bond in the
// mid-plane, so every transverse (out-of-plane) degree of freedom has exactly
// zero stiffness: the library reports those as *mechanism* modes and the caller
// must decide what to do about them. Nothing here hides that.

#include "fracture/ActiveMatter.hpp"
#include "modal/DenseMatrix.hpp"

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace banjo::algo1 {

inline constexpr std::uint32_t kFixedDof = 0xFFFFFFFFU;

// The linearised extension gradient of one bond over the library's free dofs:
// e_b = g_b . u, six non-zero entries (three per end, minus the ends held by
// the support). Entries at held dofs are dropped, exactly as a clamped node
// contributes stiffness to the free end only.
struct BondGradient {
    std::uint32_t dof[6]{kFixedDof, kFixedDof, kFixedDof, kFixedDof, kFixedDof, kFixedDof};
    double value[6]{};
    unsigned count{};
    double stiffness_n_m{};
    double rest_length_m{};
    // The smallest of the bond's three break thresholds; the screen compares
    // its bound against this.
    double break_strain{};
};

struct LibraryOptions {
    // A mode whose omega^2 is at or below this fraction of the largest omega^2
    // carries no elastic restoring force at working precision.
    double rigid_relative_threshold{1.0e-9};
    // Bytes the dense compliance block may occupy. Above it the columns are
    // computed on demand (only the bonds that break ever need one).
    std::size_t compliance_budget_bytes{1024ULL * 1024ULL * 1024ULL};
};

struct LibraryStats {
    std::size_t dofs{}, modes{}, bonds{}, nodes{};
    // Zero-frequency modes that strain no bond (true rigid-body motion) and
    // zero-frequency modes that do strain bonds (mechanisms: the model has no
    // restoring force for them and the linear response is unbounded in time).
    std::size_t rigid_modes{}, mechanism_modes{}, straining_rigid_modes{};
    double assemble_s{}, decompose_s{}, amplitude_s{}, compliance_s{};
    double cache_read_s{}, cache_write_s{}, total_s{};
    bool cached{};
    bool compliance_stored{};
    std::size_t cache_bytes{}, phi_bytes{}, amplitude_bytes{}, compliance_bytes{};
    double omega_max_rad_s{}, omega_min_elastic_rad_s{};
    double fastest_period_s{};
    std::string cache_path;
};

// The library itself. Built from an ActiveMatter and a per-dof free/held mask
// of length 3 * nodes.
class ImpulseLibrary {
public:
    ImpulseLibrary() = default;

    [[nodiscard]] std::size_t dofs() const { return dof_of_free_.size(); }
    [[nodiscard]] std::size_t modes() const { return omega2_.size(); }
    [[nodiscard]] std::size_t bondCount() const { return gradients_.size(); }
    [[nodiscard]] const std::vector<double> &omegaSquared() const { return omega2_; }
    [[nodiscard]] const std::vector<double> &omega() const { return omega_; }
    [[nodiscard]] bool isRigidMode(std::size_t mode) const { return rigid_[mode] != 0U; }
    // phi, dofs x modes, row-major: a field evaluation u = phi q walks rows.
    [[nodiscard]] const modal::DenseMatrix &phi() const { return phi_; }
    // a(b, i), bonds x modes, row-major.
    [[nodiscard]] const modal::DenseMatrix &amplitude() const { return amplitude_; }
    [[nodiscard]] const std::vector<BondGradient> &gradients() const { return gradients_; }
    [[nodiscard]] const std::vector<std::uint32_t> &freeDofOf() const { return free_dof_of_; }
    [[nodiscard]] const std::vector<std::uint32_t> &dofOfFree() const { return dof_of_free_; }
    [[nodiscard]] const std::vector<double> &dofMass() const { return dof_mass_; }
    [[nodiscard]] const std::vector<std::uint8_t> &looseDofs() const { return loose_dof_; }
    [[nodiscard]] const LibraryStats &stats() const { return stats_; }

    // c_b over the free dofs. Returns a pointer into the stored block when the
    // whole set fits the budget, otherwise computes the column into `scratch`
    // and returns that. Never null.
    [[nodiscard]] const double *complianceColumn(std::uint32_t bond, std::vector<double> &scratch) const;
    [[nodiscard]] bool complianceStored() const { return stats_.compliance_stored; }

    // g_b . x for a vector over the free dofs.
    [[nodiscard]] double bondExtension(std::uint32_t bond, const std::vector<double> &field) const;

    // u = K^+ f over the free dofs: the static response to a force, with the
    // null space (mechanisms and rigid-body motion) dropped.
    void staticResponse(const std::vector<double> &force, std::vector<double> &out) const;
    // u = phi q over the free dofs (out is resized).
    void displacement(const std::vector<double> &q, std::vector<double> &out) const;
    // The three components of free node dofs for one node, from q.
    [[nodiscard]] Vec3 nodeDisplacement(const std::vector<double> &q, std::uint32_t node) const;
    [[nodiscard]] Vec3 nodeValue(const std::vector<double> &field, std::uint32_t node) const;
    // qdot += phi_node^T J for an impulse applied at one node.
    void addNodeImpulse(std::vector<double> &qdot, std::uint32_t node, const Vec3 &impulse) const;

    // Build (or load from `cache_dir`, keyed by `key`) and return the library.
    static ImpulseLibrary create(const ActiveMatter &matter,
                                 const std::vector<std::uint8_t> &dof_free,
                                 const LibraryOptions &options,
                                 const std::string &key,
                                 const std::filesystem::path &cache_dir);

    // Dense stiffness over the free dofs, mass-scaled (A = M^-1/2 K M^-1/2).
    // Diagnostics and tests only; O(n^2) memory.
    [[nodiscard]] modal::DenseMatrix assembleScaledStiffness(const ActiveMatter &matter) const;

private:
    void buildTopology(const ActiveMatter &matter, const std::vector<std::uint8_t> &dof_free);
    void decompose(const ActiveMatter &matter);
    void classifyModes();
    void buildAmplitudes();
    void buildCompliance(const LibraryOptions &options);
    [[nodiscard]] bool readCache(const std::filesystem::path &path);
    void writeCache(const std::filesystem::path &path, const std::string &key);

    std::vector<std::uint32_t> free_dof_of_;  // 3*nodes -> free index or kFixedDof
    std::vector<std::uint32_t> dof_of_free_;  // free index -> 3*node + axis
    std::vector<double> dof_mass_;            // free index -> node mass
    std::vector<std::uint8_t> loose_dof_;     // 1 when no live bond gives the dof any stiffness
    std::vector<double> omega2_, omega_;
    std::vector<std::uint8_t> rigid_;
    modal::DenseMatrix phi_;
    modal::DenseMatrix amplitude_;
    modal::DenseMatrix compliance_;           // bonds x dofs, row b = c_b
    std::vector<BondGradient> gradients_;
    LibraryStats stats_{};
    LibraryOptions options_{};
};

// A stable identity for the cache: everything the library depends on and
// nothing else. The strike is deliberately absent.
[[nodiscard]] std::string libraryKey(const std::string &material, unsigned nx, unsigned ny, unsigned nz,
                                     double cell_m, unsigned horizon, std::uint64_t seed,
                                     const std::string &support, double ledge_width_m);

} // namespace banjo::algo1
