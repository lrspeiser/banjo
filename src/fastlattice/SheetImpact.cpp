#include "fastlattice/SheetImpact.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include "rigid/JoltWorld.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace banjo::fastlattice {
namespace {
Vec3 at(const std::vector<double>&v,unsigned i){return {v[3*i],v[3*i+1],v[3*i+2]};}
MechanicalTotals measure(const DoubleFixedSource &source,const LatticeState &s){
    MechanicalTotals out;for(const auto &b:source.bodies())out+=measureRigidMechanics(b);
    out.kinetic_energy_j+=latticeStateKineticEnergy(s);out.elastic_energy_j+=latticeStateElasticEnergy(s);
    for(unsigned i=0;i<s.node_count;++i){const auto j=s.mass[i]*at(s.v,i);
        out.mass_kg+=s.mass[i];out.linear_momentum_kg_m_s+=j;out.angular_momentum_kg_m2_s+=cross(s.origin+at(s.x0,i)+at(s.u,i),j);}
    return out;
}
}
struct SheetImpact::Impl {
    JoltWorld geometry;MaterialShapeBinding head;MaterialDefinition sheet;
    LatticeAsset asset;LatticeSchedule schedule;LatticeState state;std::unique_ptr<LatticeBackend> target;
    std::unique_ptr<DoubleFixedSource> source;MechanicalTotals initial;double dt{},cell{},contact_loss{},roundoff{},drift{};
    Vec3 contact_p{},contact_l{},couple{},drift_p{},drift_l{};
    Impl(MaterialPreset material,MaterialPreset pick,double h,double scale,Vec3 point,double speed):sheet(makeReferenceMaterial(material,17)),cell(h){
        if(h!=.002||!std::isfinite(scale)||scale<=0||scale>1||!std::isfinite(point.x)||!std::isfinite(point.z)||point.y!=0||
           std::abs(point.x)>.008||std::abs(point.z)>.012||!std::isfinite(speed)||speed<0||speed>8)throw std::invalid_argument("unsupported sheet resolution/timestep/strike declaration");
        geometry.setGravity({});const auto tool=makeReferenceMaterial(pick,17);
        const RigidPrimitive tip{PrimitiveKind::Box,0,{.008,.004,.002}}, shaft{PrimitiveKind::Box,0,{.002,.04,.002}};
        const double m1=tip.volume()*tool.density_kg_m3,m2=shaft.volume()*tool.density_kg_m3;
        const double center=(m1*.004+m2*.026)/(m1+m2);
        auto inertia=tip.inertia(m1);const auto shaft_inertia=shaft.inertia(m2);
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)inertia.m[i][j]+=shaft_inertia.m[i][j];
        const double parallel=m1*std::pow(.004-center,2)+m2*std::pow(.026-center,2);
        inertia.m[0][0]+=parallel;inertia.m[2][2]+=parallel;
        geometry.addCompound({1,{{tip,{0,.004-center,0},{},tool,0},{shaft,{0,.026-center,0},{},tool,0}},
            tool,{{point.x,center,point.z},{},{0,-speed,0},{}},m1+m2,inertia});
        head=geometry.bindMaterialShape(1);
        source=std::make_unique<DoubleFixedSource>(std::vector<RigidMechanicalState>{geometry.mechanicalState(1)},std::vector<FixedVelocityLink>{});
        const auto law=withPlasticFlow(withFailureLaw(compileElasticLatticeReference(sheet,h,1),sheet,h,1),sheet);
        const Vec3 dimensions{.04,.004,.04};
        if(dimensions.x/h*dimensions.y/h*dimensions.z/h>1024)throw std::invalid_argument("sheet exceeds bounded node budget");
        asset=generateBoxTileLattice({dimensions,h,1},law);ActiveMatter matter;matter.asset=&asset;matter.material=law;
        for(const auto &n:asset.nodes){const auto p=n.local_position_m;matter.nodes.push_back({p,p,{},n.represented_volume_m3*sheet.density_kg_m3,{}});matter.reference_positions_world_m.push_back(p);}
        matter.bonds.resize(asset.bonds.size());schedule=buildLatticeSchedule(asset);state=buildLatticeState(matter,schedule,{});
        for(unsigned i=0;i<state.node_count;++i)if(std::abs(state.x0[3*i])>.02-h*1.01||std::abs(state.x0[3*i+2])>.02-h*1.01)state.inv_mass[i]=0;
        StepSettings<double> settings{};settings.dt=scale*std::min(1e-7,.05*latticeStateSubstepLimit(state));
        settings.audit_energy=1;settings.bond_integrator=kBondVelocityVerlet;
        settings.plastic_yield_stretch=law.yield_stretch;settings.plastic_hardening=law.plastic_hardening_ratio;
        dt=settings.dt;target=makeCpuLatticeBackend(schedule,Precision::Double);target->upload(state,settings,{});initial=measure(*source,state);
    }
    DoubleFixedManifoldTransfer contact(){
        SphereState<double> unused;target->download(state,unused);const auto bodies=source->bodies();std::vector<MaterialSurfaceWitness> witnesses;
        const RigidPrimitive voxel{PrimitiveKind::Box,0,{cell,cell,cell}};const auto &pose=bodies[0].motion;
        for(unsigned i=0;i<state.node_count;++i){const auto p=state.origin+at(state.x0,i)+at(state.u,i);
            if(length(p-pose.center_of_mass_world_m)>.028+cell)continue;
            const auto q=pose.orientation_world;
            const auto local=Quat{q.w,-q.x,-q.y,-q.z}.rotate(p-pose.center_of_mass_world_m);
            // Conservative oriented part bounds, expanded by the cell's sphere.
            // Exact native clipped-face geometry still admits every contact.
            if(std::abs(local.x)>.004+cell||std::abs(local.z)>.001+cell)continue;
            const auto hits=geometry.materialShapeContactsAtPose(head,{pose.center_of_mass_world_m,pose.orientation_world},p,voxel,{},1e-8,64,MaterialContactGeometry::ClippedFace).contacts;
            if(state.inv_mass[i]==0){if(!hits.empty())throw std::runtime_error("pick reached ideal fixed boundary");continue;}
            for(const auto &hit:hits){const auto law=combineContactMaterials(compileContactMaterial(sheet),hit.body_contact);
                witnesses.push_back({i,hit.point_on_body_world_m,hit.normal_world,hit.gap_m,{law.static_friction,law.dynamic_friction,law.restitution}});}
        }
        return applyDoubleFixedLocalSurfaceManifold(*source,*target,witnesses,{cell*1.8,1,32,4096},0);
    }
    void step(){
        DoubleFixedStep receipt;
        try{receipt=advanceDoubleFixedTargetStep(*source,*target,dt,[&](double){return contact();});}
        catch(...){SphereState<double> unused;target->download(state,unused);throw;}
        drift+=receipt.free_drift.numerical_energy_j;drift_p+=receipt.free_drift.momentum_residual_n_s;drift_l+=receipt.free_drift.angular_residual_kg_m2_s;
        for(const auto &r:receipt.contacts){contact_loss+=r.contact.dissipated_energy_j+r.contact.reconciliation_loss_j;roundoff+=r.source_roundoff_energy_j;
            contact_p+=r.momentum_residual_n_s;contact_l+=r.angular_residual_kg_m2_s;couple+=r.contact.geometry_couple_kg_m2_s;}
        SphereState<double> unused;target->download(state,unused);
    }
};
SheetImpact::SheetImpact(MaterialPreset a,MaterialPreset b,double h,double scale,Vec3 point,double speed):impl_(std::make_unique<Impl>(a,b,h,scale,point,speed)){}
SheetImpact::~SheetImpact()=default;
void SheetImpact::advance(unsigned steps){if(steps>20000)throw std::invalid_argument("sheet batch exceeds 20000 steps");for(unsigned i=0;i<steps;++i)impl_->step();}
const LatticeState &SheetImpact::state()const{return impl_->state;}
const RunStatus &SheetImpact::status()const{return impl_->target->status();}
const DoubleFixedSource &SheetImpact::source()const{return *impl_->source;}
const LatticeAsset &SheetImpact::asset()const{return impl_->asset;}
double SheetImpact::timestep()const{return impl_->dt;}
double SheetImpact::energyResidual()const{const auto &s=status();return measure(source(),state()).mechanicalEnergy()-impl_->initial.mechanicalEnergy()+impl_->contact_loss+s.removed_energy_j+s.plastic_work_j+s.plastic_return_numerical_loss_j+s.damping_dissipated_j-impl_->roundoff-impl_->drift-s.integration_numerical_energy_j-s.external_load.work_j-s.gravity_load.work_j;}
Vec3 SheetImpact::momentumResidual()const{const auto &s=status();return measure(source(),state()).linear_momentum_kg_m_s-impl_->initial.linear_momentum_kg_m_s-s.fixed_boundary.impulse_n_s-s.bond_kick_roundoff_impulse_n_s-impl_->contact_p-impl_->drift_p-s.external_load.impulse_n_s-s.gravity_load.impulse_n_s;}
Vec3 SheetImpact::angularResidual()const{const auto &s=status();return measure(source(),state()).angular_momentum_kg_m2_s-impl_->initial.angular_momentum_kg_m2_s-s.fixed_boundary.angular_impulse_kg_m2_s-s.bond_kick_roundoff_angular_kg_m2_s-impl_->contact_l-impl_->couple-impl_->drift_l-s.external_load.angular_impulse_kg_m2_s-s.gravity_load.angular_impulse_kg_m2_s;}
double SheetImpact::contactLoss()const{return impl_->contact_loss;}
double SheetImpact::initialEnergy()const{return impl_->initial.mechanicalEnergy();}
double SheetImpact::numericalEnergy()const{return status().integration_numerical_energy_j+impl_->drift+impl_->roundoff;}
}
