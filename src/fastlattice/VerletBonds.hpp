#pragma once

// Serial CPU reference for the existing axial bond potential. This changes
// integration, not compliance, plastic return, damage or failure thresholds.
#include "fastlattice/FastLattice.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace banjo::fastlattice {
namespace verlet {
inline bool finite(Vec3 v) { return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z); }
template <typename Real> Vec3 widen(V3<Real> v) { return {double(v.x),double(v.y),double(v.z)}; }

template <typename Real>
void validate(const LatticeArrays<Real> &L, const StepSettings<Real> &S) {
    if constexpr (sizeof(Real)!=sizeof(double))
        throw std::invalid_argument("Verlet reference requires double precision");
    if (S.sphere_enabled||S.support.plane_count||S.node_contact.mode!=kNodeContactOff)
        throw std::invalid_argument("Verlet reference requires serial double free nodes without internal contacts");
    if (!(S.dt>0)||!std::isfinite(S.dt)||!finite(widen(S.gravity))||
        !std::isfinite(S.damping_fraction)||S.damping_fraction<0||S.damping_fraction>1||
        !std::isfinite(S.plastic_yield_stretch)||S.plastic_yield_stretch<0||
        !std::isfinite(S.plastic_hardening)||S.plastic_hardening<0||
        !std::isfinite(S.plate_half_thickness)||S.plate_half_thickness<0)
        throw std::invalid_argument("Verlet reference needs finite physical settings");
    for (std::uint32_t i=0;i<L.node_count;++i) {
        if (!(L.mass[i]>0)||!(L.inv_mass[i]>0)||!std::isfinite(L.mass[i])||!std::isfinite(L.inv_mass[i])||
            std::abs(L.mass[i]*L.inv_mass[i]-1)>1e-12||
            !finite(double(L.mass[i])*widen(S.gravity))||
            !finite(widen(load3(L.x0,i)))||!finite(widen(load3(L.u,i)))||
            !finite(widen(load3(L.u_prev,i)))||!finite(widen(load3(L.v,i))))
            throw std::invalid_argument("Verlet reference needs finite freely movable reciprocal node masses");
    }
    for (std::uint32_t j=0;j<L.bond_count;++j) if (L.alive[j]) {
        if (L.bond_a[j]>=L.node_count||L.bond_b[j]>=L.node_count||L.bond_a[j]==L.bond_b[j]||
            !(L.compliance[j]>0)||!std::isfinite(L.compliance[j])||
            !(L.rest_length[j]>0)||!std::isfinite(L.rest_length[j])||
            !std::isfinite(L.plastic_extension[j])||!std::isfinite(L.plastic_strain[j])||L.plastic_strain[j]<0)
            throw std::invalid_argument("Verlet reference needs finite positive live bond compliance and rest lengths");
        if (!finite(widen(load3(L.rest_edge,j))))
            throw std::invalid_argument("Verlet reference needs finite bond reference vectors");
    }
}

// Conservative local Hessian bound: |H_edge| <= max(1, |e|/l)/compliance.
// The mass-normalized pair quadratic form is bounded by twice the largest
// incident sum divided by node mass. It includes transverse geometric terms,
// unequal masses and current plastic rest lengths. Not a global trajectory
// guarantee: repeat before each kick, and refuse collapsed/nonfinite bonds.
template <typename Real>
void checkStep(const LatticeArrays<Real> &L, const StepSettings<Real> &S) {
    std::vector<double> frequency(L.node_count);
    for (std::uint32_t j=0;j<L.bond_count;++j) if (L.alive[j]) {
        const double l=length(bondVector(L,j,S.direct_arithmetic!=0));
        const double e=bondElasticExtension(L,j,S.direct_arithmetic!=0);
        if (!(l>1e-12)||!std::isfinite(l)||!std::isfinite(e))
            throw std::invalid_argument("Verlet reference cannot integrate a collapsed or nonfinite bond");
        const double c=std::max(1.0,std::abs(e)/l)/L.compliance[j];
        frequency[L.bond_a[j]]+=c*L.inv_mass[L.bond_a[j]];
        frequency[L.bond_b[j]]+=c*L.inv_mass[L.bond_b[j]];
    }
    const double fastest=frequency.empty()?0:*std::max_element(frequency.begin(),frequency.end());
    if (!std::isfinite(fastest)||double(S.dt)*std::sqrt(2*fastest)>=2)
        throw std::invalid_argument("Verlet timestep exceeds the current conservative spring stability bound");
}

template <typename Real>
void kick(const LatticeArrays<Real> &L,const StepSettings<Real> &S,Vec3 origin,RunStatus &status) {
    checkStep(L,S);
    std::vector<V3<Real>> impulses(L.node_count),after(L.node_count);
    for (std::uint32_t j=0;j<L.bond_count;++j) if (L.alive[j]) {
        const auto delta=bondVector(L,j,S.direct_arithmetic!=0);
        const Real l=length(delta),e=bondElasticExtension(L,j,S.direct_arithmetic!=0);
        const auto impulse=(Real(.5)*S.dt*(e/L.compliance[j])/l)*delta;
        const auto a=L.bond_a[j],b=L.bond_b[j];
        impulses[a]=impulses[a]+impulse;impulses[b]=impulses[b]-impulse;
    }
    Vec3 p{},angular{};
    for (std::uint32_t i=0;i<L.node_count;++i) {
        const auto before=load3(L.v,i);
        after[i]=before+L.inv_mass[i]*impulses[i];
        if (!finite(widen(after[i]))) throw std::overflow_error("Verlet bond kick velocity overflow");
        const Vec3 actual=double(L.mass[i])*(widen(after[i])-widen(before));
        p+=actual;angular+=cross(origin+widen(position(L,i)),actual);
    }
    const Vec3 total_p=status.bond_kick_roundoff_impulse_n_s+p;
    const Vec3 total_l=status.bond_kick_roundoff_angular_kg_m2_s+angular;
    if (!finite(total_p)||!finite(total_l)) throw std::overflow_error("Verlet bond arithmetic ledger overflow");
    for (std::uint32_t i=0;i<L.node_count;++i) store3(L.v,i,after[i]);
    status.bond_kick_roundoff_impulse_n_s=total_p;
    status.bond_kick_roundoff_angular_kg_m2_s=total_l;
}

template <typename Real>
void drift(const LatticeArrays<Real> &L,Real dt) {
    std::vector<V3<Real>> after(L.node_count);
    for (std::uint32_t i=0;i<L.node_count;++i) {
        after[i]=load3(L.u,i)+dt*load3(L.v,i);
        if (!finite(widen(after[i]))||!finite(widen(load3(L.x0,i)+after[i])))
            throw std::overflow_error("Verlet position drift overflow");
    }
    for (std::uint32_t i=0;i<L.node_count;++i) {
        store3(L.u_prev,i,load3(L.u,i));store3(L.u,i,after[i]);
    }
}
} // namespace verlet
} // namespace banjo::fastlattice
