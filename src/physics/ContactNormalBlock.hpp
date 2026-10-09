#pragma once

#include <array>

namespace banjo {

// Frozen unilateral patch: min 1/2 lambda^T K lambda + q^T lambda,
// lambda >= 0. K = J M^-1 J^T (1/kg), q in m/s, lambda in N s.
// Four coplanar points generally give a rank-three K. Do not regularize it.
// Prepared principal pseudoinverses can be reused by reference callers. This
// analytical primitive is not admitted into the current native contact solve.
class ContactNormalBlock {
public:
    ContactNormalBlock() = default;
    ContactNormalBlock(const std::array<double,16> &k, unsigned points);
    std::array<double,4> solve(const std::array<double,4> &q) const;
    const std::array<double,16> &matrix() const { return k_; }
    unsigned points() const { return points_; }
private:
    unsigned points_{};
    std::array<double,16> k_{};
    std::array<std::array<double,16>,16> inverse_{};
};

}
