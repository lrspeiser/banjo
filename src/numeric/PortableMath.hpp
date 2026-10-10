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
// Accuracy is not traded for speed here: each costs some tens to a few hundred
// floating-point operations. Squares and square roots asked of pow() take the
// one-operation path.

#include <cmath>
#include <cstdint>
#include <limits>

namespace banjo::pm {

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
[[nodiscard]] inline Twin ldexp(Twin a, int e) { return {std::ldexp(a.hi, e), std::ldexp(a.lo, e)}; }

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
    (void)std::frexp(x.hi, &e);
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

} // namespace dd

[[nodiscard]] inline double exp(double x) {
    if (std::isnan(x)) return x;
    if (x > 709.782712893384) return std::numeric_limits<double>::infinity();
    if (x < -745.1332191019412) return 0.0;
    int k = 0;
    const dd::Twin e = dd::exp(dd::Twin{x, 0.0}, k);
    return std::ldexp(dd::round(e), k);
}

// e^x - 1, kept relative for small x.
[[nodiscard]] inline double expm1(double x) {
    if (std::isnan(x) || x == 0.0) return x;
    if (x > 709.782712893384) return std::numeric_limits<double>::infinity();
    if (x < -40.0) return -1.0;
    if (std::abs(x) < 1e-5) {
        // x + x^2/2 + ... + x^7/7!, in double-double.
        dd::Twin p{1.0, 0.0};
        for (int n = 7; n >= 2; --n) p = dd::add(dd::div(dd::mul(p, x), static_cast<double>(n)), 1.0);
        return dd::round(dd::mul(p, x));
    }
    int k = 0;
    const dd::Twin e = dd::exp(dd::Twin{x, 0.0}, k);
    return dd::round(dd::add(dd::ldexp(e, k), -1.0));
}

[[nodiscard]] inline double log(double x) {
    if (std::isnan(x) || x < 0.0) return std::numeric_limits<double>::quiet_NaN();
    if (x == 0.0) return -std::numeric_limits<double>::infinity();
    if (std::isinf(x)) return x;
    if (x == 1.0) return 0.0;
    return dd::round(dd::log(dd::Twin{x, 0.0}));
}

[[nodiscard]] inline double log1p(double x) {
    if (std::isnan(x) || x < -1.0) return std::numeric_limits<double>::quiet_NaN();
    if (x == -1.0) return -std::numeric_limits<double>::infinity();
    if (std::isinf(x) || x == 0.0) return x;
    if (std::abs(x) < 1e-300) return x;
    return dd::round(dd::log(dd::twoSum(1.0, x)));
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
    double result;
    if (y == 0.5) result = std::sqrt(ax);
    else {
        const dd::Twin t = dd::mul(dd::log(dd::Twin{ax, 0.0}), y);
        if (t.hi > 709.782712893384) result = std::numeric_limits<double>::infinity();
        else if (t.hi < -745.1332191019412) result = 0.0;
        else {
            int k = 0;
            const double scaled = dd::round(dd::exp(t, k));  // sets k: not in one expression
            result = std::ldexp(scaled, k);
        }
    }
    return x < 0.0 && y_odd ? -result : result;
}

[[nodiscard]] inline double sin(double x) {
    if (!std::isfinite(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 1.4901161193847656e-08) return x;  // |x| < 2^-26: sin x rounds to x
    int q = 0;
    const dd::Twin r = dd::reduceHalfPi(x, q);
    switch (q) {
    case 0: return dd::round(dd::sinSeries(r));
    case 1: return dd::round(dd::cosSeries(r));
    case 2: return -dd::round(dd::sinSeries(r));
    default: return -dd::round(dd::cosSeries(r));
    }
}

[[nodiscard]] inline double cos(double x) {
    if (!std::isfinite(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 1.0536712127723509e-08) return 1.0;  // |x| < 2^-26.5: cos x rounds to 1
    int q = 0;
    const dd::Twin r = dd::reduceHalfPi(x, q);
    switch (q) {
    case 0: return dd::round(dd::cosSeries(r));
    case 1: return -dd::round(dd::sinSeries(r));
    case 2: return -dd::round(dd::cosSeries(r));
    default: return dd::round(dd::sinSeries(r));
    }
}

[[nodiscard]] inline double tan(double x) {
    if (!std::isfinite(x)) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 7.4505805969238281e-09) return x;  // |x| < 2^-27: tan x rounds to x
    int q = 0;
    const dd::Twin r = dd::reduceHalfPi(x, q);
    const dd::Twin s = dd::sinSeries(r), c = dd::cosSeries(r);
    return (q & 1) == 0 ? dd::round(dd::div(s, c)) : -dd::round(dd::div(c, s));
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
    return dd::round(dd::atan2(dd::Twin{y, 0.0}, dd::Twin{x, 0.0}));
}

[[nodiscard]] inline double atan(double x) {
    if (std::isnan(x)) return x;
    if (std::isinf(x)) return std::copysign(dd::round(dd::kHalfPi), x);
    if (std::abs(x) < 7.4505805969238281e-09) return x;  // |x| < 2^-27: atan x rounds to x
    const dd::Twin a = dd::atanPositive(dd::Twin{std::abs(x), 0.0});
    return x < 0.0 ? -dd::round(a) : dd::round(a);
}

// sqrt((1 - x)(1 + x)) as a double-double, for |x| <= 1.
[[nodiscard]] inline dd::Twin complementRoot(double x) {
    return dd::sqrt(dd::mul(dd::twoSum(1.0, -x), dd::twoSum(1.0, x)));
}

[[nodiscard]] inline double asin(double x) {
    if (std::isnan(x) || std::abs(x) > 1.0) return std::numeric_limits<double>::quiet_NaN();
    if (std::abs(x) < 1.4901161193847656e-08) return x;
    return dd::round(dd::atan2(dd::Twin{x, 0.0}, complementRoot(x)));
}

[[nodiscard]] inline double acos(double x) {
    if (std::isnan(x) || std::abs(x) > 1.0) return std::numeric_limits<double>::quiet_NaN();
    if (x == 1.0) return 0.0;
    return dd::round(dd::atan2(complementRoot(x), dd::Twin{x, 0.0}));
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
    ax = std::ldexp(ax, scale);
    ay = std::ldexp(ay, scale);
    const dd::Twin sum = dd::add(dd::twoProduct(ax, ax), dd::twoProduct(ay, ay));
    return std::ldexp(dd::round(dd::sqrt(sum)), -scale);
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
    ax = std::ldexp(ax, scale);
    ay = std::ldexp(ay, scale);
    az = std::ldexp(az, scale);
    const dd::Twin sum = dd::add(dd::add(dd::twoProduct(ax, ax), dd::twoProduct(ay, ay)), dd::twoProduct(az, az));
    return std::ldexp(dd::round(dd::sqrt(sum)), -scale);
}

// The double nearest the real cube root: start from e^(ln|x| / 3), computed
// above, and walk to whichever neighbour's cube is nearest |x|, measured
// exactly by error-free products.
[[nodiscard]] inline double cbrt(double x) {
    if (!std::isfinite(x) || x == 0.0) return x;
    const double ax = std::abs(x);
    int e = 0;
    const double m = std::frexp(ax, &e);  // ax = m 2^e, m in [0.5, 1)
    const int third = (e >= 0 ? e : e - 2) / 3, rest = e - 3 * third;
    const double mm = std::ldexp(m, rest);  // ax = mm 2^(3 third), mm in [0.5, 4)
    const auto miss = [mm](double y) {
        const double square = y * y, square_low = std::fma(y, y, -square);
        const double cube = square * y, cube_low = std::fma(square, y, -cube);
        const double carry = square_low * y, carry_low = std::fma(square_low, y, -carry);
        return std::abs((cube - mm) + (cube_low + (carry + carry_low)));
    };
    double y = exp(log(mm) / 3.0);
    for (int i = 0; i < 8; ++i) {
        const double up = std::nextafter(y, 4.0), down = std::nextafter(y, 0.0);
        const double here = miss(y), above = miss(up), below = miss(down);
        if (above < here && above <= below) y = up;
        else if (below < here) y = down;
        else break;
    }
    const double root = std::ldexp(y, third);
    return x < 0.0 ? -root : root;
}

} // namespace banjo::pm
