// Axial plasticity in the explicit lattice lane.
//
// 1. The bond's return mapping IS material/NetworkMaterial.cpp advanceNetworkBond
//    on the same bond: same permanent extension, same plastic work, step for
//    step, over a path that loads, yields, unloads, reverses and yields again.
// 2. A ductile coupon has the answer the constitutive law prescribes: the
//    force-extension path is elastic, then the yield plateau (or the hardening
//    slope), then an elastic unload of the same slope through zero force at the
//    permanent set, and the permanent set is (D - n s_y h) / (1 + H) per bond.
// 3. With no declared yield strength -- or the law switched off -- every bond
//    state, node position and node velocity is bit for bit what it was.
// 4. The energy ledger closes: on a bar with no gravity, no supports, no
//    striker and no damping, kinetic + elastic + plastic + fracture equals the
//    kinetic energy it started with to about 1%, and the SAME bar with a
//    material that declares no yield strength leaves a residual of the same
//    size -- so what is left over is the solve's, not the ledger's.
// 5. The serial and parallel CPU backends are bit identical through a scene
//    that yields, and so is CUDA when the build has it.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"
#include "fastlattice/TileImpactScene.hpp"
#include "material/MaterialCompiler.hpp"
#include "material/NetworkMaterial.hpp"
#include "matter/BoxLattice.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;

void require(bool result, const std::string &message) {
    if (!result) throw std::runtime_error(message);
}

// ---------------------------------------------------------------------------
// One bond, hand built, so the constitutive law can be driven directly.
// ---------------------------------------------------------------------------
struct OneBond {
    std::vector<double> x0{0, 0, 0, 0, 0, 0};
    std::vector<double> u{0, 0, 0, 0, 0, 0};
    std::vector<double> rest_length{0.0}, compliance{0.0};
    std::vector<double> plastic_extension{0.0}, plastic_strain{0.0};
    std::vector<std::uint32_t> a{0}, b{1};

    OneBond(double rest, double bond_compliance) {
        x0[3] = rest;
        rest_length[0] = rest;
        compliance[0] = bond_compliance;
    }
    void setExtension(double extension) { u[3] = extension; }
    [[nodiscard]] LatticeArrays<double> arrays() {
        LatticeArrays<double> L{};
        L.node_count = 2;
        L.bond_count = 1;
        L.x0 = x0.data();
        L.u = u.data();
        L.bond_a = a.data();
        L.bond_b = b.data();
        L.rest_length = rest_length.data();
        L.compliance = compliance.data();
        L.plastic_extension = plastic_extension.data();
        L.plastic_strain = plastic_strain.data();
        return L;
    }
};

StepSettings<double> plasticSettings(double yield_stretch, double hardening) {
    StepSettings<double> s{};
    s.plastic_yield_stretch = yield_stretch;
    s.plastic_hardening = hardening;
    return s;
}

// The network lane's bond with this lattice bond's stiffness and yield force.
// directionalNetworkParameters gives stiffness = E A / L and yield force
// sigma_y A, so with A = 1 and L the bond's rest length, E = L / compliance and
// sigma_y = yield_stretch * L / compliance reproduce both exactly. Fracture is
// off because NetworkMaterial.cpp refuses to combine plasticity with it; the
// lattice does combine them, which is the departure section 1 of the checkpoint
// states.
struct NetworkBond {
    NetworkMaterial material;
    DirectionalNetworkParameters parameters;
    NetworkBondHistory history;
    NetworkBond(double rest, double compliance, double yield_stretch) {
        const double modulus = rest / compliance;
        material.name = "coupon";
        material.density_kg_m3 = 7870.0;
        material.young_modulus_pa = {modulus, modulus, modulus};
        material.tensile_strength_pa = {1.0e12, 1.0e12, 1.0e12};
        material.fracture_energy_j_m2 = {1.0e9, 1.0e9, 1.0e9};
        material.damping_ratio = 0.0;
        material.friction = 0.0;
        material.yield_strength_pa = yield_stretch * rest / compliance;
        material.hardening_ratio = 0.0;
        material.fracture_enabled = false;
        material.failure_law = NetworkFailureLaw::Cohesive;
        parameters = directionalNetworkParameters(material, {1.0, 0.0, 0.0}, 1.0, rest);
    }
};

void theReturnMappingIsTheNetworkLanes() {
    const double rest = 0.01;
    const double compliance = 4.7393364928909956e-10; // iron, 10 mm cell, horizon 1
    const double yield_stretch = 200.0e6 / 211.0e9;
    OneBond bond(rest, compliance);
    LatticeArrays<double> L = bond.arrays();
    const StepSettings<double> settings = plasticSettings(yield_stretch, 0.0);
    NetworkBond network(rest, compliance, yield_stretch);

    // Load past yield, unload through zero, push into compression past yield,
    // and come back: every branch of the mapping, in both signs.
    std::vector<double> path;
    for (int k = 0; k <= 60; ++k) path.push_back(3.0e-5 * k / 60.0);
    for (int k = 1; k <= 90; ++k) path.push_back(3.0e-5 - 6.0e-5 * k / 90.0);
    for (int k = 1; k <= 40; ++k) path.push_back(-3.0e-5 + 3.0e-5 * k / 40.0);

    // advanceNetworkBond's plasticity block, transcribed (NetworkMaterial.cpp
    // lines 106-117) onto the lattice bond's own yield extension. That is the
    // "same algebra" claim and it is checked exactly. The run against the real
    // advanceNetworkBond alongside it goes through
    // directionalNetworkParameters, which forms the yield extension as
    // (sigma_y A) / (E A / L) and therefore rounds differently by construction,
    // so it is checked to that rounding.
    double reference_plastic = 0.0, reference_work = 0.0;
    const double yield_extension = yield_stretch * rest;

    double lattice_work = 0.0, network_work = 0.0;
    double worst_reference = 0.0, worst_reference_work = 0.0;
    double worst_network = 0.0, worst_network_work = 0.0;
    std::size_t yields = 0;
    for (const double extension : path) {
        bond.setExtension(extension);
        // The extension the lattice measures is |x_b - x_a| - rest, a square
        // root of a square, so it equals the prescribed one only to rounding.
        // Both references are driven with the measured number, so what is
        // compared is the law and not the geometry.
        const double measured = bondElasticExtension(L, 0U, true) + bond.plastic_extension[0];
        const double increment = bondPlasticReturn(L, settings, 0U, true);
        lattice_work += increment;

        const double elastic = measured - reference_plastic;
        const double magnitude = std::abs(elastic);
        if (magnitude > yield_extension) {
            const double step = magnitude - yield_extension;
            reference_plastic += elastic < 0.0 ? -step : step;
            reference_work += 0.5 * (yield_extension + yield_extension) * step / compliance;
        }
        const NetworkBondUpdate update =
            advanceNetworkBond(network.material, network.parameters, network.history, measured, rest);
        network.history = update.history;
        network_work += update.plastic_increment_j;

        if (increment > 0.0) ++yields;
        worst_reference = std::max(worst_reference, std::abs(bond.plastic_extension[0] - reference_plastic));
        worst_reference_work = std::max(worst_reference_work, std::abs(lattice_work - reference_work));
        worst_network = std::max(worst_network,
                                 std::abs(bond.plastic_extension[0] - network.history.plastic_extension_m));
        worst_network_work = std::max(worst_network_work, std::abs(lattice_work - network_work));
    }
    std::cout << "  " << path.size() << " path points, " << yields << " of them plastic; permanent extension "
              << bond.plastic_extension[0] << " m, plastic work " << lattice_work << " J\n"
              << "    vs advanceNetworkBond's own block: max |d extension| = " << worst_reference
              << " m, max |d work| = " << worst_reference_work << " J\n"
              << "    vs advanceNetworkBond itself (" << network.history.plastic_extension_m << " m, "
              << network_work << " J): max |d extension| = " << worst_network << " m, max |d work| = "
              << worst_network_work << " J\n";
    require(yields > 20, "the path must actually yield, in both directions");
    require(worst_reference == 0.0, "the permanent extension is the network lane's block, bit for bit");
    require(worst_reference_work == 0.0, "the plastic work is the network lane's block, bit for bit");
    require(worst_network <= 1e-12 * yield_extension,
            "the permanent extension matches advanceNetworkBond to its parameter rounding");
    require(worst_network_work <= 1e-12 * std::max(1.0, network_work),
            "the plastic work matches advanceNetworkBond to its parameter rounding");
    require(bond.plastic_extension[0] < 0.0, "the reversed path ends with a compressive permanent extension");
}

// Linear isotropic hardening is the network lane's law with the term it
// declares and refuses to admit (validateNetworkMaterial requires
// hardening_ratio == 0). Checked against the closed form instead.
void hardeningFollowsTheClosedForm() {
    const double rest = 0.01, compliance = 4.7393364928909956e-10;
    const double yield_stretch = 200.0e6 / 211.0e9;
    for (const double hardening : {0.0, 0.02, 0.1}) {
        OneBond bond(rest, compliance);
        LatticeArrays<double> L = bond.arrays();
        const StepSettings<double> settings = plasticSettings(yield_stretch, hardening);
        const double yield_extension = yield_stretch * rest;
        const double target = 4.0 * yield_extension;
        // One step or a thousand: the return mapping of linear hardening is
        // path independent under monotone loading, so both must land on
        //   p = (target - yield) / (1 + H).
        bond.setExtension(target);
        double work = bondPlasticReturn(L, settings, 0U, true);
        const double closed_form = (target - yield_extension) / (1.0 + hardening);
        OneBond stepped(rest, compliance);
        LatticeArrays<double> Ls = stepped.arrays();
        double stepped_work = 0.0;
        for (int k = 1; k <= 1000; ++k) {
            stepped.setExtension(target * k / 1000.0);
            stepped_work += bondPlasticReturn(Ls, settings, 0U, true);
        }
        // Work: integral of the yield force over the flow,
        //   (yield * p + H p^2 / 2) / compliance.
        const double work_closed_form =
            (yield_extension * closed_form + 0.5 * hardening * closed_form * closed_form) / compliance;
        std::cout << "  H = " << hardening << ": p = " << bond.plastic_extension[0] << " m (one step), "
                  << stepped.plastic_extension[0] << " m (1000 steps), closed form " << closed_form << " m (d = "
                  << (bond.plastic_extension[0] - closed_form) << " / "
                  << (stepped.plastic_extension[0] - closed_form) << "); work " << work << " / " << stepped_work
                  << " J, closed form " << work_closed_form << " J\n";
        // The tolerances are set by the geometry, not by the law: the mapping
        // reads |x_b - x_a| - rest, a square root of a square, which equals the
        // prescribed extension only to an ulp of the rest length.
        require(std::abs(bond.plastic_extension[0] - closed_form) <= 1e-13 * rest,
                "one-step flow matches the closed form");
        require(std::abs(stepped.plastic_extension[0] - closed_form) <= 1e-10 * rest,
                "the flow is path independent under monotone loading");
        require(std::abs(work - work_closed_form) <= 1e-9 * work_closed_form, "one-step work matches");
        require(std::abs(stepped_work - work_closed_form) <= 1e-6 * work_closed_form, "stepped work matches");
    }
}

// ---------------------------------------------------------------------------
// A chain of cells: horizon 1 on a 1 x 1 cross-section, so the lattice is n - 1
// identical springs in series and the answer is closed form.
// ---------------------------------------------------------------------------
struct Coupon {
    MaterialDefinition material;
    CompiledBrittleMaterial compiled;
    std::unique_ptr<LatticeAsset> asset;
    ActiveMatter matter;
    BoxLatticeLayout layout{};
    LatticeSchedule schedule;
    LatticeState state;
    std::uint32_t cells{};
    double cell{}, dt{};

    Coupon(MaterialPreset preset, std::uint32_t n, double cell_size, double hardening, bool plastic)
        : cells(n), cell(cell_size) {
        material = makeReferenceMaterial(preset, 17);
        material.hardening_ratio = hardening;
        compiled = withStrengthDerivedFailure(compileElasticLatticeReference(material, cell, 1U), material);
        if (plastic) compiled = withPlasticFlow(compiled, material);
        asset = std::make_unique<LatticeAsset>(generateBoxTileLattice(
            {{cell * static_cast<double>(n), cell, cell}, cell, 1U}, compiled, &layout));
        matter.asset = asset.get();
        matter.material = compiled;
        for (const LatticeNodeRest &node : asset->nodes) {
            matter.nodes.push_back({node.local_position_m, node.local_position_m, {},
                                    node.represented_volume_m3 * compiled.density_kg_m3, {}});
            matter.reference_positions_world_m.push_back(node.local_position_m);
        }
        matter.bonds.resize(asset->bonds.size());
        schedule = buildLatticeSchedule(*asset, boxLatticeSlabs(layout, 1U, 1U));
        state = buildLatticeState(matter, schedule, Vec3{});
        dt = 0.5 * measureLatticeResolutionLimit(*asset, compiled).explicit_substep_limit_s;
    }

    [[nodiscard]] StepSettings<double> settings(double damping_fraction, unsigned iterations) const {
        StepSettings<double> s{};
        s.dt = dt;
        s.gravity = {0.0, 0.0, 0.0};
        s.constraint_iterations = iterations;
        s.damping_fraction = damping_fraction;
        s.sphere_enabled = 0;
        s.direct_arithmetic = 1;
        s.audit_energy = 0;
        s.plastic_yield_stretch = compiled.yield_stretch;
        s.plastic_hardening = compiled.plastic_hardening_ratio;
        s.node_contact.mode = kNodeContactOff;
        s.node_contact.bucket_mask = latticeContactBucketMask(state.node_count);
        s.support.plane_count = 0;
        return s;
    }

    // The node index at each end of the chain, by reference x.
    [[nodiscard]] std::pair<std::uint32_t, std::uint32_t> ends() const {
        std::uint32_t low = 0, high = 0;
        for (std::uint32_t i = 0; i < state.node_count; ++i) {
            if (state.x0[3 * i] < state.x0[3 * low]) low = i;
            if (state.x0[3 * i] > state.x0[3 * high]) high = i;
        }
        return {low, high};
    }
};

// Force in a bond of the chain, from its elastic extension.
double bondForce(const LatticeState &state, std::size_t bond) {
    const std::uint32_t a = state.bond_a[bond], b = state.bond_b[bond];
    double length_squared = 0.0;
    for (int k = 0; k < 3; ++k) {
        const double d = (state.x0[3 * b + k] + state.u[3 * b + k]) - (state.x0[3 * a + k] + state.u[3 * a + k]);
        length_squared += d * d;
    }
    const double elastic = std::sqrt(length_squared) - state.rest_length[bond] - state.plastic_extension[bond];
    return elastic / state.compliance[bond];
}

// Pull the chain to `peak` and back to zero grip displacement, holding both ends
// kinematically, quasi-statically (strong radial damping, many substeps a step).
// Returns the recorded force-extension path.
struct CouponPath {
    std::vector<double> extension_m, force_n;
    LatticeState state;
    double plastic_work_j{};
    std::uint32_t broken{};
};

// The grip is a node with zero mass AND zero inverse mass carrying a constant
// velocity: the constraint solve cannot move it (its inverse mass is zero), the
// radial damping sweep skips it (it reads mass, and a held node with a mass
// would be given a velocity the prediction then integrates -- which drove this
// chain at sixty times the grip amplitude before the mass was zeroed), and the
// prediction advances it at exactly the prescribed rate. So the coupon is pulled
// smoothly rather than in jumps, and the only shock is the start.
CouponPath pullAndRelease(Coupon &coupon, double peak, std::uint64_t substeps, std::uint64_t samples) {
    CouponPath path;
    const auto [low, high] = coupon.ends();
    LatticeState state = coupon.state;
    state.inv_mass[low] = state.mass[low] = 0.0;
    state.inv_mass[high] = state.mass[high] = 0.0;
    auto backend = makeCpuLatticeBackend(coupon.schedule, Precision::Double);
    const StepSettings<double> settings = coupon.settings(1.0, 4U);
    SphereState<double> sphere{};
    sphere.radius = sphere.mass = sphere.inertia = 1.0;
    const std::uint64_t chunk = std::max<std::uint64_t>(1, substeps / samples);
    const double rate = peak / (static_cast<double>(substeps) * coupon.dt);
    RunControl control{};
    control.max_steps = chunk;
    for (int direction : {1, -1}) {
        state.v[3 * high] = direction * rate;
        for (std::uint64_t done = 0; done < substeps; done += chunk) {
            backend->upload(state, settings, sphere);
            const RunStatus status = backend->run(control);
            backend->download(state, sphere);
            path.extension_m.push_back(state.u[3 * high]);
            path.force_n.push_back(bondForce(state, 0));
            path.plastic_work_j += status.plastic_work_j;
            path.broken += status.broken_bonds;
        }
    }
    path.state = state;
    return path;
}

// Where the unloading branch crosses zero force: the permanent set.
double zeroForceCrossing(const CouponPath &path) {
    for (std::size_t k = path.force_n.size() - 1; k > 0; --k) {
        if (path.force_n[k] <= 0.0 && path.force_n[k - 1] > 0.0) {
            const double t = path.force_n[k - 1] / (path.force_n[k - 1] - path.force_n[k]);
            return path.extension_m[k - 1] + t * (path.extension_m[k] - path.extension_m[k - 1]);
        }
    }
    require(false, "the unloading branch must cross zero force");
    return 0.0;
}

// ONE bond between two grips. The extension is prescribed exactly, so the whole
// pipeline -- the solve reading the plastic rest length, the mapping, the
// backend's accounting -- has a closed-form answer with no chain to share the
// flow out over, and it is checked at rounding.
void theCouponKeepsThePermanentSetTheLawPrescribes() {
    for (const double hardening : {0.0, 0.05}) {
        Coupon coupon(MaterialPreset::Iron, 2U, 0.01, hardening, true);
        require(coupon.state.bond_count == 1U, "two cells at horizon 1 are one spring");
        const double yield_extension = coupon.compiled.yield_stretch * coupon.cell;
        // How far past yield a bond may be taken before the failure surface
        // removes it. An iron bond goes at 2 * tensile / E = 2.37e-3 of stretch
        // against a yield stretch of 9.48e-4: the whole ductile window this
        // material has is a factor of 2.5, which the checkpoint reports as the
        // limit it is.
        const double ductile = (coupon.compiled.damage_end_stretch - coupon.compiled.yield_stretch) * coupon.cell;
        const double peak = yield_extension + 0.6 * ductile;
        const CouponPath path = pullAndRelease(coupon, peak, 40000, 200);
        require(path.broken == 0, "the coupon must not break");

        const double stiffness = 1.0 / coupon.state.compliance[0];
        const double plastic = (peak - yield_extension) / (1.0 + hardening);
        const double yield_force = yield_extension * stiffness;
        const double peak_force = (yield_extension + hardening * plastic) * stiffness;
        const double work = (yield_extension * plastic + 0.5 * hardening * plastic * plastic) * stiffness;
        const std::size_t top = path.force_n.size() / 2;
        const double slope_in = (path.force_n[1] - path.force_n[0]) / (path.extension_m[1] - path.extension_m[0]);
        const double slope_out = (path.force_n[top + 1] - path.force_n[top]) /
                                 (path.extension_m[top + 1] - path.extension_m[top]);
        const double measured = zeroForceCrossing(path);
        // The force at the last sample of the loading branch, and the force at
        // the very end, grip back at zero: the bond is a spring about its NEW
        // rest length, so it must be pushing there.
        const double plateau = path.force_n[top - 1];
        const double at_zero_grip = path.force_n.back();

        std::cout << "  one spring, H = " << hardening << ": yield force " << yield_force << " N, flow force "
                  << plateau << " N (law: " << peak_force << " N), elastic slope in " << slope_in
                  << " N/m, out " << slope_out << " N/m (law: " << stiffness << "), permanent set "
                  << measured * 1e6 << " um (law: " << plastic * 1e6 << "), permanent extension "
                  << path.state.plastic_extension[0] * 1e6 << " um, plastic work " << path.plastic_work_j
                  << " J (law: " << work << " J), force back at zero grip " << at_zero_grip << " N\n";
        require(std::abs(slope_in - stiffness) <= 1e-9 * stiffness, "the loading branch is the elastic slope");
        require(std::abs(slope_out - stiffness) <= 1e-9 * stiffness,
                "the unloading branch has the same elastic slope");
        require(std::abs(plateau - peak_force) <= 1e-3 * peak_force,
                "the flow force is the one the law prescribes");
        require(std::abs(path.state.plastic_extension[0] - plastic) <= 1e-3 * plastic,
                "the permanent extension is the law's");
        require(std::abs(measured - plastic) <= 1e-3 * plastic,
                "the unloading branch crosses zero force at the permanent set");
        require(std::abs(path.plastic_work_j - work) <= 1e-3 * work, "the plastic work is the area under the law");
        require(at_zero_grip < -0.5 * yield_force,
                "back at zero grip the bond pushes: it is a spring about its new rest length");
        if (hardening > 0.0) require(plateau > 1.02 * yield_force, "hardening raises the flow force above yield");
        if (hardening == 0.0) require(plateau == yield_force, "with no hardening the flow force is the yield force");
    }
}

// The same pull on a chain of sixteen cells, where the flow has somewhere to go.
// What is checked here is what a chain can state exactly: no bond is left
// outside the yield surface, the permanent set is the sum of the bonds'
// permanent extensions, and the chain unloads to it on the series elastic slope.
// The quasi-static closed form is REPORTED beside it rather than asserted
// tightly, because the mapping runs once per substep on the configuration the
// solve left: a bond can overshoot the yield surface inside a substep and the
// flow that takes it back is permanent, so the chain settles a little below the
// yield force having flowed a little more than the static answer.
void theChainCouponHoldsTheLawsInvariants() {
    for (const double hardening : {0.0, 0.05}) {
        const std::uint32_t cells = 16;
        Coupon coupon(MaterialPreset::Iron, cells, 0.01, hardening, true);
        const double springs = static_cast<double>(cells - 1U);
        const double yield_extension = coupon.compiled.yield_stretch * coupon.cell;
        const double ductile = (coupon.compiled.damage_end_stretch - coupon.compiled.yield_stretch) * coupon.cell;
        // With NO hardening the flow of a chain of identical springs is
        // indeterminate: the tangent modulus is zero, so nothing shares the next
        // increment out and it localises into one spring. The peak is chosen so
        // that even a fully localised flow stays inside one bond's ductile
        // window. Hardening removes the indeterminacy and the flow spreads.
        const double peak = hardening > 0.0
            ? springs * (yield_extension + 0.5 * ductile)
            : springs * yield_extension + 0.4 * ductile;
        const CouponPath path = pullAndRelease(coupon, peak, 200000, 200);
        require(path.broken == 0, "the chain coupon must not break");

        const double stiffness = 1.0 / coupon.state.compliance[0];
        const double series = stiffness / springs;
        const double closed_form = springs * (peak / springs - yield_extension) / (1.0 + hardening);
        const double measured = zeroForceCrossing(path);
        double summed = 0.0, worst_elastic = 0.0, flowed = 0.0;
        for (std::size_t k = 0; k < path.state.bond_count; ++k) {
            summed += path.state.plastic_extension[k];
            if (path.state.plastic_extension[k] != 0.0) flowed += 1.0;
            const double allowed =
                yield_extension + coupon.compiled.plastic_hardening_ratio * path.state.plastic_strain[k];
            const double elastic = std::abs(bondForce(path.state, k)) * coupon.state.compliance[k];
            worst_elastic = std::max(worst_elastic, elastic / allowed);
        }
        const std::size_t top = path.force_n.size() / 2;
        const double slope_out = (path.force_n[top + 1] - path.force_n[top]) /
                                 (path.extension_m[top + 1] - path.extension_m[top]);
        std::cout << "  " << springs << " springs, H = " << hardening << ": permanent set " << measured * 1e6
                  << " um, summed permanent extensions " << summed * 1e6 << " um, quasi-static closed form "
                  << closed_form * 1e6 << " um (" << 100.0 * (summed - closed_form) / closed_form
                  << "% more flow), " << flowed << " of " << springs
                  << " springs flowed, worst |elastic| / yield at the end " << worst_elastic
                  << ", unloading slope " << slope_out << " N/m (series stiffness " << series << ")\n";
        require(std::abs(measured - summed) <= 2e-3 * summed,
                "the chain unloads to the sum of its bonds' permanent extensions");
        require(worst_elastic <= 1.0 + 1e-9, "no bond is left outside the yield surface");
        require(std::abs(slope_out - series) <= 5e-3 * series, "the chain unloads on the series elastic slope");
        require(summed >= closed_form && summed <= 1.25 * closed_form,
                "the flow is the quasi-static answer plus the once-a-substep overshoot, never less");
        if (hardening > 0.0) require(flowed >= springs, "hardening spreads the flow over every spring");
        if (hardening == 0.0) require(flowed <= 0.5 * springs, "without hardening the flow localises");
    }
}

// ---------------------------------------------------------------------------
// The ledger. A free bar, no gravity, no supports, no striker, no damping: the
// only places energy can go are the bonds' elastic store, the plastic work and
// the motion.
// ---------------------------------------------------------------------------
struct Ledger {
    double initial_kinetic_j, kinetic_j, elastic_j, plastic_j, fracture_j, residual_j, dt_s;
    std::uint32_t broken;
    std::uint64_t steps;
};

// A free bar given a uniform stretching velocity: no gravity, no supports, no
// striker, no bond damping, no contact. The only places the energy it starts
// with can go are the bonds' elastic store, the plastic work, the fracture
// energy and the motion -- and whatever the integrator loses.
Ledger stretchingBar(double dt_factor, double rate, double duration_s, bool plastic) {
    // A little hardening (a declared property of this coupon, not of the
    // catalogue's iron) so the flow spreads over the whole bar instead of
    // localising into one bond and tearing it: the ledger is about where the
    // energy goes, not about where the flow goes.
    Coupon coupon(MaterialPreset::Iron, 24, 0.01, 0.05, plastic);
    LatticeState state = coupon.state;
    double centre = 0.0;
    for (std::uint32_t i = 0; i < state.node_count; ++i) centre += state.x0[3 * i];
    centre /= static_cast<double>(state.node_count);
    for (std::uint32_t i = 0; i < state.node_count; ++i) state.v[3 * i] = rate * (state.x0[3 * i] - centre);
    Ledger ledger{};
    ledger.initial_kinetic_j = latticeStateKineticEnergy(state);
    auto backend = makeCpuLatticeBackend(coupon.schedule, Precision::Double);
    StepSettings<double> settings = coupon.settings(0.0, 1U);
    settings.dt = coupon.dt * dt_factor;
    ledger.dt_s = settings.dt;
    SphereState<double> sphere{};
    sphere.radius = sphere.mass = sphere.inertia = 1.0;
    backend->upload(state, settings, sphere);
    RunControl control{};
    control.max_steps = static_cast<std::uint64_t>(duration_s / settings.dt);
    const RunStatus status = backend->run(control);
    backend->download(state, sphere);
    ledger.steps = status.total_steps;
    ledger.kinetic_j = latticeStateKineticEnergy(state);
    ledger.elastic_j = latticeStateElasticEnergy(state);
    ledger.plastic_j = status.plastic_work_j;
    ledger.fracture_j = status.removed_energy_j;
    ledger.broken = status.broken_bonds;
    ledger.residual_j = ledger.initial_kinetic_j -
        (ledger.kinetic_j + ledger.elastic_j + ledger.plastic_j + ledger.fracture_j);
    return ledger;
}

// The ledger. What is claimed, and what is not:
//
//   in = kinetic + elastic + plastic + fracture + RESIDUAL
//
// and the residual is the solve's own error, not a bookkeeping error. The
// control is what makes that a measurement rather than an assertion: the SAME
// bar with a material that declares no yield strength -- no plastic work at all,
// nothing of this change running -- leaves a residual of the same size. XPBD is
// implicit-Euler-like and loses energy on a mode with omega * dt near one; that
// loss is the lane's, it was there before plasticity, and plastic work is
// accounted separately from it.
//
// The substep sweep shows what the residual is made of: it changes SIGN between
// the coarsest and the finest substep, because two errors of opposite sign meet
// there -- the integrator's dissipation, and the return mapping running once a
// substep on the configuration the solve left, which flows a little too far when
// the substep is long. Neither exceeds about 1% of the energy put in over a
// sixteen-fold range of substeps, and the plastic work converges.
void theEnergyLedgerCloses() {
    const double rate = 100.0, duration = 1.6e-5;
    const Ledger elastic = stretchingBar(0.125, rate, duration, false);
    const double control = std::abs(elastic.residual_j) / elastic.initial_kinetic_j;
    std::cout << "  elastic control (no declared yield): in " << elastic.initial_kinetic_j << " J = kinetic "
              << elastic.kinetic_j << " + elastic " << elastic.elastic_j << " + plastic " << elastic.plastic_j
              << " + fracture " << elastic.fracture_j << " + residual " << elastic.residual_j << " J ("
              << 100.0 * control << "%)\n";
    require(elastic.broken == 0, "the elastic control must not break");
    require(elastic.plastic_j == 0.0, "a material with no yield strength does no plastic work");
    require(control < 0.02, "the lane's own integrator residual on this scene is under 2%");

    double previous_plastic = 0.0, worst = 0.0, finest_change = 1.0;
    for (const double dt_factor : {0.5, 0.25, 0.125, 0.0625}) {
        const Ledger l = stretchingBar(dt_factor, rate, duration, true);
        const double relative = std::abs(l.residual_j) / l.initial_kinetic_j;
        worst = std::max(worst, relative);
        std::cout << "  dt = " << l.dt_s << " s (" << l.steps << " substeps): in " << l.initial_kinetic_j
                  << " J = kinetic " << l.kinetic_j << " + elastic " << l.elastic_j << " + plastic " << l.plastic_j
                  << " + fracture " << l.fracture_j << " + residual " << l.residual_j << " J (" << 100.0 * relative
                  << "%), " << l.broken << " broken";
        if (previous_plastic > 0.0) {
            finest_change = std::abs(l.plastic_j - previous_plastic) / previous_plastic;
            std::cout << ", plastic work x " << l.plastic_j / previous_plastic << " on the last halving";
        }
        std::cout << '\n';
        require(l.broken == 0, "the ledger scene must not break");
        require(l.plastic_j > 0.25 * l.initial_kinetic_j, "the bar must actually yield, and substantially");
        require(relative < 0.05, "the ledger closes to better than 5% at every substep");
        previous_plastic = l.plastic_j;
    }
    std::cout << "  worst residual over the sweep " << 100.0 * worst
              << "% of the energy in, against the elastic control's " << 100.0 * control
              << "%; the plastic work moved " << 100.0 * finest_change << "% on the last halving\n";
    require(finest_change < 0.06, "the plastic work converges as the substep falls");
    require(worst < 0.05, "the residual never exceeds 5% of the energy put in");
}

// ---------------------------------------------------------------------------
// Nothing changes without a yield strength.
// ---------------------------------------------------------------------------
TileImpactRequest yieldingScene(BackendKind backend, Precision precision, unsigned blocks, bool plastic) {
    TileImpactRequest r;
    r.tile_material = MaterialPreset::Iron;
    r.tile_dimensions_m = {0.12, 0.04, 0.16};
    r.cell_size_m = 0.02;
    r.ball_radius_m = 0.03;
    r.ball_speed_m_s = 20.0;
    r.ball_gap_m = 0.0005;
    r.layout = SceneLayout::Flat;
    r.plasticity = plastic;
    r.backend = backend;
    r.precision = precision;
    r.blocks = blocks;
    r.threads_per_block = 256;
    return r;
}

struct Advanced {
    LatticeState state;
    SphereState<double> sphere;
    RunStatus status;
};

Advanced advance(const TileImpactRequest &request, std::uint64_t steps, unsigned threads = 0,
                 std::uint64_t steps_per_launch = 0) {
    auto setup = buildTileImpactSetup(request);
    Advanced out;
    out.state = buildLatticeState(setup->matter, setup->schedule, setup->origin);
    out.sphere = setup->sphere_world;
    out.sphere.center = out.sphere.center - V3<double>{setup->origin.x, setup->origin.y, setup->origin.z};
    std::unique_ptr<LatticeBackend> backend =
        request.backend == BackendKind::Cuda
            ? makeCudaLatticeBackend(setup->schedule, request.precision, request.threads_per_block)
        : request.backend == BackendKind::CpuParallel
            ? makeParallelCpuLatticeBackend(setup->schedule, request.precision, threads)
            : makeCpuLatticeBackend(setup->schedule, request.precision);
    backend->upload(out.state, setup->settings_scene, out.sphere);
    RunControl control{};
    control.max_steps = steps;
    control.steps_per_launch = steps_per_launch;
    out.status = backend->run(control);
    backend->download(out.state, out.sphere);
    return out;
}

double maxDifference(const std::vector<double> &a, const std::vector<double> &b) {
    require(a.size() == b.size(), "comparable arrays");
    double m = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) m = std::max(m, std::abs(a[i] - b[i]));
    return m;
}

void identical(const Advanced &a, const Advanced &b, const std::string &what) {
    require(maxDifference(a.state.u, b.state.u) == 0.0, what + ": positions");
    require(maxDifference(a.state.v, b.state.v) == 0.0, what + ": velocities");
    require(maxDifference(a.state.damage, b.state.damage) == 0.0, what + ": damage");
    require(maxDifference(a.state.plastic_extension, b.state.plastic_extension) == 0.0,
            what + ": plastic extension");
    require(maxDifference(a.state.plastic_strain, b.state.plastic_strain) == 0.0, what + ": plastic strain");
    require(a.state.alive == b.state.alive, what + ": the same bonds alive");
    require(a.status.broken_bonds == b.status.broken_bonds, what + ": the same broken count");
}

void withoutAYieldStrengthNothingChanges() {
    const std::uint64_t steps = 1500;
    // Glass declares no yield strength: switching the law on must change
    // nothing at all, which is the strongest form of the claim because the
    // switch is on and the compiled yield_stretch is what turns it off.
    TileImpactRequest glass_off = yieldingScene(BackendKind::Cpu, Precision::Double, 1, false);
    glass_off.tile_material = MaterialPreset::Glass;
    glass_off.ball_speed_m_s = 12.0;
    TileImpactRequest glass_on = glass_off;
    glass_on.plasticity = true;
    const Advanced a = advance(glass_off, steps), b = advance(glass_on, steps);
    std::cout << "  glass (no declared yield), law off vs on: broken " << a.status.broken_bonds << " / "
              << b.status.broken_bonds << ", plastic work " << b.status.plastic_work_j << " J\n";
    require(a.status.broken_bonds > 0, "the window must contain fracture");
    require(b.status.plastic_work_j == 0.0, "no declared yield strength, no plastic work");
    identical(a, b, "glass with the plastic law switched on");

    // Iron declares 200 MPa: with the law off it must still be the elastic lane.
    TileImpactRequest iron_off = yieldingScene(BackendKind::Cpu, Precision::Double, 1, false);
    const Advanced c = advance(iron_off, steps);
    std::cout << "  iron with the law off: broken " << c.status.broken_bonds << ", plastic work "
              << c.status.plastic_work_j << " J, permanent extensions "
              << maxDifference(c.state.plastic_extension, c.state.plastic_extension) << '\n';
    require(c.status.plastic_work_j == 0.0, "the law off does no plastic work");
    for (const double p : c.state.plastic_extension) require(p == 0.0, "the law off leaves no permanent extension");

    // ... and with the law on, on the same scene, it does flow.
    const Advanced d = advance(yieldingScene(BackendKind::Cpu, Precision::Double, 1, true), steps);
    std::size_t flowed = 0;
    for (const double p : d.state.plastic_extension) flowed += p != 0.0;
    std::cout << "  iron with the law on: broken " << d.status.broken_bonds << ", plastic work "
              << d.status.plastic_work_j << " J over " << flowed << " bonds, deepest permanent stretch "
              << d.status.max_plastic_stretch << '\n';
    require(d.status.plastic_work_j > 0.0 && flowed > 0, "iron flows on this scene");
}

void backendsAgreeThroughYield() {
    const std::uint64_t steps = 1500;
    const Advanced serial = advance(yieldingScene(BackendKind::Cpu, Precision::Double, 1, true), steps);
    std::size_t flowed = 0;
    for (const double p : serial.state.plastic_extension) flowed += p != 0.0;
    require(flowed > 20, "the parity window must contain plenty of flow");
    for (const unsigned threads : {2U, 4U, 8U}) {
        const Advanced parallel =
            advance(yieldingScene(BackendKind::CpuParallel, Precision::Double, 1, true), steps, threads);
        const double work_error = std::abs(parallel.status.plastic_work_j - serial.status.plastic_work_j) /
                                  std::max(1e-12, serial.status.plastic_work_j);
        std::cout << "  parallel x" << threads << ": broken " << parallel.status.broken_bonds << ", plastic work "
                  << parallel.status.plastic_work_j << " J, relative difference " << work_error << '\n';
        identical(serial, parallel, "parallel backend");
        // The parallel backend sums the work in per-thread partials, so its
        // total differs from the serial one by summation order alone, as the
        // CUDA backend's atomic sum of the removed fracture energy already does.
        require(work_error <= 1e-12, "the plastic work agrees to summation order");
    }
    if (!cudaLatticeAvailable()) {
        std::cout << "  [SKIP] CUDA backend not available: " << cudaLatticeDescription() << '\n';
        return;
    }
    for (const Precision precision : {Precision::Double, Precision::Float}) {
        for (const unsigned blocks : {1U, 4U}) {
            const Advanced cpu = advance(yieldingScene(BackendKind::Cpu, precision, blocks, true), steps);
            const Advanced gpu = advance(yieldingScene(BackendKind::Cuda, precision, blocks, true), steps, 0, 250);
            const double work_error = std::abs(gpu.status.plastic_work_j - cpu.status.plastic_work_j) /
                                      std::max(1e-12, cpu.status.plastic_work_j);
            std::cout << "  cuda " << precisionName(precision) << ", " << blocks << " block(s): broken "
                      << cpu.status.broken_bonds << " / " << gpu.status.broken_bonds << ", plastic work "
                      << cpu.status.plastic_work_j << " / " << gpu.status.plastic_work_j << " J, relative difference "
                      << work_error << '\n';
            identical(cpu, gpu, "cuda backend");
            require(work_error <= 1e-12, "the plastic work agrees to summation order");
        }
    }
}

} // namespace

int main() {
    try {
        theReturnMappingIsTheNetworkLanes();
        std::cout << "[PASS] the bond's return mapping is advanceNetworkBond's, bit for bit\n";
        hardeningFollowsTheClosedForm();
        std::cout << "[PASS] linear isotropic hardening follows the closed form\n";
        theCouponKeepsThePermanentSetTheLawPrescribes();
        std::cout << "[PASS] a ductile coupon keeps the permanent set the law prescribes\n";
        theChainCouponHoldsTheLawsInvariants();
        std::cout << "[PASS] a chain coupon holds the law's invariants and unloads to its permanent set\n";
        theEnergyLedgerCloses();
        std::cout << "[PASS] the energy ledger closes to the size of the lane's own integrator residual\n";
        withoutAYieldStrengthNothingChanges();
        std::cout << "[PASS] without a declared yield strength nothing changes, bit for bit\n";
        backendsAgreeThroughYield();
        std::cout << "[PASS] the backends agree bit for bit through a scene that yields\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "[FAIL] " << error.what() << '\n';
        return 1;
    }
}
