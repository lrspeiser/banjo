#pragma once
#include "fastlattice/FastLattice.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>
namespace banjo::fastlattice {
// Absolute SI local accuracy bounds shared by both source implementations.
struct ContactAccuracySettings {
    double minimum_step_s{1e-12};
    unsigned maximum_halvings{12};
    double position_m{1e-8},velocity_m_s{1e-4};
    double orientation_rad{1e-5},angular_velocity_rad_s{1e-4};
    double damage_fraction{1e-5},history_strain{1e-5};
    double plastic_extension_m{1e-8},plastic_strain{1e-5};
    double energy_j{1e-6},impulse_n_s{1e-6},angular_impulse_kg_m2_s{1e-7};
};
struct ContactAccuracyDifference {
    bool accepted{},topology_agrees{};
    unsigned attempted_intervals{},rejected_intervals{};
    double accepted_interval_s{},suggested_interval_s{},normalized_error{};
    std::string error_metric;
    // Worst full/two-half comparison from the last attempted interval. Scalars
    // use x only; vectors retain all components and use their difference norm.
    // Values/bound share the units of the named quantity and accuracy setting.
    // Orientation uses angular distance against zero. These are observations,
    // never applied loads.
    Vec3 error_full_value{},error_fine_value{};
    double error_bound{},compared_interval_s{};
    bool error_is_vector{};
};
inline double contactRotationDistance(Quat a,Quat b) {
    const double an=std::hypot(std::hypot(a.w,a.x),std::hypot(a.y,a.z));
    const double bn=std::hypot(std::hypot(b.w,b.x),std::hypot(b.y,b.z));
    if(!std::isfinite(an)||!std::isfinite(bn)||an<=0||bn<=0)
        throw std::invalid_argument("contact accuracy source rotation is invalid");
    const double aw=a.w/an,ax=a.x/an,ay=a.y/an,az=a.z/an;
    const double bw=b.w/bn,bx=b.x/bn,by=b.y/bn,bz=b.z/bn;
    const double minus=std::hypot(std::hypot(aw-bw,ax-bx),std::hypot(ay-by,az-bz));
    const double plus=std::hypot(std::hypot(aw+bw,ax+bx),std::hypot(ay+by,az+bz));
    return 4*std::asin(std::min(1.0,.5*std::min(minus,plus)));
}
class ContactAccuracyComparison {
public:
    const ContactAccuracySettings &s;
    ContactAccuracyDifference &result;
    double error{};
    std::string metric{"material state"};
    ContactAccuracyComparison(const ContactAccuracySettings &bounds,ContactAccuracyDifference &out):s(bounds),result(out) {
        result.error_metric.clear();result.error_bound=0;result.error_full_value={};result.error_fine_value={};result.error_is_vector=false;
    }
    void compare(Vec3 x,Vec3 y,double bound,bool is_vector) {
        const double e=(is_vector?length(x-y):std::abs(x.x-y.x))/bound;
        if(!std::isfinite(e))throw std::overflow_error("contact accuracy comparison is nonfinite");
        if(e>error){error=e;result.error_metric=metric;result.error_full_value=x;result.error_fine_value=y;
            result.error_bound=bound;result.error_is_vector=is_vector;}
    }
    void scalar(double x,double y,double bound){compare({x,0,0},{y,0,0},bound,false);}
    void vector(Vec3 x,Vec3 y,double bound){compare(x,y,bound,true);}
    void array(const std::vector<double> &x,const std::vector<double> &y,double bound){
        if(x.size()!=y.size())throw std::logic_error("contact accuracy material dimensions changed");
        for(std::size_t i=0;i<x.size();++i)scalar(x[i],y[i],bound);
    }
    void materialState(const LatticeState &a,const LatticeState &b){
    metric="material position";array(a.u,b.u,s.position_m);
    metric="material velocity";array(a.v,b.v,s.velocity_m_s);
    // u_prev samples different times in full and half steps, so cannot be
    // directly compared. Rollback preserves it; accepted integration owns it.
    metric="material damage/history";array(a.damage,b.damage,s.damage_fraction);
    array(a.prev_tensile,b.prev_tensile,s.history_strain);
    array(a.prev_compressive,b.prev_compressive,s.history_strain);
    array(a.prev_shear,b.prev_shear,s.history_strain);
    metric="material plastic state";array(a.plastic_extension,b.plastic_extension,s.plastic_extension_m);
    array(a.plastic_strain,b.plastic_strain,s.plastic_strain);
    }
    void materialLedgers(const RunStatus &ast,const RunStatus &bst){
    const auto load=[&](const ExternalLoadLedger &x,const ExternalLoadLedger &y) {
        scalar(x.work_j,y.work_j,s.energy_j);
        vector(x.requested_impulse_n_s,y.requested_impulse_n_s,s.impulse_n_s);
        vector(x.impulse_n_s,y.impulse_n_s,s.impulse_n_s);
        vector(x.requested_angular_impulse_kg_m2_s,y.requested_angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
        vector(x.angular_impulse_kg_m2_s,y.angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
    };
    const auto &x=ast,&y=bst;
    metric="external/gravity transfer";load(x.external_load,y.external_load);load(x.gravity_load,y.gravity_load);
    if(x.external_sources.size()!=y.external_sources.size())throw std::logic_error("contact accuracy force sources changed");
    for(std::size_t i=0;i<x.external_sources.size();++i) {
        if(x.external_sources[i].source!=y.external_sources[i].source)throw std::logic_error("contact accuracy force identity changed");
        load(x.external_sources[i].load,y.external_sources[i].load);
    }
    metric="target contact work (J)";scalar(x.external_point_transfer.work_j,y.external_point_transfer.work_j,s.energy_j);
    metric="target contact impulse (N s)";
    vector(x.external_point_transfer.impulse_n_s,y.external_point_transfer.impulse_n_s,s.impulse_n_s);
    metric="target contact angular impulse (kg m2/s)";
    vector(x.external_point_transfer.angular_impulse_kg_m2_s,y.external_point_transfer.angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
    metric="target boundary/correction";vector(x.fixed_boundary.impulse_n_s,y.fixed_boundary.impulse_n_s,s.impulse_n_s);
    vector(x.fixed_boundary.angular_impulse_kg_m2_s,y.fixed_boundary.angular_impulse_kg_m2_s,s.angular_impulse_kg_m2_s);
    vector(x.bond_kick_roundoff_impulse_n_s,y.bond_kick_roundoff_impulse_n_s,s.impulse_n_s);
    vector(x.bond_kick_roundoff_angular_kg_m2_s,y.bond_kick_roundoff_angular_kg_m2_s,s.angular_impulse_kg_m2_s);
    metric="target numerical integration";scalar(x.integration_numerical_energy_j,y.integration_numerical_energy_j,s.energy_j);
    metric="material work/loss";
    scalar(x.removed_energy_j,y.removed_energy_j,s.energy_j);
    scalar(x.plastic_work_j,y.plastic_work_j,s.energy_j);
    scalar(x.plastic_return_numerical_loss_j,y.plastic_return_numerical_loss_j,s.energy_j);
    scalar(x.damping_dissipated_j,y.damping_dissipated_j,s.energy_j);

    }
    void sources(const std::vector<RigidSnapshot> &a,const std::vector<RigidSnapshot> &b,const char *label){
        if(a.size()!=b.size())throw std::logic_error("contact accuracy source dimensions changed");
        for(std::size_t i=0;i<a.size();++i){const auto &x=a[i],&y=b[i];
            metric=std::string(label)+" position";vector(x.center_of_mass_world_m,y.center_of_mass_world_m,s.position_m);
            metric=std::string(label)+" velocity";vector(x.linear_velocity_m_s,y.linear_velocity_m_s,s.velocity_m_s);
            metric=std::string(label)+" angular velocity";vector(x.angular_velocity_rad_s,y.angular_velocity_rad_s,s.angular_velocity_rad_s);
            metric=std::string(label)+" orientation";scalar(contactRotationDistance(x.orientation_world,y.orientation_world),0,s.orientation_rad);
        }
    }
};
} // namespace banjo::fastlattice
