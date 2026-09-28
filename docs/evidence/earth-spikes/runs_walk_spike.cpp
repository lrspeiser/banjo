// SPIKE, not a feature: does holding the ground as RUNS cost anything to walk?
//
// The plan (docs/earth-and-mining-plan.md, 4.1) turns each ground column from
// four fixed doubles (rock top, soil, sand, loose) into a list of runs held CSR:
//
//     col_start : uint32[cells + 1]
//     run_top   : double[]
//     run_kind  : uint8[]
//
// Everything that reads the ground today goes through height(c), surface(c) and
// volumes(); if the indirection is expensive, the plan is in trouble before it
// starts. This measures the four shapes of access the engine actually makes, on
// the valley's own size (156 x 125 = 19,500 columns), both layouts, same work:
//
//   1. a full height sweep        -- Environment::heights(), for the page
//   2. a full volumes sweep       -- the ledger, by kind
//   3. random column lookups      -- every contact asks the ground what it is
//   4. a whole-field neighbour compare -- a pessimistic bound on relax(), which
//      in truth only ever walks the frontier
//
// This is a measurement of a memory layout, NOT of the engine. The real figure
// comes from 60 s of the valley once stage 1 lands.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <random>
#include <vector>

namespace {

constexpr int kNx = 156, kNz = 125;                 // the valley
constexpr std::size_t kCells = std::size_t(kNx) * kNz;
constexpr double kDx = 0.25;
constexpr int kKinds = 10;

using Clock = std::chrono::steady_clock;
double msOf(Clock::time_point a, Clock::time_point b) {
    return std::chrono::duration<double, std::milli>(b - a).count();
}

// ---- today: four fixed layers -------------------------------------------
struct Layers {
    std::vector<double> rock, soil, sand, loose;
    double height(std::size_t c) const { return rock[c] + soil[c] + sand[c] + loose[c]; }
    // TerrainField::surface: loose first, then sand, then soil, else rock.
    int surface(std::size_t c) const {
        if (loose[c] > 0.0) return 1;
        if (sand[c] > 0.0) return 2;
        if (soil[c] > 0.0) return 1;
        return 0;
    }
    std::size_t bytes() const { return 4 * kCells * sizeof(double); }
};

// ---- the plan: runs, CSR ------------------------------------------------
struct Runs {
    std::vector<std::uint32_t> start;
    std::vector<double> top;
    std::vector<std::uint8_t> kind;
    double height(std::size_t c) const { return top[start[c + 1] - 1]; }
    int surface(std::size_t c) const { return kind[start[c + 1] - 1]; }
    std::size_t bytes() const {
        return start.size() * 4 + top.size() * 8 + kind.size();
    }
};

// A valley's worth of ground, and the same ground as runs. Run counts as the
// plan's generation would leave them: bedrock, weathered rock, subsoil, topsoil
// everywhere, a vein in some columns, sand in some, and (when `mined`) two more
// runs in the tenth of columns a mine has reached.
void build(Layers &a, Runs &b, bool mined, std::uint64_t seed) {
    std::mt19937_64 rng(seed);
    std::uniform_real_distribution<double> unit(0.0, 1.0);
    a.rock.resize(kCells); a.soil.resize(kCells); a.sand.resize(kCells); a.loose.resize(kCells);
    b.start.assign(kCells + 1, 0);
    b.top.clear(); b.kind.clear();
    b.top.reserve(kCells * 7); b.kind.reserve(kCells * 7);
    for (std::size_t c = 0; c < kCells; ++c) {
        const double ground = 1.0 + 0.4 * std::sin(double(c) * 0.01);
        const double topsoil = 0.15 + 0.1 * unit(rng);
        const double subsoil = 0.6 + 0.3 * unit(rng);
        const bool sandy = unit(rng) < 0.2;
        const double sand = sandy ? 0.1 + 0.1 * unit(rng) : 0.0;
        a.rock[c] = ground - topsoil - subsoil - sand;
        a.soil[c] = subsoil + (sandy ? 0.0 : topsoil);
        a.sand[c] = sand;
        a.loose[c] = sandy ? topsoil : 0.0;

        double y = ground - topsoil - subsoil - sand - 30.0;   // 30 m of earth
        const auto run = [&](double thickness, int k) {
            y += thickness;
            b.top.push_back(y);
            b.kind.push_back(std::uint8_t(k));
        };
        run(26.0, 0);                                  // bedrock
        if (unit(rng) < 0.25) { run(0.4, 5); run(0.6, 0); }  // a vein, and rock over it
        else run(1.0, 0);
        run(3.0, 4);                                   // weathered rock
        run(subsoil, 1);                               // subsoil
        if (sandy) { run(sand, 2); run(topsoil, 3); } else run(topsoil, 1);
        if (mined && unit(rng) < 0.1) { run(0.0, 9); run(0.0, 0); }  // a void and its roof
        b.start[c + 1] = std::uint32_t(b.top.size());
    }
}

volatile double sink = 0.0;

struct Result { double sweep, volumes, random, neighbours; };

Result timeLayers(const Layers &g, const std::vector<std::uint32_t> &picks, int reps) {
    Result r{};
    std::vector<float> out(kCells);
    auto t0 = Clock::now();
    for (int n = 0; n < reps; ++n)
        for (std::size_t c = 0; c < kCells; ++c) out[c] = float(g.height(c));
    auto t1 = Clock::now();
    double total = 0.0;
    for (int n = 0; n < reps; ++n) {
        double by[kKinds] = {};
        for (std::size_t c = 0; c < kCells; ++c) {
            by[0] += g.rock[c]; by[1] += g.soil[c]; by[2] += g.sand[c]; by[1] += g.loose[c];
        }
        total += by[0] + by[1] + by[2];
    }
    auto t2 = Clock::now();
    double got = 0.0;
    for (int n = 0; n < reps; ++n)
        for (std::uint32_t c : picks) got += g.height(c) + g.surface(c);
    auto t3 = Clock::now();
    double drops = 0.0;
    for (int n = 0; n < reps; ++n)
        for (int j = 1; j < kNz - 1; ++j)
            for (int i = 1; i < kNx - 1; ++i) {
                const std::size_t c = std::size_t(j) * kNx + i;
                const double h = g.height(c);
                const double worst = std::max(std::max(h - g.height(c - 1), h - g.height(c + 1)),
                                              std::max(h - g.height(c - kNx), h - g.height(c + kNx)));
                if (worst > 0.1 * g.surface(c)) drops += worst;
            }
    auto t4 = Clock::now();
    sink = total + got + drops + out[0];
    r.sweep = msOf(t0, t1) / reps; r.volumes = msOf(t1, t2) / reps;
    r.random = msOf(t2, t3) / reps; r.neighbours = msOf(t3, t4) / reps;
    return r;
}

Result timeRuns(const Runs &g, const std::vector<std::uint32_t> &picks, int reps) {
    Result r{};
    std::vector<float> out(kCells);
    auto t0 = Clock::now();
    for (int n = 0; n < reps; ++n)
        for (std::size_t c = 0; c < kCells; ++c) out[c] = float(g.height(c));
    auto t1 = Clock::now();
    double total = 0.0;
    for (int n = 0; n < reps; ++n) {
        double by[kKinds] = {};
        for (std::size_t c = 0; c < kCells; ++c) {
            const std::uint32_t from = g.start[c], to = g.start[c + 1];
            double below = g.top[from] - 26.0;   // the run below the first is the floor
            for (std::uint32_t k = from; k < to; ++k) {
                by[g.kind[k]] += g.top[k] - below;
                below = g.top[k];
            }
        }
        total += by[0] + by[1] + by[2];
    }
    auto t2 = Clock::now();
    double got = 0.0;
    for (int n = 0; n < reps; ++n)
        for (std::uint32_t c : picks) got += g.height(c) + g.surface(c);
    auto t3 = Clock::now();
    double drops = 0.0;
    for (int n = 0; n < reps; ++n)
        for (int j = 1; j < kNz - 1; ++j)
            for (int i = 1; i < kNx - 1; ++i) {
                const std::size_t c = std::size_t(j) * kNx + i;
                const double h = g.height(c);
                const double worst = std::max(std::max(h - g.height(c - 1), h - g.height(c + 1)),
                                              std::max(h - g.height(c - kNx), h - g.height(c + kNx)));
                if (worst > 0.1 * g.surface(c)) drops += worst;
            }
    auto t4 = Clock::now();
    sink = total + got + drops + out[0];
    r.sweep = msOf(t0, t1) / reps; r.volumes = msOf(t1, t2) / reps;
    r.random = msOf(t2, t3) / reps; r.neighbours = msOf(t3, t4) / reps;
    return r;
}

void report(const char *what, const Result &a, const Result &b) {
    std::printf("%-26s %9.4f %9.4f   %+6.1f%%\n", what, a.sweep, b.sweep,
                100.0 * (b.sweep / a.sweep - 1.0));
    (void)what;
}

} // namespace

int main() {
    Layers layers;
    Runs runs, mined;
    Layers unused;
    build(layers, runs, false, 12345);
    build(unused, mined, true, 12345);

    std::mt19937_64 rng(99);
    std::uniform_int_distribution<std::uint32_t> any(0, std::uint32_t(kCells - 1));
    std::vector<std::uint32_t> picks(100000);
    for (auto &p : picks) p = any(rng);

    const int reps = 200;
    // Warm both up before either is timed.
    timeLayers(layers, picks, 5);
    timeRuns(runs, picks, 5);

    const Result a = timeLayers(layers, picks, reps);
    const Result b = timeRuns(runs, picks, reps);
    const Result c = timeRuns(mined, picks, reps);

    std::printf("the valley: %zu columns\n", kCells);
    std::printf("runs a column: %.2f fresh, %.2f mined\n",
                double(runs.top.size()) / kCells, double(mined.top.size()) / kCells);
    std::printf("bytes: four layers %zu KB, runs %zu KB (%.2fx), mined %zu KB\n\n",
                layers.bytes() / 1024, runs.bytes() / 1024,
                double(runs.bytes()) / double(layers.bytes()), mined.bytes() / 1024);

    std::printf("%-26s %9s %9s %9s\n", "per call, ms", "layers", "runs", "mined");
    std::printf("%-26s %9.4f %9.4f %9.4f   runs %+.1f%%\n", "1 full height sweep",
                a.sweep, b.sweep, c.sweep, 100.0 * (b.sweep / a.sweep - 1.0));
    std::printf("%-26s %9.4f %9.4f %9.4f   runs %+.1f%%\n", "2 full volumes sweep",
                a.volumes, b.volumes, c.volumes, 100.0 * (b.volumes / a.volumes - 1.0));
    std::printf("%-26s %9.4f %9.4f %9.4f   runs %+.1f%%\n", "3 100k random lookups",
                a.random, b.random, c.random, 100.0 * (b.random / a.random - 1.0));
    std::printf("%-26s %9.4f %9.4f %9.4f   runs %+.1f%%\n", "4 whole-field neighbours",
                a.neighbours, b.neighbours, c.neighbours,
                100.0 * (b.neighbours / a.neighbours - 1.0));

    std::printf("\nper column, ns:  height sweep  layers %.2f  runs %.2f\n",
                1e6 * a.sweep / kCells, 1e6 * b.sweep / kCells);
    std::printf("the valley's own budget: a step is 4.68 s / 60 s of world over 14,400 steps"
                " = 0.325 ms a step\n");
    return sink == 12345.0 ? 1 : 0;   // keep the sink
}
