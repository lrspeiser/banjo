#pragma once

#include "modal/DenseMatrix.hpp"

#include <cstddef>
#include <vector>

namespace banjo::modal {

// Eigen-decomposition of a real symmetric matrix. `values[k]` belongs to column
// k of `vectors`. decomposeSymmetric returns them ascending; a rank-one update
// rewrites values in place, so after updates the order is whatever the columns
// were and callers must not assume it is sorted.
struct SymmetricEigenDecomposition {
    std::vector<double> values;
    DenseMatrix vectors;
};

// Householder tridiagonalisation followed by implicit QL with Wilkinson
// shifts, eigenvectors accumulated. O(n^3), dense, no external library.
[[nodiscard]] SymmetricEigenDecomposition decomposeSymmetric(const DenseMatrix &matrix);

struct RankOneUpdateOptions {
    // A component whose contribution rho*|z_i| (with |z| normalised) is below
    // this multiple of machine epsilon times the spectral scale cannot change
    // the decomposition at working precision; it is deflated. Two retained
    // eigenvalues closer than the same tolerance are rotated so one deflates.
    double deflation_epsilon_multiple{8.0};
    unsigned maximum_secular_iterations{300};
};

struct RankOneUpdateStats {
    std::size_t deflated_small{};
    std::size_t deflated_equal{};
    std::size_t retained{};
    unsigned secular_iterations{};
    // Largest scaled secular residual at an accepted root.
    double secular_residual{};
};

// Replace (values, vectors) by the eigen-decomposition of
//     vectors * diag(values) * vectors^T + rho * x * x^T
// given z = vectors^T x, the perturbation expressed in the current eigenbasis.
// `vectors` may hold fewer columns than rows (a truncated basis); the update
// is then the exact update of the truncated problem, not of the full one.
// rho may be negative (a downdate). Every vector in `co_transform`, expressed
// in the old eigenbasis, is rotated into the new one so modal states survive
// the change of basis unchanged in physical space.
//
// Method: Bunch, Nielsen & Sorensen's secular equation for the eigenvalues,
// then Gu & Eisenstat's reformulation that recomputes the perturbation vector
// from the computed eigenvalues before forming eigenvectors, which keeps the
// new columns orthonormal to working precision without extended arithmetic.
// Cost is O(n * k^2) for k retained (non-deflated) components.
RankOneUpdateStats updateRankOne(
    std::vector<double> &values, DenseMatrix &vectors, double rho,
    const std::vector<double> &z,
    const std::vector<std::vector<double> *> &co_transform = {},
    const RankOneUpdateOptions &options = {});

// out = a * b. Parallel over rows when OpenMP is available.
void multiplyInto(const DenseMatrix &a, const DenseMatrix &b, DenseMatrix &out);

// max |Q^T Q - I| over every pair of columns. O(n^3); diagnostics only.
[[nodiscard]] double orthogonalityDefect(const DenseMatrix &vectors);

// max_k |A v_k - lambda_k v_k| / (|lambda|max or 1). O(n^3); diagnostics only.
[[nodiscard]] double decompositionResidual(
    const DenseMatrix &matrix, const SymmetricEigenDecomposition &decomposition);

} // namespace banjo::modal
