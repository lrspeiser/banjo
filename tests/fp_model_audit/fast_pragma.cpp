// Asks for fast math in the source, with no compiler option at all.
#if defined(_MSC_VER) && !defined(__clang__)
#pragma float_control(precise, off)
#pragma fp_contract(on)
#elif defined(__clang__)
#pragma clang fp contract(fast)
#else
#pragma GCC optimize("fast-math")
#endif

double fast_pragma(double a, double b, double c) { return a * b + c; }
