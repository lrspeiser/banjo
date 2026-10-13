#include "machines/SpiceNetwork.hpp"
#include <sharedspice.h>
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <locale>
#include <mutex>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>

namespace banjo::machines {
namespace {
std::string decimal(double value) {
    std::ostringstream out;
    out.imbue(std::locale::classic());
    out << std::setprecision(17) << std::scientific << value;
    return out.str();
}
// ngspice has process-global state. LiveWorld processes are isolated per player;
// serialize any in-process worlds/tests as well. No background simulation and
// no mutable transient history: every call is a fresh operating-point trial.
struct Session {
    std::mutex mutex;
    std::string diagnostic;
    bool exited{};
    static int output(char *message, int, void *context) {
        auto &s = *static_cast<Session *>(context);
        if (message && s.diagnostic.size() < 4096) {
            s.diagnostic += message;
            s.diagnostic += '\n';
        }
        return 0;
    }
    static int exit(int, bool, bool, int, void *context) {
        static_cast<Session *>(context)->exited = true;
        return 0;
    }
    Session() {
        if (ngSpice_Init(output, nullptr, exit, nullptr, nullptr, nullptr, this) != 0 || exited)
            throw std::runtime_error("circuit: cannot initialize ngspice: " + diagnostic);
        command("set nomoremode");
        command("set noaskquit");
        command("set num_threads=1");
    }
    void command(std::string text) {
        if (exited || ngSpice_Command(text.data()) != 0 || exited)
            throw std::runtime_error("circuit: ngspice command failed: " + diagnostic);
    }
};
Session &session() { static Session s; return s; }
}

const char *spiceVersion() { return NGSPICE_PACKAGE_VERSION; }

std::vector<double> solveSpiceNetwork(std::size_t n, const std::vector<SpiceBranch> &branches,
    std::size_t positive, std::size_t negative, double resistance, double voltage,
    bool limited, double current) {
    if (n == 0 || n > 128 || positive >= n || negative >= n || positive == negative ||
        !std::isfinite(resistance) || resistance <= 0 || !std::isfinite(voltage) ||
        !std::isfinite(current)) throw std::invalid_argument("circuit: invalid ngspice network");
    std::vector<std::size_t> parent(n);
    std::iota(parent.begin(), parent.end(), 0);
    const auto root = [&](std::size_t i) { while (parent[i] != i) i = parent[i]; return i; };
    for (const auto &b : branches) {
        if (b.a >= n || b.b >= n || b.a == b.b || !std::isfinite(b.conductance_s) ||
            b.conductance_s < 0 || !std::isfinite(b.emf_v))
            throw std::invalid_argument("circuit: invalid ngspice branch");
        if (b.conductance_s > 0) parent[root(b.b)] = root(b.a);
    }
    if (!limited) parent[root(negative)] = root(positive);
    // One arbitrary zero reference per conducting island. These are gauge
    // choices, not resistors between islands; an open wire never gains leakage.
    const auto node = [&](std::size_t i) { return root(i) == i ? std::string("0") : "n" + std::to_string(i); };
    std::vector<std::string> netlist{
        "Banjo bounded DC/BE companion network",
        ".options reltol=1e-12 abstol=1e-14 vntol=1e-12 gmin=0"};
    for (std::size_t i = 0; i < branches.size(); ++i) {
        const auto &b = branches[i];
        if (b.conductance_s == 0) continue;
        const auto middle = "x" + std::to_string(i);
        netlist.push_back("r" + std::to_string(i) + " " + node(b.a) + " " + middle + " " + decimal(1.0 / b.conductance_s));
        netlist.push_back("v" + std::to_string(i) + " " + middle + " " + node(b.b) + " dc " + decimal(b.emf_v));
    }
    if (limited) {
        // A zero source across separately gauged islands can be omitted. A
        // nonzero imposed current into an open island is physically unsolvable.
        if (root(positive) != root(negative) && current != 0)
            throw std::runtime_error("circuit: current source has no return path");
        if (current != 0)
            netlist.push_back("isupply " + node(negative) + " " + node(positive) + " dc " + decimal(current));
    } else {
        netlist.push_back("rsupply " + node(positive) + " source_internal " + decimal(resistance));
        netlist.push_back("vsupply source_internal " + node(negative) + " dc " + decimal(voltage));
    }
    // With no device at all ngspice has nothing to solve. Every independent
    // isolated node is its own zero gauge; no charge or energy is created.
    if (netlist.size() == 2) return std::vector<double>(n, 0.0);
    netlist.push_back(".end");
    auto &s = session();
    const std::lock_guard lock(s.mutex);
    s.diagnostic.clear();
    s.command("destroy all");
    std::vector<char *> lines;
    for (auto &line : netlist) lines.push_back(line.data());
    lines.push_back(nullptr);
    if (ngSpice_Circ(lines.data()) != 0 || s.exited)
        throw std::runtime_error("circuit: ngspice refused generated network: " + s.diagnostic);
    s.command("op");
    std::vector<double> result(n);
    for (std::size_t i = 0; i < n; ++i) {
        if (root(i) == i) continue;
        auto name = "v(" + node(i) + ")";
        const auto *v = ngGet_Vec_Info(name.data());
        if (!v || !v->v_realdata || v->v_length != 1 || !std::isfinite(v->v_realdata[0]))
            throw std::runtime_error("circuit: ngspice produced no finite operating point: " + s.diagnostic);
        result[i] = v->v_realdata[0];
    }
    return result;
}
}
