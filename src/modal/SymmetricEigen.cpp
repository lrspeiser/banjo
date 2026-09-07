#include "modal/SymmetricEigen.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>
#include <vector>

namespace banjo::modal {
namespace {

constexpr double kEpsilon = std::numeric_limits<double>::epsilon();

// Column-major working storage for the accumulation phase: a mode is
// contiguous, so the Givens rotations of the QL sweep touch two contiguous
// vectors instead of striding across every row.
struct ColumnMajor {
    std::size_t n{};
    std::vector<double> data;
    explicit ColumnMajor(std::size_t size) : n(size), data(size * size, 0.0) {}
    [[nodiscard]] double *column(std::size_t j) { return data.data() + j * n; }
};

// Householder reduction A -> tridiagonal(d, e) with Q accumulated so that
// A = Q T Q^T. `a` is overwritten. e[i] (i >= 1) couples d[i-1] and d[i].
void tridiagonalise(std::vector<double> &a, std::size_t n, std::vector<double> &d,
                    std::vector<double> &e, ColumnMajor &q) {
    d.assign(n, 0.0);
    e.assign(n, 0.0);
    std::vector<std::vector<double>> reflectors(n);
    std::vector<double> betas(n, 0.0);
    std::vector<double> p(n), w(n);
    const auto at = [&](std::size_t i, std::size_t j) -> double & { return a[i * n + j]; };
    for (std::size_t k = 0; k + 2 < n; ++k) {
        const std::size_t m = n - k - 1;
        std::vector<double> v(m);
        double norm2 = 0.0;
        for (std::size_t i = 0; i < m; ++i) {
            v[i] = at(k + 1 + i, k);
            norm2 += v[i] * v[i];
        }
        const double norm = std::sqrt(norm2);
        if (norm == 0.0) {
            e[k + 1] = 0.0;
            continue;
        }
        const double alpha = v[0] >= 0.0 ? -norm : norm;
        v[0] -= alpha;
        double vv = 0.0;
        for (double value : v) vv += value * value;
        const double beta = 2.0 / vv;
        // p = beta * A22 v
        for (std::size_t i = 0; i < m; ++i) {
            double sum = 0.0;
            const double *row = &at(k + 1 + i, k + 1);
            for (std::size_t j = 0; j < m; ++j) sum += row[j] * v[j];
            p[i] = beta * sum;
        }
        double pv = 0.0;
        for (std::size_t i = 0; i < m; ++i) pv += p[i] * v[i];
        for (std::size_t i = 0; i < m; ++i) w[i] = p[i] - 0.5 * beta * pv * v[i];
        for (std::size_t i = 0; i < m; ++i) {
            double *row = &at(k + 1 + i, k + 1);
            const double vi = v[i], wi = w[i];
            for (std::size_t j = 0; j < m; ++j) row[j] -= vi * w[j] + wi * v[j];
        }
        at(k + 1, k) = alpha;
        at(k, k + 1) = alpha;
        for (std::size_t i = 1; i < m; ++i) {
            at(k + 1 + i, k) = 0.0;
            at(k, k + 1 + i) = 0.0;
        }
        e[k + 1] = alpha;
        reflectors[k] = std::move(v);
        betas[k] = beta;
    }
    for (std::size_t i = 0; i < n; ++i) d[i] = at(i, i);
    if (n >= 2) e[n - 1] = at(n - 1, n - 2);
    // Q = H_0 H_1 ... H_{n-3}, accumulated backwards from the identity.
    for (std::size_t j = 0; j < n; ++j) q.column(j)[j] = 1.0;
    for (std::size_t kk = n; kk-- > 0;) {
        const std::size_t k = kk;
        if (k + 2 >= n || reflectors[k].empty()) continue;
        const auto &v = reflectors[k];
        const double beta = betas[k];
        const std::size_t m = v.size();
        for (std::size_t j = 0; j < n; ++j) {
            double *column = q.column(j) + k + 1;
            double s = 0.0;
            for (std::size_t i = 0; i < m; ++i) s += v[i] * column[i];
            s *= beta;
            for (std::size_t i = 0; i < m; ++i) column[i] -= s * v[i];
        }
    }
}

// Implicit QL with Wilkinson shifts on the tridiagonal (d, e). On entry e[i]
// couples d[i-1] and d[i]; it is shifted so e[i] couples d[i] and d[i+1].
// Rotations are accumulated into the columns of z.
void tridiagonalQL(std::vector<double> &d, std::vector<double> &e, ColumnMajor &z) {
    const std::size_t n = d.size();
    if (n == 0) return;
    for (std::size_t i = 1; i < n; ++i) e[i - 1] = e[i];
    e[n - 1] = 0.0;
    for (std::size_t l = 0; l < n; ++l) {
        unsigned iterations = 0;
        while (true) {
            std::size_t m = l;
            for (; m + 1 < n; ++m) {
                const double dd = std::abs(d[m]) + std::abs(d[m + 1]);
                if (std::abs(e[m]) <= kEpsilon * dd) break;
            }
            if (m == l) break;
            if (++iterations > 200) throw std::runtime_error("symmetric QL did not converge");
            double g = (d[l + 1] - d[l]) / (2.0 * e[l]);
            double r = std::hypot(g, 1.0);
            g = d[m] - d[l] + e[l] / (g + (g >= 0.0 ? std::abs(r) : -std::abs(r)));
            double s = 1.0, c = 1.0, p = 0.0;
            std::size_t i = m;
            bool underflow = false;
            while (i-- > l) {
                const double f = s * e[i];
                const double b = c * e[i];
                r = std::hypot(f, g);
                e[i + 1] = r;
                if (r == 0.0) {
                    d[i + 1] -= p;
                    e[m] = 0.0;
                    underflow = true;
                    break;
                }
                s = f / r;
                c = g / r;
                g = d[i + 1] - p;
                r = (d[i] - g) * s + 2.0 * c * b;
                p = s * r;
                d[i + 1] = g + p;
                g = c * r - b;
                double *zi = z.column(i);
                double *zi1 = z.column(i + 1);
                for (std::size_t k = 0; k < n; ++k) {
                    const double t = zi1[k];
                    zi1[k] = s * zi[k] + c * t;
                    zi[k] = c * zi[k] - s * t;
                }
            }
            if (underflow) continue;
            d[l] -= p;
            e[l] = g;
            e[m] = 0.0;
        }
    }
}

// Rotate columns (i, j) of a row-major matrix: col_i' = c col_i + s col_j,
// col_j' = -s col_i + c col_j.
void rotateColumns(DenseMatrix &m, std::size_t i, std::size_t j, double c, double s) {
    for (std::size_t r = 0; r < m.rows; ++r) {
        double *row = m.row(r);
        const double a = row[i], b = row[j];
        row[i] = c * a + s * b;
        row[j] = -s * a + c * b;
    }
}

} // namespace

SymmetricEigenDecomposition decomposeSymmetric(const DenseMatrix &matrix) {
    if (matrix.rows != matrix.cols) throw std::invalid_argument("eigen-decomposition needs a square matrix");
    const std::size_t n = matrix.rows;
    SymmetricEigenDecomposition result;
    result.values.resize(n);
    result.vectors = DenseMatrix(n, n);
    if (n == 0) return result;
    std::vector<double> a = matrix.data;
    for (double value : a)
        if (!std::isfinite(value)) throw std::invalid_argument("eigen-decomposition needs finite entries");
    // Symmetrise exactly so roundoff in the caller's assembly cannot bias one triangle.
    for (std::size_t i = 0; i < n; ++i)
        for (std::size_t j = i + 1; j < n; ++j) {
            const double s = 0.5 * (a[i * n + j] + a[j * n + i]);
            a[i * n + j] = s;
            a[j * n + i] = s;
        }
    std::vector<double> d, e;
    ColumnMajor q(n);
    tridiagonalise(a, n, d, e, q);
    tridiagonalQL(d, e, q);
    std::vector<std::size_t> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](std::size_t x, std::size_t y) { return d[x] < d[y]; });
    for (std::size_t k = 0; k < n; ++k) {
        result.values[k] = d[order[k]];
        const double *column = q.column(order[k]);
        for (std::size_t r = 0; r < n; ++r) result.vectors(r, k) = column[r];
    }
    return result;
}

RankOneUpdateStats updateRankOne(
    std::vector<double> &values, DenseMatrix &vectors, double rho,
    const std::vector<double> &z,
    const std::vector<std::vector<double> *> &co_transform,
    const RankOneUpdateOptions &options) {
    // `vectors` may be rectangular: a truncated basis keeps n columns of a
    // larger space. The update only ever rotates columns.
    const std::size_t n = values.size();
    if (vectors.cols != n || z.size() != n || vectors.rows == 0)
        throw std::invalid_argument("rank-one update needs matching decomposition and vector sizes");
    for (const auto *state : co_transform)
        if (state == nullptr || state->size() != n)
            throw std::invalid_argument("co-transformed state must have one entry per mode");
    if (!std::isfinite(rho)) throw std::invalid_argument("rank-one update needs a finite weight");
    RankOneUpdateStats stats;
    if (n == 0 || rho == 0.0) { stats.deflated_small = n; return stats; }

    std::vector<double> d = values;
    const bool negate = rho < 0.0;
    if (negate) {
        rho = -rho;
        for (double &value : d) value = -value;
    }
    double znorm2 = 0.0;
    for (double value : z) {
        if (!std::isfinite(value)) throw std::invalid_argument("rank-one update vector must be finite");
        znorm2 += value * value;
    }
    if (znorm2 == 0.0) { stats.deflated_small = n; return stats; }
    const double rho_t = rho * znorm2;
    const double inverse_norm = 1.0 / std::sqrt(znorm2);
    std::vector<double> zt(n);
    for (std::size_t i = 0; i < n; ++i) zt[i] = z[i] * inverse_norm;

    double dmax = 0.0;
    for (double value : d) dmax = std::max(dmax, std::abs(value));
    const double scale = std::max(dmax, rho_t);
    const double tol = options.deflation_epsilon_multiple * kEpsilon * scale;

    std::vector<std::size_t> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](std::size_t x, std::size_t y) { return d[x] < d[y]; });

    // Dropping component i discards rho*z_i*(z e_i^T + e_i z^T), whose norm is
    // of order rho*|z_i| (|z| = 1), so the test is linear in |z_i|: a test on
    // the diagonal term rho*z_i^2 alone would admit a sqrt(eps) backward error.
    std::vector<char> active(n, 0);
    for (std::size_t i = 0; i < n; ++i) {
        if (rho_t * std::abs(zt[i]) > tol) active[i] = 1;
        else ++stats.deflated_small;
    }
    // Nearly equal retained eigenvalues: rotate the pair so one component of z
    // vanishes and that eigenpair deflates. The rotation is applied to the
    // stored eigenvectors and to every co-transformed state.
    std::size_t previous = n;
    for (std::size_t idx : order) {
        if (!active[idx]) continue;
        if (previous < n && std::abs(d[idx] - d[previous]) <= tol) {
            const double r = std::hypot(zt[previous], zt[idx]);
            const double c = zt[previous] / r, s = zt[idx] / r;
            rotateColumns(vectors, previous, idx, c, s);
            for (auto *state : co_transform) {
                const double a = (*state)[previous], b = (*state)[idx];
                (*state)[previous] = c * a + s * b;
                (*state)[idx] = -s * a + c * b;
            }
            zt[previous] = r;
            zt[idx] = 0.0;
            const double dp = c * c * d[previous] + s * s * d[idx];
            const double di = s * s * d[previous] + c * c * d[idx];
            d[previous] = dp;
            d[idx] = di;
            active[idx] = 0;
            ++stats.deflated_equal;
            continue;
        }
        previous = idx;
    }
    std::vector<std::size_t> act;
    for (std::size_t idx : order) if (active[idx]) act.push_back(idx);
    const std::size_t k = act.size();
    stats.retained = k;
    if (k == 0) {
        for (std::size_t i = 0; i < n; ++i) values[i] = negate ? -d[i] : d[i];
        return stats;
    }
    std::vector<double> dd(k), zz(k);
    double sumz2 = 0.0;
    for (std::size_t j = 0; j < k; ++j) {
        dd[j] = d[act[j]];
        zz[j] = zt[act[j]];
        sumz2 += zz[j] * zz[j];
    }

    // Secular roots. Root i lies in (dd[i], dd[i+1]), the last in
    // (dd[k-1], dd[k-1] + rho_t * sumz2]. Each root is stored as an offset tau
    // from the nearer interval end so lambda_j - dd_i is formed with one rounding.
    std::vector<std::size_t> base(k);
    std::vector<double> tau(k);
    const auto secular = [&](std::size_t origin, double t, double *derivative, double *magnitude) {
        double f = 1.0, df = 0.0, mag = 1.0;
        for (std::size_t j = 0; j < k; ++j) {
            const double delta = (dd[j] - dd[origin]) - t;
            const double term = rho_t * zz[j] * zz[j] / delta;
            f += term;
            df += rho_t * zz[j] * zz[j] / (delta * delta);
            mag += std::abs(term);
        }
        if (derivative) *derivative = df;
        if (magnitude) *magnitude = mag;
        return f;
    };
    for (std::size_t i = 0; i < k; ++i) {
        if (k == 1) { base[0] = 0; tau[0] = rho_t * zz[0] * zz[0]; break; }
        const double lo = dd[i];
        const double hi = i + 1 < k ? dd[i + 1] : dd[i] + rho_t * sumz2;
        const double mid = 0.5 * (lo + hi);
        // Decide which end the root is nearer to from the sign at the midpoint.
        const double fmid = secular(i, mid - lo, nullptr, nullptr);
        std::size_t origin = i;
        double tlo = 0.0, thi = 0.0;
        if (fmid > 0.0) { origin = i; tlo = 0.0; thi = mid - lo; }
        else if (i + 1 < k) { origin = i + 1; tlo = mid - hi; thi = 0.0; }
        else { origin = i; tlo = mid - lo; thi = hi - lo; }
        // Newton with a maintained bracket; the secular function increases
        // monotonically on the open interval.
        double t = 0.5 * (tlo + thi);
        double g = 0.0, dg = 0.0, mag = 0.0;
        unsigned iteration = 0;
        for (; iteration < options.maximum_secular_iterations; ++iteration) {
            g = secular(origin, t, &dg, &mag);
            if (!std::isfinite(g)) { t = 0.5 * (tlo + thi); continue; }
            if (std::abs(g) <= static_cast<double>(k + 1) * kEpsilon * mag) break;
            if (g > 0.0) thi = t; else tlo = t;
            double next = dg > 0.0 ? t - g / dg : 0.5 * (tlo + thi);
            if (!(next > tlo && next < thi)) next = 0.5 * (tlo + thi);
            // The offset from the nearer end is the quantity that must carry
            // full relative accuracy; a tolerance scaled by the eigenvalue
            // itself would surrender that accuracy for roots close to a pole.
            if (next == t || thi - tlo <= 4.0 * kEpsilon * std::max(std::abs(tlo), std::abs(thi))) { t = next; break; }
            t = next;
        }
        stats.secular_iterations += iteration;
        stats.secular_residual = std::max(stats.secular_residual, std::abs(g) / std::max(mag, 1.0));
        base[i] = origin;
        tau[i] = t;
    }
    // Gu-Eisenstat: recompute the perturbation vector from the computed roots
    // (Loewner's formula) so the eigenvectors below are exactly those of a
    // nearby rank-one problem and therefore orthonormal to working precision.
    const auto lambda_minus = [&](std::size_t j, std::size_t i) {
        return (dd[base[j]] - dd[i]) + tau[j];
    };
    std::vector<double> zhat(k);
    for (std::size_t i = 0; i < k; ++i) {
        double value = lambda_minus(i, i) / rho_t;
        for (std::size_t j = 0; j < k; ++j) {
            if (j == i) continue;
            value *= lambda_minus(j, i) / (dd[j] - dd[i]);
        }
        zhat[i] = (zz[i] >= 0.0 ? 1.0 : -1.0) * std::sqrt(std::max(value, 0.0));
    }
    DenseMatrix v(k, k);
    for (std::size_t i = 0; i < k; ++i) {
        double norm2 = 0.0;
        for (std::size_t j = 0; j < k; ++j) {
            const double denominator = (dd[j] - dd[base[i]]) - tau[i];
            const double entry = zhat[j] / denominator;
            v(j, i) = entry;
            norm2 += entry * entry;
        }
        const double inv = 1.0 / std::sqrt(norm2);
        for (std::size_t j = 0; j < k; ++j) v(j, i) *= inv;
    }
    // Rotate the retained columns: Psi'[:, act] = Psi[:, act] * V.
    const std::size_t rows = vectors.rows;
    DenseMatrix gathered(rows, k), product(rows, k);
    for (std::size_t r = 0; r < rows; ++r) {
        const double *row = vectors.row(r);
        double *g = gathered.row(r);
        for (std::size_t j = 0; j < k; ++j) g[j] = row[act[j]];
    }
    multiplyInto(gathered, v, product);
    for (std::size_t r = 0; r < rows; ++r) {
        double *row = vectors.row(r);
        const double *p = product.row(r);
        for (std::size_t j = 0; j < k; ++j) row[act[j]] = p[j];
    }
    for (auto *state : co_transform) {
        std::vector<double> old(k);
        for (std::size_t j = 0; j < k; ++j) old[j] = (*state)[act[j]];
        for (std::size_t i = 0; i < k; ++i) {
            double sum = 0.0;
            for (std::size_t j = 0; j < k; ++j) sum += v(j, i) * old[j];
            (*state)[act[i]] = sum;
        }
    }
    for (std::size_t i = 0; i < k; ++i) d[act[i]] = dd[base[i]] + tau[i];
    for (std::size_t i = 0; i < n; ++i) values[i] = negate ? -d[i] : d[i];
    return stats;
}

void multiplyInto(const DenseMatrix &a, const DenseMatrix &b, DenseMatrix &out) {
    if (a.cols != b.rows) throw std::invalid_argument("matrix product dimension mismatch");
    if (out.rows != a.rows || out.cols != b.cols) out = DenseMatrix(a.rows, b.cols);
    const long long rows = static_cast<long long>(a.rows);
    const std::size_t inner = a.cols, cols = b.cols;
#if defined(_OPENMP)
#pragma omp parallel for schedule(static)
#endif
    for (long long r = 0; r < rows; ++r) {
        const auto row = static_cast<std::size_t>(r);
        double *o = out.row(row);
        for (std::size_t j = 0; j < cols; ++j) o[j] = 0.0;
        const double *ar = a.row(row);
        for (std::size_t kk = 0; kk < inner; ++kk) {
            const double aik = ar[kk];
            if (aik == 0.0) continue;
            const double *br = b.row(kk);
            for (std::size_t j = 0; j < cols; ++j) o[j] += aik * br[j];
        }
    }
}

double orthogonalityDefect(const DenseMatrix &vectors) {
    double worst = 0.0;
    for (std::size_t i = 0; i < vectors.cols; ++i)
        for (std::size_t j = i; j < vectors.cols; ++j) {
            double sum = 0.0;
            for (std::size_t r = 0; r < vectors.rows; ++r) sum += vectors(r, i) * vectors(r, j);
            worst = std::max(worst, std::abs(sum - (i == j ? 1.0 : 0.0)));
        }
    return worst;
}

double decompositionResidual(const DenseMatrix &matrix, const SymmetricEigenDecomposition &decomposition) {
    const std::size_t n = matrix.rows;
    double scale = 1.0;
    for (double value : decomposition.values) scale = std::max(scale, std::abs(value));
    double worst = 0.0;
    std::vector<double> column(n);
    for (std::size_t k = 0; k < n; ++k) {
        for (std::size_t r = 0; r < n; ++r) column[r] = decomposition.vectors(r, k);
        for (std::size_t r = 0; r < n; ++r) {
            double sum = 0.0;
            for (std::size_t c = 0; c < n; ++c) sum += matrix(r, c) * column[c];
            worst = std::max(worst, std::abs(sum - decomposition.values[k] * column[r]));
        }
    }
    return worst / scale;
}

} // namespace banjo::modal
