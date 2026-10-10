"""The transcendental functions for the game's own Python: correctly rounded,
so the same bits on every platform.

Python's `math.sin`, `math.acos`, `math.expm1`, `x ** y` and the rest call
the platform's C library, and the C libraries do not agree in the last bit:
measured on 300,000 arguments each, Python on Windows and on Linux gave
different `sin` for 3% of them, `acos` for 8%, `expm1` for 37% and `x ** 2`
for one in a thousand. What the game's Python computes becomes the world --
where `world_seed` stands a machine, which way a rover's brain steers, the
turn a chat-built part is given -- so a world generated on Render (Linux) was
not the world generated from the same seed on Windows: the solar farm on
terrain 7 stood one unit in the last place apart.

The engine's C++ has `banjo::pm` (src/numeric/PortableMath.hpp) for this, and
these are the same functions: each returns the double nearest the true value,
which is one answer whatever computes it, so this module, the engine and every
platform give the same bits (docs/floating-point-model.md, profile
banjo-cpu-precise-v2; tests/portable_math_py_tests.py checks it against the
C++ test's own table). They are computed in `decimal` -- software arithmetic,
the same on every machine -- carried to 50 digits and rounded once, so the
answer is the correctly rounded double unless the true value lies within
about 1e-45 of halfway between two doubles.

`math.hypot`, `math.dist`, `math.sqrt`, `math.fsum`, `math.prod`,
`math.degrees` and `math.radians` are CPython's own correctly rounded
arithmetic, already the same everywhere, and stay as they are.

Arguments and errors are Python's: a domain error raises ValueError and an
overflow OverflowError, where `math` would. They cost tens of microseconds a
call, against tens of nanoseconds for `math`; the game calls them a few
hundred times a second.
"""
from __future__ import annotations

import math
from decimal import Context, Decimal, ROUND_HALF_EVEN
from fractions import Fraction

__all__ = ["sin", "cos", "tan", "asin", "acos", "atan", "atan2", "exp", "expm1", "log", "log1p", "pow", "cbrt"]

_DIGITS = 50                                    # carried, then rounded once to a double
_BIG = Context(prec=_DIGITS, rounding=ROUND_HALF_EVEN, Emin=-99999, Emax=99999)
_EXACT = Context(prec=2000, rounding=ROUND_HALF_EVEN, Emin=-99999, Emax=99999)
_C60 = Context(prec=_DIGITS + 10, rounding=ROUND_HALF_EVEN, Emin=-99999, Emax=99999)
_C65 = Context(prec=_DIGITS + 15, rounding=ROUND_HALF_EVEN, Emin=-99999, Emax=99999)
_HALF_PI_DOUBLE = 1.5707963267948966             # pi/2 rounded to a double


def _pi(digits: int) -> Decimal:
    """pi to `digits` digits, by Machin's formula, once at import."""
    c = Context(prec=digits + 10, rounding=ROUND_HALF_EVEN)

    def arctan_inverse(n: int) -> Decimal:
        x = c.divide(Decimal(1), Decimal(n))
        n2, term, total, k, sign = n * n, x, x, 1, -1
        while True:
            term = c.divide(term, Decimal(n2))
            piece = c.divide(term, Decimal(2 * k + 1))
            if piece.is_zero() or piece.adjusted() < total.adjusted() - digits - 5:
                break
            total = c.add(total, piece) if sign > 0 else c.subtract(total, piece)
            sign, k = -sign, k + 1
        return total

    return c.multiply(Decimal(4), c.subtract(c.multiply(Decimal(4), arctan_inverse(5)), arctan_inverse(239)))


# Enough for the argument reduction of any double: the largest is 1.8e308, and
# the reduced argument must keep 50 digits after cancelling 309 and the
# closest approach of a double to a multiple of pi/2 (about 1e-19).
_PI = _pi(420)
_HALF_PI = Context(prec=420).divide(_PI, Decimal(2))


def _to_double(value: Decimal) -> float:
    """The double nearest a decimal: CPython converts through its own correctly
    rounded string conversion, the same on every platform."""
    return float(value)


def _finite(x: float, name: str) -> float:
    """The argument as a float, as `math` takes it (an int, a bool, anything with __float__)."""
    return x if type(x) is float else float(x)


# -- sin, cos, tan ------------------------------------------------------------

def _reduce(x: float) -> tuple[Decimal, int]:
    """x = r + n pi/2 with |r| <= pi/4, r to 50 digits whatever x is."""
    d = Decimal(x)
    places = max(0, d.adjusted()) + 80
    c = Context(prec=places + _DIGITS, rounding=ROUND_HALF_EVEN, Emin=-99999, Emax=99999)
    n = c.divide(d, _HALF_PI).to_integral_value(rounding=ROUND_HALF_EVEN)
    r = c.subtract(d, c.multiply(n, _HALF_PI))
    return r, int(n) % 4                         # Python's modulo: 0..3 whatever n's sign


def _sin_series(r: Decimal) -> Decimal:
    c = _C60
    r2 = c.multiply(r, r)
    term, total, k = r, r, 1
    while True:
        term = c.divide(c.multiply(term, r2), Decimal((2 * k) * (2 * k + 1)))
        if term.is_zero() or term.adjusted() < total.adjusted() - _DIGITS - 8:
            return total
        total = c.subtract(total, term) if k % 2 else c.add(total, term)
        k += 1


def _cos_series(r: Decimal) -> Decimal:
    c = _C60
    r2 = c.multiply(r, r)
    term, total, k = Decimal(1), Decimal(1), 1
    while True:
        term = c.divide(c.multiply(term, r2), Decimal((2 * k - 1) * (2 * k)))
        if term.is_zero() or term.adjusted() < total.adjusted() - _DIGITS - 8:
            return total
        total = c.subtract(total, term) if k % 2 else c.add(total, term)
        k += 1


def sin(x: float) -> float:
    x = _finite(x, "sin")
    if not math.isfinite(x) or x == 0.0:
        return math.sin(x)                       # nan, the ValueError for inf, and a signed zero
    r, q = _reduce(x)
    value = _sin_series(r) if q % 2 == 0 else _cos_series(r)
    return _to_double(-value if q >= 2 else value)


def cos(x: float) -> float:
    x = _finite(x, "cos")
    if not math.isfinite(x) or x == 0.0:
        return math.cos(x)
    r, q = _reduce(x)
    value = _cos_series(r) if q % 2 == 0 else _sin_series(r)
    return _to_double(-value if q in (1, 2) else value)


def tan(x: float) -> float:
    x = _finite(x, "tan")
    if not math.isfinite(x) or x == 0.0:
        return math.tan(x)
    r, q = _reduce(x)
    s, c = _sin_series(r), _cos_series(r)
    value = _BIG.divide(s, c) if q % 2 == 0 else _BIG.divide(-c, s)
    return _to_double(value)


# -- atan, atan2, asin, acos ---------------------------------------------------

def _atan_positive(t: Decimal) -> Decimal:
    """atan(t) for t >= 0, to 50 digits."""
    c = _C65
    flip = t > 1
    if flip:
        t = c.divide(Decimal(1), t)
    halvings = 0
    while t > Decimal("0.05"):                    # atan t = 2 atan(t / (1 + sqrt(1 + t^2)))
        t = c.divide(t, c.add(Decimal(1), c.add(Decimal(1), c.multiply(t, t)).sqrt(c)))
        halvings += 1
    t2 = c.multiply(t, t)
    term, total, k = t, t, 1
    while True:
        term = c.multiply(term, t2)
        piece = c.divide(term, Decimal(2 * k + 1))
        if piece.is_zero() or piece.adjusted() < total.adjusted() - _DIGITS - 10:
            break
        total = c.subtract(total, piece) if k % 2 else c.add(total, piece)
        k += 1
    total = c.multiply(total, Decimal(2 ** halvings))
    return c.subtract(_HALF_PI, total) if flip else total


def _atan2_decimal(y: Decimal, x: Decimal) -> Decimal:
    """atan2 of two decimals, not both zero, as a decimal."""
    c = _C65
    ay, ax = abs(y), abs(x)
    if ax.is_zero():
        angle = _HALF_PI
    elif ay <= ax:
        angle = _atan_positive(c.divide(ay, ax))
    else:
        angle = c.subtract(_HALF_PI, _atan_positive(c.divide(ax, ay)))
    if x.is_signed() and not x.is_zero():
        angle = c.subtract(_PI, angle)
    return -angle if y.is_signed() else angle


def atan(x: float) -> float:
    x = _finite(x, "atan")
    if not math.isfinite(x) or x == 0.0:
        return math.atan(x)                      # +-pi/2 at +-inf, nan, a signed zero
    value = _atan_positive(abs(Decimal(x)))
    return _to_double(-value if x < 0 else value)


def atan2(y: float, x: float) -> float:
    y, x = _finite(y, "atan2"), _finite(x, "atan2")
    if not (math.isfinite(y) and math.isfinite(x)) or y == 0.0:
        return math.atan2(y, x)                  # CPython's own special cases: zeros, infinities, nan
    if x == 0.0:
        return math.copysign(_HALF_PI_DOUBLE, y)
    if x > 0.0 and abs(y) < x * 2.0 ** -900:
        return _tiny_quotient(y, x)
    return _to_double(_atan2_decimal(Decimal(y), Decimal(x)))


def _tiny_quotient(y: float, x: float) -> float:
    """atan2(y, x) where it is y/x to within 2^-1800 of it -- perhaps a denormal,
    perhaps exactly halfway between two of them, where the true value lies just
    inside the half and so rounds towards zero (as banjo::pm::atan2 does)."""
    t = Fraction(y) / Fraction(x)
    nearest = float(t)                           # correctly rounded, ties to even
    if Fraction(nearest) == t:
        return nearest
    other = math.nextafter(nearest, -math.inf if Fraction(nearest) > t else math.inf)
    if abs(Fraction(nearest) - t) == abs(Fraction(other) - t):
        return min(nearest, other, key=abs)      # a tie: the smaller is the nearer to atan
    return nearest


def _complement_root(x: float) -> Decimal:
    """sqrt(1 - x^2) for |x| <= 1, to 50 digits (1 - x^2 is exact here)."""
    d = Decimal(x)
    one_minus = _EXACT.subtract(Decimal(1), _EXACT.multiply(d, d))
    c = _C65
    return one_minus.sqrt(c)


def asin(x: float) -> float:
    x = _finite(x, "asin")
    if not math.isfinite(x) or x == 0.0 or abs(x) > 1.0:
        return math.asin(x)                      # nan, a signed zero, the ValueError outside [-1, 1]
    return _to_double(_atan2_decimal(Decimal(x), _complement_root(x)))


def acos(x: float) -> float:
    x = _finite(x, "acos")
    if not math.isfinite(x) or abs(x) > 1.0:
        return math.acos(x)
    if x == 1.0:
        return 0.0
    return _to_double(_atan2_decimal(_complement_root(x), Decimal(x)))


# -- exp, expm1, log, log1p, pow, cbrt -----------------------------------------

def _overflow_checked(value: float, name: str) -> float:
    if math.isinf(value):
        raise OverflowError("math range error")
    return value


def exp(x: float) -> float:
    x = _finite(x, "exp")
    if not math.isfinite(x) or x == 0.0:
        return math.exp(x)
    if x > 709.8:
        raise OverflowError("math range error")
    if x < -746.0:
        return 0.0
    return _overflow_checked(_to_double(Decimal(x).exp(_BIG)), "exp")


def expm1(x: float) -> float:
    x = _finite(x, "expm1")
    if not math.isfinite(x) or x == 0.0:
        return math.expm1(x)
    if x > 709.8:
        raise OverflowError("math range error")
    if x < -40.0:
        return -1.0                              # exp(x) - 1 rounds to -1 below about -37.4
    d = Decimal(x)
    c = _C65
    if abs(x) < 1e-5:                            # x + x^2/2 + ..., no cancellation
        term, total, k = d, d, 1
        while True:
            k += 1
            term = c.divide(c.multiply(term, d), Decimal(k))
            if term.is_zero() or term.adjusted() < total.adjusted() - _DIGITS - 8:
                break
            total = c.add(total, term)
        return _to_double(total)
    return _overflow_checked(_to_double(c.subtract(d.exp(c), Decimal(1))), "expm1")


def log(x: float, base: float | None = None) -> float:
    if base is not None:
        return _to_double(_BIG.divide(_log_decimal(_finite(x, "log")), _log_decimal(_finite(base, "log"))))
    x = _finite(x, "log")
    if not math.isfinite(x) or x <= 0.0 or x == 1.0:
        return math.log(x)                       # inf, nan, the ValueError at and below 0, and log 1 = 0
    return _to_double(_log_decimal(x))


def _log_decimal(x: float) -> Decimal:
    if not math.isfinite(x) or x <= 0.0:
        math.log(x)                              # raises as math would
        raise ValueError("math domain error")
    c = _C60
    return Decimal(x).ln(c)


def log1p(x: float) -> float:
    x = _finite(x, "log1p")
    if not math.isfinite(x) or x == 0.0 or x <= -1.0:
        return math.log1p(x)
    d = Decimal(x)
    c = _C65
    if abs(x) < 1e-10:                           # x - x^2/2 + x^3/3 ...
        term, total, k = d, d, 1
        while True:
            k += 1
            term = c.multiply(term, -d)
            piece = c.divide(term, Decimal(k))
            if piece.is_zero() or piece.adjusted() < total.adjusted() - _DIGITS - 8:
                break
            total = c.add(total, piece)
        return _to_double(total)
    return _to_double(_EXACT.add(Decimal(1), d).ln(c))


def pow(x: float, y: float) -> float:
    """x ** y for floats, as Python's float power, correctly rounded.

    A negative base with a fractional exponent raises ValueError here, as
    `math.pow` does (Python's `**` would make a complex number)."""
    x, y = _finite(x, "pow"), _finite(y, "pow")
    if y == 1.0:
        return x
    if not (math.isfinite(x) and math.isfinite(y)) or x == 0.0 or y == 0.0 or x == 1.0:
        return math.pow(x, y)                    # the C99 special cases, which CPython handles itself
    if y == 2.0:
        return _overflow_checked(x * x, "pow")
    negative = x < 0.0
    if negative:
        if y != math.floor(y):
            raise ValueError("math domain error")
        odd = int(y) % 2 == 1 if abs(y) < 2.0 ** 53 else False
    else:
        odd = False
    d, e = abs(Decimal(x)), Decimal(y)
    c = _C65
    if y == math.floor(y) and abs(y) <= 64:      # an exact power, rounded once
        value = _EXACT.power(d, int(y)) if y > 0 else c.divide(Decimal(1), _EXACT.power(d, -int(y)))
    else:
        exponent = c.multiply(e, d.ln(c))
        if exponent > 710:
            raise OverflowError("math range error")
        if exponent < -746:
            return -0.0 if negative and odd else 0.0
        value = exponent.exp(c)
    result = _overflow_checked(_to_double(c.plus(value)), "pow")
    return -result if negative and odd else result


def cbrt(x: float) -> float:
    x = _finite(x, "cbrt")
    if not math.isfinite(x) or x == 0.0:
        return x
    c = _C65
    d = abs(Decimal(x))
    root = c.power(d, c.divide(Decimal(1), Decimal(3)))
    for _ in range(2):                           # Newton on r^3 = d, from 50 digits to more
        root = c.subtract(root, c.divide(c.subtract(c.multiply(c.multiply(root, root), root), d),
                                         c.multiply(Decimal(3), c.multiply(root, root))))
    value = _to_double(root)
    return -value if x < 0 else value
