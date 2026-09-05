#include "rigid/JoltWorld.hpp"
#include "material/MaterialCatalog.hpp"
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace banjo;
namespace {
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
template<class F> void rejects(F f){bool rejected=false;try{f();}catch(const std::invalid_argument&){rejected=true;}require(rejected,"unsupported transfer must reject");}
void same(const RigidSnapshot &a,const RigidSnapshot &b) {
    require(length(a.center_of_mass_world_m-b.center_of_mass_world_m)==0&&
        length(a.linear_velocity_m_s-b.linear_velocity_m_s)==0&&length(a.angular_velocity_rad_s-b.angular_velocity_rad_s)==0&&
        a.orientation_world.w==b.orientation_world.w&&a.orientation_world.x==b.orientation_world.x&&
        a.orientation_world.y==b.orientation_world.y&&a.orientation_world.z==b.orientation_world.z,"rejection preserves both body states");
}
// Independent homogeneous-box principal-axis torque response.
Vec3 angularChange(Vec3 torque,Vec3 dimensions,double mass,Quat q) {
    const Quat inverse{q.w,-q.x,-q.y,-q.z};const auto local=inverse.rotate(torque);
    return q.rotate({12*local.x/(mass*(dimensions.y*dimensions.y+dimensions.z*dimensions.z)),
        12*local.y/(mass*(dimensions.x*dimensions.x+dimensions.z*dimensions.z)),
        12*local.z/(mass*(dimensions.x*dimensions.x+dimensions.y*dimensions.y))});
}
}
int main(){try {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron})for(bool central:{true,false}) {
        const auto material=makeReferenceMaterial(preset);
        JoltWorld world;world.setGravity({});
        const Vec3 da{.1,.15,.2},db{.15,.12,.08};
        const Quat qa{std::cos(.3),0,0,std::sin(.3)},qb{std::cos(.2),0,std::sin(.2),0};
        world.addBox({1,da,material,{{-.3,.1,0},qa,{.2,-.1,.3},{.1,.2,-.3}},false});
        world.addBox({2,db,material,{{.3,-.1,0},qb,{-.1,.3,-.2},{-.2,.3,.1}},false});
        const auto a=world.mechanicalState(1),b=world.mechanicalState(2);
        const Vec3 pa=a.motion.center_of_mass_world_m+Vec3{.03,.04,-.02},pb=b.motion.center_of_mass_world_m+Vec3{-.02,.03,.01};
        const Vec3 j=.4*a.mass_kg*(central?normalized(pb-pa):Vec3{.3,.7,-.2});
        const auto unchanged=[&]{same(a.motion,world.snapshot(1));same(b.motion,world.snapshot(2));};
        rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,j,1);});unchanged();
        world.setPairContactOwner(1,2,PairContactOwner::External);
        rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,j,-1);});unchanged();
        rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,{std::numeric_limits<double>::quiet_NaN(),0,0},1);});unchanged();
        rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,{1e10,0,0},1);});unchanged();
        rejects([&]{(void)world.applyPairImpulse(1,2,a.motion.center_of_mass_world_m,{0,1e5,0},j,1);});unchanged();
        rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,{1e100,0,0},1);});unchanged();
        world.pinToWorld(2);rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,j,1);});unchanged();world.releaseFromWorld(2);
        const auto report=world.applyPairImpulse(1,2,pa,pb,j,1e-5);
        const auto aa=world.snapshot(1),bb=world.snapshot(2);
        require(length(aa.linear_velocity_m_s-(a.motion.linear_velocity_m_s+j/a.mass_kg))<1e-7&&
            length(bb.linear_velocity_m_s-(b.motion.linear_velocity_m_s-j/b.mass_kg))<1e-7,"equal/opposite linear impulse");
        const auto expected_a=a.motion.angular_velocity_rad_s+angularChange(cross(pa-a.motion.center_of_mass_world_m,j),da,a.mass_kg,qa);
        const auto expected_b=b.motion.angular_velocity_rad_s+angularChange(cross(pb-b.motion.center_of_mass_world_m,-j),db,b.mass_kg,qb);
        require(length(aa.angular_velocity_rad_s-expected_a)<2e-6&&length(bb.angular_velocity_rad_s-expected_b)<2e-6,"oriented unequal box torque oracle");
        require(length(aa.center_of_mass_world_m-a.motion.center_of_mass_world_m)==0&&length(bb.center_of_mass_world_m-b.motion.center_of_mass_world_m)==0,"impulse does not drift positions");
        const double scale=report.before.kinetic_energy_j+std::abs(report.impulse_work_j);
        require(std::abs(report.numerical_energy_change_j)<1e-12+2e-7*scale,"measured float transfer energy residual");
        require(length(report.momentum_error_kg_m_s)<1e-7*(a.mass_kg+b.mass_kg)&&length(report.angular_momentum_error_kg_m2_s)<1e-7*(a.mass_kg+b.mass_kg),"measured linear/angular transfer residuals");
        require(length(report.applied_couple_kg_m2_s-cross(pa-pb,j))<1e-14,"noncentral couple explicitly accounted");
        if(central)require(length(report.applied_couple_kg_m2_s)<1e-14,"central impulse has no net couple");
        else require(length(report.applied_couple_kg_m2_s)>.01*a.mass_kg,"noncentral fixture supplies a real couple");
        const auto measured=world.mechanicalTotals();
        require(measured.kinetic_energy_j==report.after.kinetic_energy_j&&length(measured.linear_momentum_kg_m_s-report.after.linear_momentum_kg_m_s)==0,"receipt matches actual runtime state");
        const auto removal=world.applyPairImpulse(1,2,pa,pb,-j,1e-5);
        require(removal.impulse_work_j<0&&removal.after.kinetic_energy_j<removal.before.kinetic_energy_j,"opposite transfer accounts for energy withdrawal");
        require(std::abs(removal.impulse_work_j+report.impulse_work_j)<1e-12+3e-7*scale,"reversed impulse work matches within float rounding");
        // An insufficient budget must reject before either body is modified.
        require(std::abs(report.numerical_energy_change_j)>0,"fixture exercises nonzero float rounding");
        world.applyRigidState(1,a.motion);world.applyRigidState(2,b.motion);
        rejects([&]{(void)world.applyPairImpulse(1,2,pa,pb,j,.5*std::abs(report.numerical_energy_change_j));});unchanged();
        const auto reverse=world.applyPairImpulse(2,1,pb,pa,-j,1e-5);
        same(aa,world.snapshot(1));same(bb,world.snapshot(2));
        require(std::abs(reverse.impulse_work_j-report.impulse_work_j)<1e-12,"reversed IDs preserve impulse work");
        world.step(1.0/240);
        require(length(world.snapshot(1).center_of_mass_world_m-(aa.center_of_mass_world_m+aa.linear_velocity_m_s/240))<1e-7,"transferred velocity drives live motion");
        require(world.drainImpacts().empty(),"no duplicate Jolt impact response");
        std::cout<<materialPresetName(preset)<<" central="<<central<<" work="<<report.impulse_work_j<<" dE="<<report.numerical_energy_change_j<<" dP="<<length(report.momentum_error_kg_m_s)<<" dH="<<length(report.angular_momentum_error_kg_m2_s)<<'\n';
    }
    JoltWorld fixed;const auto material=makeReferenceMaterial(MaterialPreset::Oak);
    fixed.addBox({1,{.1,.1,.1},material,{},false});fixed.addBox({2,{.1,.1,.1},material,{{1,0,0},{},{},{}},true});
    fixed.setPairContactOwner(1,2,PairContactOwner::External);const auto before=fixed.snapshot(1);
    rejects([&]{(void)fixed.applyPairImpulse(1,2,{},{},{1,0,0},1);});same(before,fixed.snapshot(1));
    std::cout<<"[PASS] audited live pair impulse, oriented torque, roundoff rejection and runtime motion\n";return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
