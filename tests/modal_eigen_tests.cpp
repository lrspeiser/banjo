// The dense symmetric eigensolver and the rank-one eigen-update that the modal
// fracture lane rests on. Everything here is checked against the matrix itself:
// residual |A v - lambda v|, orthonormality, and agreement between an updated
// decomposition and a fresh decomposition of the explicitly modified matrix.

#include "modal/SymmetricEigen.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo::modal;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

DenseMatrix randomSymmetric(std::size_t n, std::uint64_t seed, double spectrum_scale) {
    std::mt19937_64 engine(seed);
    std::normal_distribution<double> normal;
    DenseMatrix a(n, n);
    for (std::size_t i = 0; i < n; ++i)
        for (std::size_t j = i; j < n; ++j) {
            const double value = normal(engine) * spectrum_scale;
            a(i, j) = value;
            a(j, i) = value;
        }
    return a;
}

std::vector<double> sorted(std::vector<double> values) {
    std::sort(values.begin(), values.end());
    return values;
}

void decompositionIsExact() {
    for (const std::size_t n : {std::size_t{1}, std::size_t{2}, std::size_t{3}, std::size_t{7},
                                std::size_t{40}, std::size_t{150}}) {
        const auto a = randomSymmetric(n, 11U + n, 3.0);
        const auto d = decomposeSymmetric(a);
        require(decompositionResidual(a, d) < 1e-13, "eigen residual at n=" + std::to_string(n));
        require(orthogonalityDefect(d.vectors) < 1e-12, "eigenvector orthogonality at n=" + std::to_string(n));
        for (std::size_t k = 1; k < n; ++k)
            require(d.values[k - 1] <= d.values[k], "eigenvalues ascend");
    }
    // A stiffness-like matrix with an exact null space and a wide spread.
    const std::size_t n = 60;
    DenseMatrix k(n, n);
    for (std::size_t i = 0; i + 1 < n; ++i) {
        const double stiffness = 1e8 * (1.0 + 0.5 * std::sin(static_cast<double>(i)));
        k(i, i) += stiffness; k(i + 1, i + 1) += stiffness;
        k(i, i + 1) -= stiffness; k(i + 1, i) -= stiffness;
    }
    const auto d = decomposeSymmetric(k);
    require(std::abs(d.values.front()) < 1e-6 * d.values.back(), "chain null mode is numerically zero");
    require(decompositionResidual(k, d) < 1e-13, "stiff chain residual");
}

void rankOneUpdateMatchesRecomputation() {
    std::mt19937_64 engine(5);
    std::normal_distribution<double> normal;
    for (const double rho : {2.5, -0.75}) {
        const std::size_t n = 90;
        const auto a = randomSymmetric(n, 21, 1.0);
        auto d = decomposeSymmetric(a);
        std::vector<double> x(n);
        for (double &value : x) value = normal(engine);
        std::vector<double> z(n, 0.0);
        for (std::size_t k = 0; k < n; ++k)
            for (std::size_t r = 0; r < n; ++r) z[k] += d.vectors(r, k) * x[r];
        std::vector<double> state(n);
        for (double &value : state) value = normal(engine);
        std::vector<double> physical_before(n, 0.0);
        for (std::size_t r = 0; r < n; ++r)
            for (std::size_t k = 0; k < n; ++k) physical_before[r] += d.vectors(r, k) * state[k];
        const auto stats = updateRankOne(d.values, d.vectors, rho, z, {&state});
        DenseMatrix modified = a;
        for (std::size_t i = 0; i < n; ++i)
            for (std::size_t j = 0; j < n; ++j) modified(i, j) += rho * x[i] * x[j];
        require(decompositionResidual(modified, d) < 1e-12, "updated decomposition satisfies the modified matrix");
        require(orthogonalityDefect(d.vectors) < 1e-12, "updated vectors stay orthonormal");
        const auto fresh = decomposeSymmetric(modified);
        const auto updated = sorted(d.values);
        for (std::size_t k = 0; k < n; ++k)
            require(std::abs(updated[k] - fresh.values[k]) < 1e-11 * (1.0 + std::abs(fresh.values[k])),
                    "updated eigenvalues match a fresh decomposition");
        for (std::size_t r = 0; r < n; ++r) {
            double after = 0.0;
            for (std::size_t k = 0; k < n; ++k) after += d.vectors(r, k) * state[k];
            require(std::abs(after - physical_before[r]) < 1e-11,
                    "co-transformed state is invariant in physical space");
        }
        std::cout << "  rho=" << rho << " retained=" << stats.retained << " deflated_small=" << stats.deflated_small
                  << " deflated_equal=" << stats.deflated_equal << " secular_iterations=" << stats.secular_iterations
                  << " residual=" << stats.secular_residual << '\n';
    }
}

// A sparse perturbation on a matrix with a repeated spectrum exercises both
// deflation paths.
void deflationPathsAreExercised() {
    const std::size_t n = 48;
    DenseMatrix a(n, n);
    for (std::size_t b = 0; b < n / 3; ++b) {
        const double block[3][3] = {{4.0, 1.0, 0.5}, {1.0, 3.0, 0.25}, {0.5, 0.25, 2.0}};
        for (std::size_t i = 0; i < 3; ++i)
            for (std::size_t j = 0; j < 3; ++j) a(3 * b + i, 3 * b + j) = block[i][j];
    }
    auto d = decomposeSymmetric(a);
    std::vector<double> x(n, 0.0);
    x[4] = 1.0; x[5] = -0.5;
    std::vector<double> z(n, 0.0);
    for (std::size_t k = 0; k < n; ++k)
        for (std::size_t r = 0; r < n; ++r) z[k] += d.vectors(r, k) * x[r];
    const auto stats = updateRankOne(d.values, d.vectors, -1.5, z);
    require(stats.deflated_small + stats.deflated_equal > 0, "repeated spectrum deflates");
    require(stats.retained <= 3, "a two-node perturbation of a block matrix retains at most three modes");
    DenseMatrix modified = a;
    for (std::size_t i = 0; i < n; ++i)
        for (std::size_t j = 0; j < n; ++j) modified(i, j) -= 1.5 * x[i] * x[j];
    require(decompositionResidual(modified, d) < 1e-12, "deflated update still satisfies the modified matrix");
    require(orthogonalityDefect(d.vectors) < 1e-12, "deflated update keeps orthonormality");
    std::cout << "  block matrix: retained=" << stats.retained << " deflated_small=" << stats.deflated_small
              << " deflated_equal=" << stats.deflated_equal << '\n';
}

// Sixty sequential bond downdates of a stiffness-like matrix, the operation
// the fracture cascade performs. Orthogonality and residual must not drift.
void sequentialDowndatesDoNotDrift() {
    const std::size_t nodes = 40, n = 2 * nodes;
    struct Bond { std::size_t a, b; double k; double gx, gy; };
    std::vector<Bond> bonds;
    std::mt19937_64 engine(9);
    std::uniform_real_distribution<double> uniform(0.5, 1.5);
    for (std::size_t i = 0; i + 1 < nodes; ++i) {
        bonds.push_back({i, i + 1, 1e6 * uniform(engine), 1.0, 0.0});
        if (i + 2 < nodes) bonds.push_back({i, i + 2, 5e5 * uniform(engine), 0.8, 0.6});
        bonds.push_back({i, i + 1, 3e5 * uniform(engine), 0.0, 1.0});
    }
    const auto assemble = [&](const std::vector<char> &alive) {
        DenseMatrix k(n, n);
        for (std::size_t b = 0; b < bonds.size(); ++b) {
            if (!alive[b]) continue;
            const auto &bond = bonds[b];
            const double g[4] = {-bond.gx, -bond.gy, bond.gx, bond.gy};
            const std::size_t idx[4] = {2 * bond.a, 2 * bond.a + 1, 2 * bond.b, 2 * bond.b + 1};
            for (std::size_t i = 0; i < 4; ++i)
                for (std::size_t j = 0; j < 4; ++j) k(idx[i], idx[j]) += bond.k * g[i] * g[j];
        }
        return k;
    };
    std::vector<char> alive(bonds.size(), 1);
    auto d = decomposeSymmetric(assemble(alive));
    std::uniform_int_distribution<std::size_t> pick(0, bonds.size() - 1);
    std::size_t removed = 0;
    double worst_orthogonality = 0.0, worst_residual = 0.0, worst_value_error = 0.0;
    while (removed < 60) {
        const std::size_t b = pick(engine);
        if (!alive[b]) continue;
        alive[b] = 0;
        ++removed;
        const auto &bond = bonds[b];
        std::vector<double> x(n, 0.0);
        x[2 * bond.a] = -bond.gx; x[2 * bond.a + 1] = -bond.gy;
        x[2 * bond.b] = bond.gx; x[2 * bond.b + 1] = bond.gy;
        std::vector<double> z(n, 0.0);
        for (std::size_t k = 0; k < n; ++k)
            for (const std::size_t r : {2 * bond.a, 2 * bond.a + 1, 2 * bond.b, 2 * bond.b + 1})
                z[k] += d.vectors(r, k) * x[r];
        updateRankOne(d.values, d.vectors, -bond.k, z);
        if (removed % 10 == 0) {
            const auto k = assemble(alive);
            worst_orthogonality = std::max(worst_orthogonality, orthogonalityDefect(d.vectors));
            worst_residual = std::max(worst_residual, decompositionResidual(k, d));
            const auto fresh = decomposeSymmetric(k);
            const auto updated = sorted(d.values);
            for (std::size_t i = 0; i < n; ++i)
                worst_value_error = std::max(worst_value_error,
                    std::abs(updated[i] - fresh.values[i]) / std::max(1.0, std::abs(fresh.values.back())));
        }
    }
    std::cout << "  60 sequential downdates: orthogonality " << worst_orthogonality
              << " residual " << worst_residual << " value error " << worst_value_error << '\n';
    require(worst_orthogonality < 1e-11, "sequential downdates keep orthonormality");
    require(worst_residual < 1e-11, "sequential downdates keep the residual");
    require(worst_value_error < 1e-11, "sequential downdates keep the spectrum");
}

void productAgreesWithNaive() {
    const auto a = randomSymmetric(37, 3, 1.0);
    const auto b = randomSymmetric(37, 4, 1.0);
    DenseMatrix out;
    multiplyInto(a, b, out);
    for (std::size_t i = 0; i < 37; ++i)
        for (std::size_t j = 0; j < 37; ++j) {
            double sum = 0.0;
            for (std::size_t k = 0; k < 37; ++k) sum += a(i, k) * b(k, j);
            require(std::abs(sum - out(i, j)) < 1e-12, "dense product");
        }
}

} // namespace

int main() {
    try {
        decompositionIsExact();
        std::cout << "[PASS] symmetric decomposition: residual, orthonormality and order\n";
        rankOneUpdateMatchesRecomputation();
        std::cout << "[PASS] rank-one update and downdate match a fresh decomposition\n";
        deflationPathsAreExercised();
        std::cout << "[PASS] small-component and equal-eigenvalue deflation\n";
        sequentialDowndatesDoNotDrift();
        std::cout << "[PASS] sixty sequential bond downdates do not drift\n";
        productAgreesWithNaive();
        std::cout << "[PASS] dense product\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
