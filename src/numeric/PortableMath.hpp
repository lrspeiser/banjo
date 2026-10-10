#pragma once

// Transcendental functions that give the same bits on every platform.
//
// IEEE 754 makes + - * / sqrt and fma correctly rounded, so every compiler and
// C library agrees on them. It does not make sin, cos, exp, log, pow, cbrt,
// hypot or the inverse trigonometric functions correctly rounded, and the C
// libraries do not agree on them. Measured on 2026-10-10: glibc's cbrt is a
// unit in the last place off the true root for 47% of arguments in
// [1e-6, 1e4]; for the voxel lab's 1 kg iron ball, cbrt(1 / (7870 * 0.5)) is
// 0.06334102511897383 in glibc and 0.06334102511897385 in the Microsoft CRT,
// either side of 0.06334102511897384; glibc's exp misrounds about one argument
// in 1,300. A fracture run is chaotic, so two such balls are two different runs
// a few hundred steps later, and Linux (Render, CI) and Windows (local play)
// gave different outcomes for one declared experiment.
//
// These are computed in double-double arithmetic (about 104 good bits) from the
// correctly rounded operations alone -- no C library call, so no platform's
// library decides anything -- and rounded once. The result is the correctly
// rounded value except for an argument whose true value lies within about
// 2^-100 of a rounding boundary, and it is the same bits everywhere whatever.
// tests/portable_math_tests.cpp checks them against values computed to 60
// digits. docs/floating-point-model.md says where they are used.
//
// Each first takes a fast path -- a table (numeric/PortableMathTables.hpp)
// shortens the series, the leading terms carried in double-double -- that says
// how far out it can be; when that leaves the rounding undecided, about one call
// in millions, the long series below decide it. Squares and square roots asked
// of pow() take the one-operation path.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

#include "numeric/PortableMathTables.hpp"

namespace banjo::pm {

// ldexp and frexp as exact operations on the bits. The C library's are calls
// (glibc's are not inlined), and a fast path makes several a call; these give
// exactly what std::ldexp and std::frexp give.
namespace bits {
[[nodiscard]] inline std::uint64_t of(double x) {
    std::uint64_t b;
    std::memcpy(&b, &x, sizeof b);
    return b;
}
[[nodiscard]] inline double from(std::uint64_t b) {
    double x;
    std::memcpy(&x, &b, sizeof x);
    return x;
}
// x * 2^k: one multiplication by an exact power of two rounds the exact product
// once, as ldexp does, denormal results included. Beyond the normal exponents,
// the library.
[[nodiscard]] inline double ldexp(double x, int k) {
    if (k >= -1022 && k <= 1023) return x * from(static_cast<std::uint64_t>(k + 1023) << 52);
    return std::ldexp(x, k);
}
// A normal x as m 2^e, m in [0.5, 1); zeros, denormals, infinities and NaNs
// from the library.
[[nodiscard]] inline double frexp(double x, int *e) {
    const std::uint64_t b = of(x);
    const int biased = static_cast<int>((b >> 52) & 0x7ff);
    if (biased == 0 || biased == 0x7ff) return std::frexp(x, e);
    *e = biased - 1022;
    return from((b & ~(std::uint64_t{0x7ff} << 52)) | (std::uint64_t{1022} << 52));
}
} // namespace bits

namespace dd {

// hi + lo, |lo| at most half an ulp of hi.
struct Twin {
    double hi, lo;
};

[[nodiscard]] inline Twin twoSum(double a, double b) {
    const double s = a + b, bb = s - a;
    return {s, (a - (s - bb)) + (b - bb)};
}
[[nodiscard]] inline Twin quickTwoSum(double a, double b) {  // |a| >= |b| or a == 0
    const double s = a + b;
    return {s, b - (s - a)};
}
[[nodiscard]] inline Twin twoProduct(double a, double b) {
    const double p = a * b;
    return {p, std::fma(a, b, -p)};
}
[[nodiscard]] inline Twin add(Twin a, Twin b) {
    Twin s = twoSum(a.hi, b.hi);
    const Twin t = twoSum(a.lo, b.lo);
    s.lo += t.hi;
    s = quickTwoSum(s.hi, s.lo);
    s.lo += t.lo;
    return quickTwoSum(s.hi, s.lo);
}
[[nodiscard]] inline Twin add(Twin a, double b) {
    Twin s = twoSum(a.hi, b);
    s.lo += a.lo;
    return quickTwoSum(s.hi, s.lo);
}
[[nodiscard]] inline Twin negate(Twin a) { return {-a.hi, -a.lo}; }
[[nodiscard]] inline Twin sub(Twin a, Twin b) { return add(a, negate(b)); }
[[nodiscard]] inline Twin mul(Twin a, Twin b) {
    Twin p = twoProduct(a.hi, b.hi);
    const double cross = a.hi * b.lo;
    p.lo += cross + a.lo * b.hi;
    return quickTwoSum(p.hi, p.lo);
}
[[nodiscard]] inline Twin mul(Twin a, double b) {
    Twin p = twoProduct(a.hi, b);
    p.lo += a.lo * b;
    return quickTwoSum(p.hi, p.lo);
}
[[nodiscard]] inline Twin div(Twin a, Twin b) {
    const double q1 = a.hi / b.hi;
    Twin r = sub(a, mul(b, q1));
    const double q2 = r.hi / b.hi;
    r = sub(r, mul(b, q2));
    const double q3 = r.hi / b.hi;
    return add(quickTwoSum(q1, q2), q3);
}
[[nodiscard]] inline Twin div(Twin a, double b) { return div(a, Twin{b, 0.0}); }
// Square root: one Newton step from the correctly rounded double root.
[[nodiscard]] inline Twin sqrt(Twin a) {
    if (!(a.hi > 0.0)) return {a.hi == 0.0 ? 0.0 : std::numeric_limits<double>::quiet_NaN(), 0.0};
    const double s = std::sqrt(a.hi);
    const Twin square = twoProduct(s, s);
    const double rest = ((a.hi - square.hi) - square.lo + a.lo) / (2.0 * s);
    return quickTwoSum(s, rest);
}
[[nodiscard]] inline Twin ldexp(Twin a, int e) { return {bits::ldexp(a.hi, e), bits::ldexp(a.lo, e)}; }

// Constants as double-doubles (each hi the double nearest; lo the remainder).
inline constexpr Twin kLn2{6.93147180559945286227e-01, 2.31904681384629955842e-17};
inline constexpr Twin kPi{3.14159265358979311600e+00, 1.22464679914735320717e-16};
inline constexpr Twin kHalfPi{1.57079632679489655800e+00, 6.12323399573676603587e-17};
// pi/2 as three pieces of 33 significant bits and a tail (fdlibm's pio2_1,
// pio2_2, pio2_3 and pio2_3t), so k * piece is exact for |k| < 2^20.
inline constexpr double kHalfPi1 = 1.57079632673412561417e+00;
inline constexpr double kHalfPi2 = 6.07710050630396597660e-11;
inline constexpr double kHalfPi3 = 2.02226624871116645580e-21;
inline constexpr double kHalfPi3Tail = 8.47842766036889956997e-32;

// e^x for a double-double x with |x.hi| <= 746. x = k ln2 + r, then
// e^r = (e^(r/16))^16: a series, then four squarings carried as e^s - 1 so
// nothing cancels; the caller scales by 2^k exactly.
[[nodiscard]] inline Twin exp(Twin x, int &k_out) {
    const double k = std::round(x.hi / kLn2.hi);
    const Twin kln2 = add(twoProduct(k, kLn2.hi), twoProduct(k, kLn2.lo));
    Twin r = sub(x, kln2);
    r = ldexp(r, -4);
    Twin series{1.0, 0.0};
    for (int n = 18; n >= 2; --n) series = add(div(mul(series, r), static_cast<double>(n)), 1.0);
    Twin less_one = mul(series, r);
    for (int i = 0; i < 4; ++i) less_one = mul(less_one, add(less_one, 2.0));
    k_out = static_cast<int>(k);
    return add(less_one, 1.0);  // e^r; the caller scales by 2^k
}

// ln x for a positive, finite double-double: x = m 2^e with m in
// [sqrt(1/2), sqrt(2)), ln m = 2 atanh((m - 1) / (m + 1)) by its series.
[[nodiscard]] inline Twin log(Twin x) {
    int e = 0;
    (void)bits::frexp(x.hi, &e);
    Twin m = ldexp(x, -e);  // hi in [0.5, 1)
    if (m.hi < 0.70710678118654752440) {
        m = ldexp(m, 1);
        --e;
    }
    const Twin s = div(add(m, -1.0), add(m, 1.0));
    const Twin s2 = mul(s, s);
    Twin series = div(Twin{1.0, 0.0}, 45.0);
    for (int n = 43; n >= 1; n -= 2) series = add(mul(series, s2), div(Twin{1.0, 0.0}, static_cast<double>(n)));
    const Twin ln_m = mul(mul(series, s), 2.0);
    return add(mul(kLn2, static_cast<double>(e)), ln_m);
}

// sin and cos of a reduced argument |r| <= pi/4 + a little, by their series.
[[nodiscard]] inline Twin sinSeries(Twin r) {
    const Twin r2 = mul(r, r);
    Twin p{1.0, 0.0};
    for (int n = 33; n >= 3; n -= 2) p = sub(Twin{1.0, 0.0}, div(mul(r2, p), static_cast<double>(n) * (n - 1)));
    return mul(p, r);
}
[[nodiscard]] inline Twin cosSeries(Twin r) {
    const Twin r2 = mul(r, r);
    Twin p{1.0, 0.0};
    for (int n = 34; n >= 2; n -= 2) p = sub(Twin{1.0, 0.0}, div(mul(r2, p), static_cast<double>(n) * (n - 1)));
    return p;
}

// x = k pi/2 + r. Exact pieces of pi/2 for |k| < 2^20 (|x| below about 1.6e6
// rad); past that the reduction is still the same bits everywhere, though no
// longer correctly rounded.
[[nodiscard]] inline Twin reduceHalfPi(double x, int &quadrant) {
    const double k = std::round(x * 0.63661977236758134308);
    Twin r = twoSum(x, -k * kHalfPi1);
    r = add(r, -k * kHalfPi2);
    r = add(r, -k * kHalfPi3);
    r = add(r, twoProduct(-k, kHalfPi3Tail));
    const double q = k - 4.0 * std::floor(k * 0.25);
    quadrant = static_cast<int>(q);
    return r;
}

// atan of a non-negative double-double, by halving the angle until the series
// is short: atan t = 2 atan(t / (1 + sqrt(1 + t^2))).
[[nodiscard]] inline Twin atanPositive(Twin t) {
    bool flipped = false;
    if (t.hi > 1.0) {
        t = div(Twin{1.0, 0.0}, t);
        flipped = true;
    }
    for (int i = 0; i < 3; ++i) t = div(t, add(sqrt(add(mul(t, t), 1.0)), 1.0));
    const Twin t2 = mul(t, t);
    Twin series = div(Twin{1.0, 0.0}, 41.0);
    for (int n = 39; n >= 1; n -= 2) {
        const Twin term = div(Twin{1.0, 0.0}, static_cast<double>(n));
        series = sub(term, mul(t2, series));
    }
    Twin a = ldexp(mul(series, t), 3);
    if (flipped) a = sub(kHalfPi, a);
    return a;
}

// atan2 of double-doubles, finite and not both zero.
[[nodiscard]] inline Twin atan2(Twin y, Twin x) {
    const bool y_negative = y.hi < 0.0 || (y.hi == 0.0 && std::signbit(y.hi));
    const Twin ay = y.hi < 0.0 ? negate(y) : y, ax = x.hi < 0.0 ? negate(x) : x;
    // The smaller over the larger, so the ratio cannot overflow.
    Twin a;
    if (ay.hi == 0.0) a = {0.0, 0.0};
    else if (ax.hi == 0.0) a = kHalfPi;
    else if (ay.hi > ax.hi) a = sub(kHalfPi, atanPositive(div(ax, ay)));
    else a = atanPositive(div(ay, ax));
    if (x.hi < 0.0 || (x.hi == 0.0 && std::signbit(x.hi) && ay.hi == 0.0)) a = sub(kPi, a);
    return y_negative ? negate(a) : a;
}

[[nodiscard]] inline double round(Twin a) { return a.hi + a.lo; }

// The double nearest a * 2^k, rounded once. Where that is a denormal,
// std::ldexp(round(a), k) would round twice -- to 53 bits, then to the coarser
// grid of the denormals -- and can miss by one. So it is counted in units of
// the smallest denormal, 2^-1074, where the scaled pair is still exact, and
// that count rounded to an integer once: ties to even, or, for a result known
// to lie just inside a (`below`), towards zero.
[[nodiscard]] inline double scaleRound(Twin a, int k, bool below = false) {
    if (a.hi == 0.0 || !(std::abs(bits::ldexp(a.hi, k)) <= 0x1p-1022)) return bits::ldexp(round(a), k);
    const bool negative = a.hi < 0.0;
    const double h = bits::ldexp(std::abs(a.hi), k + 1074);
    const double l = bits::ldexp(negative ? -a.lo : a.lo, k + 1074);
    double n = std::nearbyint(h);
    const double rest = (h - n) + l;  // h - n is exact: |h| < 2^52 and n the integer nearest it
    const bool odd = std::fmod(n, 2.0) != 0.0;
    if (rest > 0.5 || (rest == 0.5 && odd && !below)) n += 1.0;
    else if (rest < -0.5 || (rest == -0.5 && (odd || below))) n -= 1.0;
    const double out = bits::ldexp(n, -1074);
    return negative ? -out : out;
}

// Whether a result known to within e (absolute) rounds to one double: the
// double nearest the true value then, whatever is in the last bits.
[[nodiscard]] inline bool decided(Twin r, double e, double &out) {
    const double a = r.hi + (r.lo - e), b = r.hi + (r.lo + e);
    if (a != b) return false;
    out = a;
    return true;
}

} // namespace dd

// The fast paths: a table cuts the argument down to a short polynomial, the
// leading terms carried in double-double, the rest in double. Each says how
// far it can be out; when that leaves the rounding undecided (about one call
// in millions) the series in dd:: above answer instead. Both use the correctly
// rounded operations alone, so which path runs, and what it gives, is the same
// on every platform.
namespace fast {

using dd::Twin;

// How far a fast path's result can be out, relative: above the largest of the
// bounds worked out for each (about 2^-67, where a small result meets a
// correction term computed in double), with room to spare.
inline constexpr double kRelativeBound = 0x1p-64;

// e^x = 2^k * result, x a double-double with |x.hi| <= 709.8. Relative error
// below 2^-73.
[[nodiscard]] inline Twin exp(Twin x, int &k) {
    const double kd = std::round(x.hi * 92.332482616893656768);  // x 64/ln2
    const Twin step{dd::kLn2.hi / 64.0, dd::kLn2.lo / 64.0};
    const Twin r = dd::sub(x, dd::add(dd::twoProduct(kd, step.hi), dd::twoProduct(kd, step.lo)));
    // e^r - 1 = r + r^2/2 + r^2 t, |r| <= ln2/128.
    const double rh = r.hi;
    Twin r2 = dd::twoProduct(rh, rh);
    r2.lo += 2.0 * rh * r.lo;
    const double t =
        rh * (1.0 / 6 + rh * (1.0 / 24 + rh * (1.0 / 120 + rh * (1.0 / 720 + rh * (1.0 / 5040 + rh / 40320)))));
    Twin less_one = dd::add(r, Twin{0.5 * r2.hi, 0.5 * r2.lo});
    less_one = dd::add(less_one, r2.hi * t);
    const long long ki = static_cast<long long>(kd);
    const int j = static_cast<int>(ki & 63);
    k = static_cast<int>((ki - j) / 64);
    const Twin table{tables::kExp2Sixtyfourths[j].hi, tables::kExp2Sixtyfourths[j].lo};
    return dd::add(table, dd::mul(table, less_one));
}

// ln x for a positive normal double: absolute error below 2^-75, relative
// below 2^-67.
[[nodiscard]] inline Twin log(double x) {
    int e = 0;
    double m = bits::frexp(x, &e);
    m *= 2.0;
    --e;  // x = m 2^e, m in [1, 2)
    const int i = static_cast<int>(std::round((m - 1.0) * 128.0));
    const double c = 1.0 + i / 128.0;
    const double u = m - c;  // exact: m and c are within 1/256 of each other
    const double q = u / c;
    const Twin r = dd::quickTwoSum(q, std::fma(-q, c, u) / c);  // (m - c)/c = m/c - 1
    // ln(1 + r) = r - r^2/2 + r^2 t, |r| <= 1/256.
    const double rh = r.hi;
    Twin r2 = dd::twoProduct(rh, rh);
    r2.lo += 2.0 * rh * r.lo;
    const double t = rh * (1.0 / 3 + rh * (-1.0 / 4 + rh * (1.0 / 5 + rh * (-1.0 / 6 + rh * (1.0 / 7 - rh / 8)))));
    Twin small = dd::add(r, Twin{-0.5 * r2.hi, -0.5 * r2.lo});
    small = dd::add(small, r2.hi * t);
    const Twin ln_c{tables::kLogOnePlus[i].hi, tables::kLogOnePlus[i].lo};
    return dd::add(dd::mul(dd::kLn2, static_cast<double>(e)), dd::add(ln_c, small));
}

// sin and cos of r, |r| <= pi/4 (+ a little): absolute error below 2^-75,
// relative below 2^-67.
inline void sinCos(Twin r, Twin &s, Twin &c) {
    const bool negative = r.hi < 0.0;
    if (negative) r = dd::negate(r);
    const int j = static_cast<int>(std::round(r.hi * 64.0));
    const Twin t = dd::add(Twin{r.hi - j / 64.0, 0.0}, r.lo);  // exact difference: within 1/128
    const double th = t.hi, tt = th * th;
    Twin t2 = dd::twoProduct(th, th);
    t2.lo += 2.0 * th * t.lo;
    // sin t = t + t^3 ps, cos t - 1 = -t^2/2 + t^4 pc, |t| <= 1/128.
    const double ps = -1.0 / 6 + tt * (1.0 / 120 + tt * (-1.0 / 5040 + tt * (1.0 / 362880)));
    const double pc = 1.0 / 24 + tt * (-1.0 / 720 + tt * (1.0 / 40320 - tt / 3628800));
    const Twin sin_t = dd::add(t, th * tt * ps);
    const Twin cos_less_one = dd::add(Twin{-0.5 * t2.hi, -0.5 * t2.lo}, tt * tt * pc);
    const Twin S{tables::kSinSixtyfourths[j].hi, tables::kSinSixtyfourths[j].lo};
    const Twin C{tables::kCosSixtyfourths[j].hi, tables::kCosSixtyfourths[j].lo};
    s = dd::add(S, dd::add(dd::mul(S, cos_less_one), dd::mul(C, sin_t)));
    c = dd::add(C, dd::sub(dd::mul(C, cos_less_one), dd::mul(S, sin_t)));
    if (negative) s = dd::negate(s);
}

// atan t for 0 <= t <= 1 (a double-double): absolute error below 2^-74,
// relative below 2^-67.
[[nodiscard]] inline Twin atanUnit(Twin t) {
    const int j = static_cast<int>(std::round(t.hi * 64.0));
    const double c = j / 64.0;
    // atan t = atan c + atan u, u = (t - c) / (1 + t c), |u| <= 1/128.
    const Twin num = dd::add(Twin{t.hi - c, 0.0}, t.lo);  // exact difference
    const Twin den = dd::add(dd::add(dd::twoProduct(t.hi, c), t.lo * c), 1.0);
    const Twin u = dd::div(num, den);
    const double uh = u.hi, uu = uh * uh;
    const double p = uh * uu * (-1.0 / 3 + uu * (1.0 / 5 + uu * (-1.0 / 7 + uu * (1.0 / 9 - uu / 11))));
    const Twin atan_c{tables::kAtanSixtyfourths[j].hi, tables::kAtanSixtyfourths[j].lo};
    return dd::add(atan_c, dd::add(u, p));
}

// atan2 of finite double-doubles, not both zero.
[[nodiscard]] inline Twin atan2(Twin y, Twin x) {
    const bool y_negative = y.hi < 0.0 || (y.hi == 0.0 && std::signbit(y.hi));
    const Twin ay = y.hi < 0.0 ? dd::negate(y) : y, ax = x.hi < 0.0 ? dd::negate(x) : x;
    Twin a;
    if (ay.hi == 0.0) a = {0.0, 0.0};
    else if (ax.hi == 0.0) a = dd::kHalfPi;
    else if (ay.hi > ax.hi) a = dd::sub(dd::kHalfPi, atanUnit(dd::div(ax, ay)));
    else a = atanUnit(dd::div(ay, ax));
    if (x.hi < 0.0 || (x.hi == 0.0 && std::signbit(x.hi) && ay.hi == 0.0)) a = dd::sub(dd::kPi, a);
    return y_negative ? dd::negate(a) : a;
}

} // namespace fast

[[nodiscard]] inline double exp(double x) {
    if (std::isnan(x)) return x;
    if (x > 709.782712893384) return std::numeric_limits<double>::infinity();
    if (x < -745.1332191019412) return 0.0;
    int k = 0;
    if (x > -708.0) {  // a normal result: the fast path, scaled exactly
        const dd::Twin e = fast::exp(dd::Twin{x, 0.0}, k);
        const dd::Twin scaled = dd::ldexp(e, k);
        double out;
        if (dd::decided(scaled, std::abs(scaled.hi) * fast::kRelativeBound, out)) return out;
    }
    const dd::Twin e = dd::exp(dd::Twin{x, 0.0}, k);  // sets k: not in one expression
    return dd::scaleRound(e, k);
}

// e^x - 1, kept relative for small x.
[[nodiscard]] inline double expm1(double x) {
    if (std::isnan(x) || x == 0.0) return x;
    if (x > 709.782712893384) return std::numeric_limits<double>::infinity();
    if (x < -40.0) return -1.0;
    if (std::abs(x) < 0x1p-10) {
        // x + x^2/2 + ... + x^9/9!, in double-double.
        dd::Twin p{1.0, 0.0};
        for (int n = 9; n >= 2; --n) p = dd::add(dd::div(dd::mul(p, x), static_cast<double>(n)), 1.0);
        return dd::round(dd::mul(p, x));
    }
    int k = 0;
    const dd::Twin unscaled = fast::exp(dd::Twin{x, 0.0}, k);  // sets k: not in one expression
    const dd::Twin e = dd::ldexp(unscaled, k);
    double out;
    if (dd::decided(dd::add(e, -1.0), std::abs(e.hi) * fast::kRelativeBound, out)) return out;
    const dd::Twin slow = dd::exp(dd::Twin{x, 0.0}, k);
    return dd::round(dd::add(dd::ldexp(slow, k), -1.0));
}

[[nodiscard]] inline double log(double x) {
    if (std::isnan(x) || x < 0.0) return std::numeric_limits<double>::quiet_NaN();
    if (x == 0.0) return -std::numeric_limits<double>::infinity();
    if (std::isinf(x)) return x;
    if (x == 1.0) return 0.0;
    if (x >= 0x1p-1022) {
        const dd::Twin l = fast::log(x);
        double out;
        if (dd::decided(l, std::abs(l.hi) * fast::kRelativeBound, out)) return out;
    }
    return dd::round(dd::log(dd::Twin{x, 0.0}));
}

[[nodiscard]] inline double log1p(double x) {
    if (std::isnan(x) || x < -1.0) return std::numeric_limits<double>::quiet_NaN();
    if (x == -1.0) return -std::numeric_limits<double>::infinity();
    if (std::isinf(x) || x == 0.0) return x;
    if (std::abs(x) < 1e-300) return x;
    const dd::Twin one_plus = dd::twoSum(1.0, x);
    if (std::abs(x) >= 0x1p-9 && one_plus.hi >= 0x1p-1022) {
        // ln(h + l) = ln h + l/h, the next term below 2^-106.
        const dd::Twin l = dd::add(fast::log(one_plus.hi), one_plus.lo / one_plus.hi);
        double out;
        if (dd::decided(l, std::abs(l.hi) * fast::kRelativeBound, out)) return out;
    }
    return dd::round(dd::log(one_plus));
}

[[nodiscard]] inline double pow(double x, double y) {
    if (y == 0.0 || x == 1.0) return 1.0;
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<double>::quiet_NaN();
    if (y == 1.0) return x;
    if (y == 2.0) return x * x;
    const bool y_integer = std::floor(y) == y && std::isfinite(y);
    const bool y_odd = y_integer && std::abs(y) < 9007199254740992.0 && std::fmod(y, 2.0) != 0.0;
    if (std::isinf(y)) {
        const double ax = std::abs(x);
        if (ax == 1.0) return 1.0;
        return (ax < 1.0) == (y < 0.0) ? std::numeric_limits<double>::infinity() : 0.0;
    }
    if (x == 0.0) {
        if (y < 0.0) return y_odd ? std::copysign(std::numeric_limits<double>::infinity(), x)
                                  : std::numeric_limits<double>::infinity();
        return y_odd ? x : 0.0;
    }
    if (std::isinf(x)) {
        if (x > 0.0) return y < 0.0 ? 0.0 : x;
        if (y < 0.0) return y_odd ? -0.0 : 0.0;
        return y_odd ? x : -x;
    }
    if (x < 0.0 && !y_integer) return std::numeric_limits<double>::quiet_NaN();
    const double ax = std::abs(x);
    double result = 0.0;
    bool done = false;
    if (y == 0.5) {
        result = std::sqrt(ax);
        done = true;
    } else if (ax >= 0x1p-1022) {
        const dd::Twin l = fast::log(ax);
        const dd::Twin t = dd::mul(l, y);
        if (t.hi > 709.782712893384) {
            result = std::numeric_limits<double>::infinity();
            done = true;
        } else if (t.hi > -708.0) {
            int k = 0;
            const dd::Twin unscaled = fast::exp(t, k);  // sets k: not in one expression
            const dd::Twin e = dd::ldexp(unscaled, k);
            // ln x is out by at most 2^-67 of max(|ln x|, 1), so y ln x by |y|
            // times that, and e^(y ln x) by as much again, relative.
            const double bound = std::abs(e.hi) * (std::abs(y) * std::max(std::abs(l.hi), 1.0) * 0x1p-64 + 0x1p-64);
            done = dd::decided(e, bound, result);
        }
    }
    if (!done) {
        const dd::Twin t = dd::mul(dd::log(dd::Twin{ax, 0.0}), y);
        if (t.hi > 709.782712893384) result = std::numeric_limits<double>::infinity();
        else if (t.hi < -745.1332191019412) result = 0.0;
        else {
            int k = 0;
            const dd::Twin e = dd::exp(t, k);  // sets k: not in one expression
            result = dd::scaleRound(e, k);
        }
    }
    return x < 0.0 && y_odd ? -result : result;
}

namespace detail {
// sin, cos or tan of x by the fast path, falling back to the series.
enum class Trig { Sin, Cos, Tan };
[[nodiscard]] inline double trig(double x, Trig which) {
    int q = 0;
    const dd::Twin r = dd::reduceHalfPi(x, q);
    dd::Twin s, c;
    fast::sinCos(r, s, c);
    dd::Twin v;
    switch (which) {
    case Trig::Sin: v = (q & 1) == 0 ? s : c; break;
    case Trig::Cos: v = (q & 1) == 0 ? c : dd::negate(s); break;
    default: v = (q & 1) == 0 ? dd::div(s, c) : dd::negate(dd::div(c, s)); break;
    }
    if (which != Trig::Tan && (q & 2) != 0) v = dd::negate(v);
    double out;
    if (dd::decided(v, std::abs(v.hi) * fast::kRelativeBound, out)) return out;
    const dd::Twin ss = dd::sinSeries(r), cs = dd::cosSeries(r);
    switch (which) {
    case Trig::Sin: v = (q & 1) == 0 ? ss : cs; break;
    case Trig::Cos: v = (q & 1) == 0 ? cs : dd::negate(ss); break;
    default: v = (q & 1) == 0 ? dd::div(ss, cs) : dd::negate(dd::div(cs, ss)); break;
    }
    if (which != Trig::Tan && (q & 2) != 0) v = dd::negate(v);
    return dd::round(v);
}

[[nodiscard]] inline double atan2(dd::Twin y, dd::Twin x) {
    const dd::Twin a = fast::atan2(y, x);
    double out;
    if (dd::decided(a, std::abs(a.hi) * fast::kRelativeBound, out)) return out;
    return dd::round(dd::atan2(y, x));
}
} // namespace detail

[[nodiscard]] inline double sin(double x) {
    if (!std::isfinite(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 1.4901161193847656e-08) return x;  // |x| < 2^-26: sin x rounds to x
    return detail::trig(x, detail::Trig::Sin);
}

[[nodiscard]] inline double cos(double x) {
    if (!std::isfinite(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 1.0536712127723509e-08) return 1.0;  // |x| < 2^-26.5: cos x rounds to 1
    return detail::trig(x, detail::Trig::Cos);
}

[[nodiscard]] inline double tan(double x) {
    if (!std::isfinite(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 7.4505805969238281e-09) return x;  // |x| < 2^-27: tan x rounds to x
    return detail::trig(x, detail::Trig::Tan);
}

[[nodiscard]] inline double atan2(double y, double x) {
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<double>::quiet_NaN();
    if (std::isinf(x) || std::isinf(y)) {
        const double quarter = dd::round(dd::kHalfPi) / 2.0;
        double a;
        if (std::isinf(x) && std::isinf(y)) a = x > 0.0 ? quarter : 3.0 * quarter;
        else if (std::isinf(y)) a = dd::round(dd::kHalfPi);
        else a = x > 0.0 ? 0.0 : dd::round(dd::kPi);
        return std::copysign(a, y);
    }
    if (y == 0.0 && x == 0.0) return std::copysign(std::signbit(x) ? dd::round(dd::kPi) : 0.0, y);
    if (x > 0.0 && std::abs(y) < x * 0x1p-900) {
        // atan(y/x) is y/x to within 2^-1800 of it, and may be a denormal,
        // where a quotient of double-doubles is no longer exact: the quotient
        // of the two significands, scaled and rounded once, just below it.
        int ey = 0, ex = 0;
        const double my = bits::frexp(y, &ey), mx = bits::frexp(x, &ex);
        return dd::scaleRound(dd::div(dd::Twin{my, 0.0}, dd::Twin{mx, 0.0}), ey - ex, true);
    }
    return detail::atan2(dd::Twin{y, 0.0}, dd::Twin{x, 0.0});
}

[[nodiscard]] inline double atan(double x) {
    if (std::isnan(x)) return x;
    if (std::isinf(x)) return std::copysign(dd::round(dd::kHalfPi), x);
    if (std::abs(x) < 7.4505805969238281e-09) return x;  // |x| < 2^-27: atan x rounds to x
    return detail::atan2(dd::Twin{x, 0.0}, dd::Twin{1.0, 0.0});
}

// sqrt((1 - x)(1 + x)) as a double-double, for |x| <= 1.
[[nodiscard]] inline dd::Twin complementRoot(double x) {
    return dd::sqrt(dd::mul(dd::twoSum(1.0, -x), dd::twoSum(1.0, x)));
}

[[nodiscard]] inline double asin(double x) {
    if (std::isnan(x) || std::abs(x) > 1.0) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 1.4901161193847656e-08) return x;
    return detail::atan2(dd::Twin{x, 0.0}, complementRoot(x));
}

[[nodiscard]] inline double acos(double x) {
    if (std::isnan(x) || std::abs(x) > 1.0) return std::numeric_limits<double>::quiet_NaN();
    if (x == 1.0) return 0.0;
    return detail::atan2(complementRoot(x), dd::Twin{x, 0.0});
}

// sqrt(x^2 + y^2 [+ z^2]) without overflow or underflow on the way.
[[nodiscard]] inline double hypot(double x, double y) {
    if (std::isinf(x) || std::isinf(y)) return std::numeric_limits<double>::infinity();
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<double>::quiet_NaN();
    double ax = std::abs(x), ay = std::abs(y);
    const double big = ax > ay ? ax : ay;
    if (big == 0.0) return 0.0;
    int scale = 0;
    if (big > 0x1p+500) scale = -600;
    else if (big < 0x1p-500) scale = 600;
    ax = bits::ldexp(ax, scale);
    ay = bits::ldexp(ay, scale);
    const dd::Twin sum = dd::add(dd::twoProduct(ax, ax), dd::twoProduct(ay, ay));
    return dd::scaleRound(dd::sqrt(sum), -scale);
}

[[nodiscard]] inline double hypot(double x, double y, double z) {
    if (std::isinf(x) || std::isinf(y) || std::isinf(z)) return std::numeric_limits<double>::infinity();
    if (std::isnan(x) || std::isnan(y) || std::isnan(z)) return std::numeric_limits<double>::quiet_NaN();
    double ax = std::abs(x), ay = std::abs(y), az = std::abs(z);
    double big = ax > ay ? ax : ay;
    big = big > az ? big : az;
    if (big == 0.0) return 0.0;
    int scale = 0;
    if (big > 0x1p+500) scale = -600;
    else if (big < 0x1p-500) scale = 600;
    ax = bits::ldexp(ax, scale);
    ay = bits::ldexp(ay, scale);
    az = bits::ldexp(az, scale);
    const dd::Twin sum = dd::add(dd::add(dd::twoProduct(ax, ax), dd::twoProduct(ay, ay)), dd::twoProduct(az, az));
    return dd::scaleRound(dd::sqrt(sum), -scale);
}

// The double nearest the real cube root. Halley's iteration from a linear
// guess, one Newton correction carried in double-double, and -- in the rare
// case that leaves the rounding open -- a walk to whichever neighbour's cube is
// nearest |x|, measured exactly by error-free products.
[[nodiscard]] inline double cbrt(double x) {
    if (!std::isfinite(x) || x == 0.0) return x;
    const double ax = std::abs(x);
    int e = 0;
    const double m = bits::frexp(ax, &e);  // ax = m 2^e, m in [0.5, 1)
    const int third = (e >= 0 ? e : e - 2) / 3, rest = e - 3 * third;
    const double mm = bits::ldexp(m, rest);  // ax = mm 2^(3 third), mm in [0.5, 4)
    double y = 0.62 + 0.25 * mm;
    for (int i = 0; i < 4; ++i) {
        const double cube = y * y * y;
        y *= (cube + 2.0 * mm) / (2.0 * cube + mm);
    }
    const dd::Twin cube = dd::mul(dd::twoProduct(y, y), y);
    const double correction = dd::round(dd::sub(dd::Twin{mm, 0.0}, cube)) / (3.0 * y * y);
    double root;
    if (!dd::decided(dd::quickTwoSum(y, correction), y * 0x1p-90, root)) {
        const auto miss = [mm](double v) {
            const double square = v * v, square_low = std::fma(v, v, -square);
            const double cubed = square * v, cube_low = std::fma(square, v, -cubed);
            const double carry = square_low * v, carry_low = std::fma(square_low, v, -carry);
            return std::abs((cubed - mm) + (cube_low + (carry + carry_low)));
        };
        root = y;
        for (int i = 0; i < 8; ++i) {
            const double up = std::nextafter(root, 4.0), down = std::nextafter(root, 0.0);
            const double here = miss(root), above = miss(up), below = miss(down);
            if (above < here && above <= below) root = up;
            else if (below < here) root = down;
            else break;
        }
    }
    root = bits::ldexp(root, third);
    return x < 0.0 ? -root : root;
}

} // namespace banjo::pm
