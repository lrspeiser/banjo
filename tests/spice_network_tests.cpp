#include "machines/SpiceNetwork.hpp"
#include "machines/Circuit.hpp"
#include <array>
#include <chrono>
#include <cmath>
#include <future>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#undef near
#elif defined(__linux__)
#include <unistd.h>
#endif

namespace {
using banjo::machines::SpiceBranch;
using banjo::machines::solveSpiceNetwork;
void near(double actual, double expected, double tolerance, const char *why) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(std::string(why) + ": " + std::to_string(actual));
}
void resistorAndCurrentLimit() {
    const std::vector<SpiceBranch> branches{{0,1,.1,0}, {0,1,.1,0}};
    const auto cv = solveSpiceNetwork(3,branches,0,1,1,24,false,0);
    near(cv[0]-cv[1],20,1e-11,"parallel network terminal voltage");
    near(cv[2],0,0,"isolated terminal gauge");
    const auto cc = solveSpiceNetwork(3,branches,0,1,1,24,true,2);
    near(cc[0]-cc[1],10,1e-11,"current-limited shared voltage");
    const auto empty = solveSpiceNetwork(3,{},0,1,1,24,true,0);
    for (double v : empty) near(v,0,0,"empty isolated network");
}
void bridgeAndMotor() {
    // Balanced Wheatstone bridge: the cross branch sees zero current.
    std::vector<SpiceBranch> bridge{{0,2,.1,0},{2,1,.05,0},{0,3,.2,0},{3,1,.1,0},{2,3,1,0}};
    const auto v = solveSpiceNetwork(4,bridge,0,1,1,12,false,0);
    near(v[2]-v[3],0,1e-12,"balanced bridge current");
    const double drop = v[0]-v[1];
    near((12-drop),drop/10,1e-11,"bridge source KCL");
    near(v[2]-v[1],drop*2/3,1e-11,"bridge voltage divider");
    // Winding R=2 ohms, back EMF=8 V, source 12 V with 1 ohm
    // internal resistance: current=(12-8)/3, never an assigned rotation.
    const auto motor = solveSpiceNetwork(2,{{0,1,.5,8}},0,1,1,12,false,0);
    near((motor[0]-motor[1]-8)/2,4.0/3,1e-12,"motor back EMF current");
    // Reversed supply connections reverse signed current.
    const auto reverse = solveSpiceNetwork(2,{{1,0,.5,0}},0,1,1,12,false,0);
    near((reverse[1]-reverse[0])/2,-4,1e-12,"reversed winding polarity");
}
void capacitorIslandAndIsolation() {
    // A charged capacitor's BE companion, isolated from an exhausted source.
    // V_old=6 V, ESR=.1 ohm, dt=.01 s, C=.1 F => R_eff=.2 ohm.
    const std::vector<SpiceBranch> branch{{2,3,5,6},{2,3,.1,0},{0,2,0,0}};
    const auto v = solveSpiceNetwork(5,branch,0,1,.1,12,true,0);
    near(v[2]-v[3],6*10/10.2,1e-11,"capacitor discharge island");
    near(v[0],0,0,"open supply has no leakage");
    near(v[1],0,0,"open return has no leakage");
    near(v[4],0,0,"unused node has no leakage");
    const double load_current = (v[2]-v[3])/10;
    const double capacitor_current = (v[2]-v[3]-6)/.2;
    near(load_current+capacitor_current,0,1e-12,"isolated island KCL");
    const double next = 6 + .01*capacitor_current/.1;
    const double delta = .5*.1*(next*next-36);
    const double heat = .01*(load_current*load_current*10+capacitor_current*capacitor_current*.1);
    const double numerical = .5*.1*(next-6)*(next-6);
    near(delta+heat+numerical,0,1e-12,"capacitor storage/heat/numerical balance");
}
void historyAndThreads() {
    std::array<std::future<void>,4> workers;
    for (std::size_t i=0;i<workers.size();++i) {
        workers[i]=std::async(std::launch::async,[i] {
            const double r=2+static_cast<double>(i);
            for(int k=0;k<100;++k) {
                const auto v=solveSpiceNetwork(2,{{0,1,1/r,0}},0,1,1,12,false,0);
                near(v[0]-v[1],12*r/(r+1),1e-11,"independent worlds share no trial state");
            }
        });
    }
    for(auto &worker:workers)worker.get();
    bool refused=false;
    try { (void)solveSpiceNetwork(2,{{0,1,std::numeric_limits<double>::quiet_NaN(),0}},0,1,1,12,false,0); }
    catch(const std::invalid_argument &){refused=true;}
    if(!refused)throw std::runtime_error("nonfinite conductance accepted");
    refused=false;
    try { (void)solveSpiceNetwork(2,{},0,1,1,12,true,1); }
    catch(const std::runtime_error &){refused=true;}
    if(!refused)throw std::runtime_error("current source without return accepted");
}
std::size_t memoryBytes() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX counters{};
    if (!GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS *>(&counters), sizeof(counters)))
        throw std::runtime_error("cannot read process memory");
    return counters.PrivateUsage;
#elif defined(__linux__)
    std::ifstream input("/proc/self/statm");
    std::size_t virtual_pages{}, resident_pages{};
    if (!(input >> virtual_pages >> resident_pages)) throw std::runtime_error("cannot read process memory");
    return resident_pages * static_cast<std::size_t>(sysconf(_SC_PAGESIZE));
#else
    return 0;
#endif
}
void boundedTrialMemory() {
#if defined(_WIN32) || defined(__linux__)
    const auto solve = [] {
        const auto v = solveSpiceNetwork(3,{{0,2,1,0},{2,1,.1,0}},0,1,1,12,false,0);
        near(v[0]-v[1],11,1e-11,"long-run voltage");
    };
    for(int k=0;k<1000;++k) solve();
    const auto before=memoryBytes();
    for(int k=0;k<6000;++k) solve();
    const auto after=memoryBytes();
    const auto growth=after>before?after-before:0;
    std::cout<<"6000 additional trials: memory growth "<<growth<<" bytes\n";
    // Allow bounded allocator/cache growth after warmup, not retention of a
    // circuit/netlist/command list for each simulation trial. No physics
    // tolerance changes: voltage/KCL/energy checks remain unchanged.
    if(growth>8*1024*1024)throw std::runtime_error("electrical trials retain unbounded circuit/history memory");
#else
    std::cout<<"long-run memory observation unavailable on this platform\n";
#endif
}
}
int main() {
    try {
        const auto start=std::chrono::steady_clock::now();
        if (std::string(banjo::machines::Circuit::solverName()) != "ngspice")
            throw std::runtime_error("Circuit is not wired to the ngspice backend");
        resistorAndCurrentLimit();bridgeAndMotor();capacitorIslandAndIsolation();historyAndThreads();boundedTrialMemory();
        std::cout<<"ngspice "<<banjo::machines::spiceVersion()<<" electrical oracles passed in "
                 <<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<" s\n";
        return 0;
    } catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}
}
