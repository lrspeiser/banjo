#include "fastlattice/NativeFixedContact.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
using namespace banjo;using namespace banjo::fastlattice;
void require(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
void near(double x,double y,double bound,const char *why){require(std::isfinite(x)&&std::abs(x-y)<=bound,why);}
template<class F> void rejects(F action,const char *why){bool refused=false;try{action();}catch(const std::exception&){refused=true;}require(refused,why);}
std::vector<ActiveNodeState> cube(double mass=2,Vec3 origin={}) {
    std::vector<ActiveNodeState> out;
    for(double x:{-.02,.02})for(double y:{-.02,.02})for(double z:{-.02,.02}) {
        const Vec3 p=origin+Vec3{x,y,z};
        out.push_back({p,p,Vec3{1,-2,.3}+cross(Vec3{.2,.5,-.7},p-origin),mass,{}});
    }
    return out;
}
void analyticalSurfaceOracles() {
    const Vec3 p{-.04,.01,.015},j{.4,.3,-.2};const auto nodes=cube();
    const auto stencil=makeMaterialContactStencil(nodes,p);
    for(std::size_t i=0;i<nodes.size();++i)
        near(stencil.weights[i],.125*(1+dot(nodes[i].position_world_m,p)/.0004),1e-15,"cube affine weight oracle");
    near(stencil.point.mass_kg,16/(1+dot(p,p)/.0004),1e-14,"cube effective mass oracle");
    near(length(stencil.point.velocity_m_s-(Vec3{1,-2,.3}+cross(Vec3{.2,.5,-.7},p))),0,1e-15,"affine spin velocity reproduction");
    const auto velocities=materialContactVelocities(nodes,stencil,j);
    Vec3 impulse{},moment{};double work=0;
    for(std::size_t i=0;i<nodes.size();++i) {
        const Vec3 dp=nodes[i].mass_kg*(velocities[i]-nodes[i].velocity_m_s);
        impulse+=dp;moment+=cross(nodes[i].position_world_m,dp);
        work+=.5*nodes[i].mass_kg*dot(velocities[i]-nodes[i].velocity_m_s,velocities[i]+nodes[i].velocity_m_s);
    }
    near(length(impulse-j),0,2e-15,"surface impulse reproduction");
    near(length(moment-cross(p,j)),0,2e-16,"surface moment reproduction");
    near(work,dot(stencil.point.velocity_m_s,j)+.5*dot(j,j)/stencil.point.mass_kg,3e-15,"surface virtual work identity");
    const Quat q{std::cos(.35),0,0,std::sin(.35)};
    auto rotated=nodes;
    for(auto &n:rotated){n.position_world_m=q.rotate(n.position_world_m);n.previous_position_world_m=n.position_world_m;n.velocity_m_s=q.rotate(n.velocity_m_s)+Vec3{3,-1,2};}
    const auto rs=makeMaterialContactStencil(rotated,q.rotate(p));
    const auto rv=materialContactVelocities(rotated,rs,q.rotate(j));
    for(std::size_t i=0;i<nodes.size();++i) {
        near(rs.weights[i],stencil.weights[i],1e-15,"rotation changed surface weights");
        near(length(rv[i]-(q.rotate(velocities[i])+Vec3{3,-1,2})),0,2e-15,"surface covariance or Galilean boost");
    }
    auto distant=cube(2,{1e8,-1e8,1e8});const Vec3 actual=distant[0].position_world_m+Vec3{0,.01,.015};
    const auto ds=makeMaterialContactStencil(distant,actual);
    Vec3 local{};for(std::size_t i=0;i<distant.size();++i)local+=ds.weights[i]*(distant[i].position_world_m-distant[0].position_world_m);
    near(length(local-(actual-distant[0].position_world_m)),0,1e-15,"distant-origin local moment reproduction");
    auto unequal=nodes;for(std::size_t i=0;i<unequal.size();++i)unequal[i].mass_kg*=1+static_cast<double>(i);
    const auto us=makeMaterialContactStencil(unequal,p);Vec3 um{};double sum=0;
    for(std::size_t i=0;i<unequal.size();++i){sum+=us.weights[i];um+=us.weights[i]*unequal[i].position_world_m;}
    near(sum,1,1e-14,"unequal mass force reproduction");near(length(um-p),0,1e-15,"unequal mass moment reproduction");
    auto bad=nodes;for(auto &n:bad)n.position_world_m.z=0;
    rejects([&]{(void)makeMaterialContactStencil(bad,p);},"planar support admitted");
    bad=nodes;bad[0].mass_kg=0;rejects([&]{(void)makeMaterialContactStencil(bad,p);},"zero mass admitted");
    bad=nodes;bad[0].spin_angular_velocity_rad_s.x=1;rejects([&]{(void)makeMaterialContactStencil(bad,p);},"cell spin silently reduced");
    bad=nodes;bad[0].previous_position_world_m.x=std::numeric_limits<double>::infinity();
    rejects([&]{(void)makeMaterialContactStencil(bad,p);},"nonfinite history admitted");
    rejects([&]{(void)makeMaterialContactStencil(nodes,{1,0,0});},"unbounded surface extrapolation admitted");
    rejects([&]{(void)makeMaterialContactStencil(std::span(nodes).first(3),p);},"three-node support admitted");
    auto changed=stencil;changed.weights[0]+=.01;
    rejects([&]{(void)materialContactVelocities(nodes,changed,j);},"edited weights admitted");
    bad=nodes;bad[0].velocity_m_s.x+=.1;
    rejects([&]{(void)materialContactVelocities(bad,stencil,j);},"stale stencil velocity admitted");
    const auto tiny=cube(.001);const auto ts=makeMaterialContactStencil(tiny,p);
    rejects([&]{(void)materialContactVelocities(tiny,ts,{1e308,1e308,1e308});},"overflowing impulse admitted");
}
struct Target {
    MaterialDefinition material;LatticeAsset asset;ActiveMatter matter;LatticeSchedule schedule;LatticeState state;StepSettings<double> settings{};
    Target(MaterialPreset preset,double dt=1e-7):material(makeReferenceMaterial(preset,17)) {
        const auto law=withPlasticFlow(withStrengthDerivedFailure(compileElasticLatticeReference(material,.04,1),material),material);
        asset=generateBoxTileLattice({{.08,.08,.08},.04,1},law);matter.asset=&asset;matter.material=law;
        for(const auto &n:asset.nodes) {
            const Vec3 p=Vec3{.08,0,0}+n.local_position_m;
            matter.nodes.push_back({p,p,{},n.represented_volume_m3*material.density_kg_m3,{}});
            matter.reference_positions_world_m.push_back(p);
        }
        matter.bonds.resize(asset.bonds.size());schedule=buildLatticeSchedule(asset);
        state=buildLatticeState(matter,schedule,{.08,0,0});
        settings.dt=dt;settings.audit_energy=1;settings.bond_integrator=kBondVelocityVerlet;
        settings.plastic_yield_stretch=law.yield_stretch;settings.plastic_hardening=law.plastic_hardening_ratio;
    }
    std::unique_ptr<LatticeBackend> backend(Precision precision=Precision::Double)const {
        auto out=makeCpuLatticeBackend(schedule,precision);out->upload(state,settings,{});return out;
    }
    LatticeState download(LatticeBackend &b)const {auto out=state;SphereState<double> s;b.download(out,s);return out;}
    std::vector<std::uint32_t> support()const {std::vector<std::uint32_t> ids;for(unsigned i=0;i<state.node_count;++i)ids.push_back(i);return ids;}
};
struct Tool {
    JoltWorld world;
    explicit Tool(double width=.12) {
        world.setGravity({});const auto iron=makeReferenceMaterial(MaterialPreset::Iron,17),oak=makeReferenceMaterial(MaterialPreset::Oak,17);
        world.addBox({1,{.08,width,.08},iron,{{},{},{6,.2,.1},{}},false});
        world.addBox({10,{.24,.04,.04},oak,{{-.16,0,0},{},{6,.2,.1},{}},false});
        world.addBox({2,{.01,.01,.01},oak,{{5,5,5},{},{},{}},true});
        (void)world.addFixing({10,1,{-.04,0,0},{1,0,0},0,0,0});
        for(auto pair:{std::pair{1U,10U},std::pair{2U,1U},std::pair{2U,10U}})world.setPairContactOwner(pair.first,pair.second,PairContactOwner::External);
        world.setDamping(1,0,0);world.setDamping(10,0,0);
    }
};
MechanicalTotals totals(const LatticeState &s,JoltWorld &w) {
    auto out=w.mechanicalTotals();out.elastic_energy_j+=latticeStateElasticEnergy(s);out.kinetic_energy_j+=latticeStateKineticEnergy(s);
    for(unsigned i=0;i<s.node_count;++i) {
        const Vec3 p=s.origin+Vec3{s.x0[3*i]+s.u[3*i],s.x0[3*i+1]+s.u[3*i+1],s.x0[3*i+2]+s.u[3*i+2]};
        const Vec3 mv=s.mass[i]*Vec3{s.v[3*i],s.v[3*i+1],s.v[3*i+2]};
        out.mass_kg+=s.mass[i];out.linear_momentum_kg_m_s+=mv;out.angular_momentum_kg_m2_s+=cross(p,mv);
    }
    return out;
}
void bulkAtomicity() {
    Target target(MaterialPreset::Oak);auto b=target.backend();const auto original=target.download(*b);
    std::vector<ExternalPointVelocity> updates;
    for(unsigned i=0;i<target.state.node_count;++i)updates.push_back({i,b->externalContactPoint(i),{.2,.3,-.1}});
    const auto unchanged=[&]{const auto now=target.download(*b);require(now.v==original.v&&now.u==original.u&&now.u_prev==original.u_prev&&now.alive==original.alive&&b->status().external_point_transfer.transfers==0,"refused bulk transfer mutated target");};
    auto bad=updates;bad.back().node=bad.front().node;rejects([&]{(void)b->applyExternalPointVelocities(bad);},"duplicate bulk node admitted");unchanged();
    bad=updates;bad.back().expected.velocity_m_s.x=1;rejects([&]{(void)b->applyExternalPointVelocities(bad);},"stale last bulk node admitted");unchanged();
    bad=updates;bad.back().node=999;rejects([&]{(void)b->applyExternalPointVelocities(bad);},"invalid last bulk node admitted");unchanged();
    bad=updates;bad.back().velocity_m_s.x=1e300;rejects([&]{(void)b->applyExternalPointVelocities(bad);},"last bulk node ledger overflow admitted");unchanged();
    rejects([&]{(void)b->applyExternalPointVelocities({});},"empty bulk transfer admitted");unchanged();
    bad.assign(65,updates.front());rejects([&]{(void)b->applyExternalPointVelocities(bad);},"oversized bulk transfer admitted");unchanged();
    const auto checked=b->validateExternalPointVelocities(updates);unchanged();
    const auto r=b->applyExternalPointVelocities(updates);const auto after=target.download(*b);
    require(r.transfers==1&&b->status().external_point_transfer.transfers==1,"bulk contact counted constituent updates as extra contacts");
    near(r.work_j,checked.work_j,0,"bulk preflight parity");near(latticeStateKineticEnergy(after)-latticeStateKineticEnergy(original),r.work_j,1e-15,"bulk work oracle");
    require(after.u==original.u&&after.u_prev==original.u_prev&&after.alive==original.alive&&after.damage==original.damage&&after.plastic_strain==original.plastic_strain&&b->status().total_steps==0,"bulk transfer reset histories/time");
    auto unsupported=makeCpuLatticeBackend(target.schedule,Precision::Float);
    auto float_settings=target.settings;float_settings.bond_integrator=kBondXpbd;
    unsupported->upload(target.state,float_settings,{});
    rejects([&]{(void)unsupported->applyExternalPointVelocities(updates);},"float bulk admitted");
    auto parallel=makeParallelCpuLatticeBackend(target.schedule,Precision::Double,2,1);parallel->upload(target.state,float_settings,{});
    rejects([&]{(void)parallel->applyExternalPointVelocities(updates);},"parallel bulk admitted");
    Tool tool;const auto source=tool.world.snapshot(1);auto ids=target.support();ids.back()=ids.front();
    rejects([&]{(void)applyNativeFixedSurfaceTransfer(tool.world,*b,ids,2,1,{.04,.01,.01},{1,0,0},0,{}, {1e-5,1e-5,1e-5});},"duplicate native support admitted");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-source.linear_velocity_m_s),0,0,"bad support changed native source");
    auto clamped=target.state;clamped.inv_mass.back()=0;auto cb=target.backend();cb->upload(clamped,target.settings,{});ids=target.support();
    rejects([&]{(void)applyNativeFixedSurfaceTransfer(tool.world,*cb,ids,2,1,{.04,.01,.01},{1,0,0},0,{}, {1e-5,1e-5,1e-5});},"clamped support silently given mobility");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-source.linear_velocity_m_s),0,0,"clamped support changed native source");
    auto fresh=target.backend();const auto pristine=target.download(*fresh);
    rejects([&]{(void)applyNativeFixedSurfaceTransfer(tool.world,*fresh,ids,2,1,{.04,.01,.01},{1,0,0},0,{}, {});},"zero native roundoff budget unexpectedly admitted");
    require(target.download(*fresh).v==pristine.v&&fresh->status().external_point_transfer.transfers==0,"refused native candidate changed target");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-source.linear_velocity_m_s),0,0,"refused native candidate changed head");
}
void matchedNativeSurfaceTrajectories() {
    // A short pre-fracture experiment: all eight actual cells stay connected.
    // Never spread a stencil over separated debris. Long-time contact/topology
    // selection is a later gate. No damping, gravity, clamps or artificial spin.
    for(double width:{.04,.12})for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        double coarse_error=0;
        for(double dt:{1e-7,5e-8}) {
            Target target(preset,dt);Tool tool(width);auto b=target.backend();const auto ids=target.support();
            const auto initial=totals(target.state,tool.world);const auto original_head=tool.world.snapshot(1),original_handle=tool.world.snapshot(10);
            double loss=0,reconcile=0,transfer_e=0,native_e=0,max_target_work=0,max_target_p=0,max_target_l=0;
            Vec3 transfer_p{},transfer_l{},geometry_couple{},native_p{},native_l{};unsigned contacts=0;
            const auto step=[&](bool record) {
                const auto state=target.download(*b);
                require(std::all_of(state.alive.begin(),state.alive.end(),[](auto alive){return alive!=0;}),"surface fixture lost its declared connected support");
                for(unsigned i=0;i<state.node_count;++i) {
                    const Vec3 at=state.origin+Vec3{state.x0[3*i]+state.u[3*i],state.x0[3*i+1]+state.u[3*i+1],state.x0[3*i+2]+state.u[3*i+2]};
                    require(tool.world.materialShapeContacts(10,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts.empty(),"surface fixture omitted handle contact");
                    for(const auto &hit:tool.world.materialShapeContacts(1,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts) {
                        const auto law=combineContactMaterials(compileContactMaterial(target.material),hit.body_contact);
                        // Common source-surface reaction point, with current native gap/normal.
                        const auto r=applyNativeFixedSurfaceTransfer(tool.world,*b,ids,2,1,hit.point_on_body_world_m,
                            hit.normal_world,hit.gap_m,{law.static_friction,law.dynamic_friction,law.restitution},{1e-5,1e-5,1e-5});
                        if(!record||!r.source.contact.modal_contact.applied)continue;
                        ++contacts;loss+=r.source.contact.modal_contact.dissipated_energy_j;reconcile+=r.source.contact.reconciliation_loss_j;
                        transfer_e+=r.source.numerical_energy_change_j;transfer_p+=r.source.momentum_error_kg_m_s;
                        transfer_l+=r.source.angular_momentum_error_kg_m2_s;geometry_couple+=r.source.contact.geometry_couple_kg_m2_s;
                        max_target_work=std::max(max_target_work,std::abs(r.target_work_error_j));
                        max_target_p=std::max(max_target_p,length(r.target_impulse_error_n_s));
                        max_target_l=std::max(max_target_l,length(r.target_angular_error_kg_m2_s));
                    }
                }
                const auto before=tool.world.mechanicalTotals();tool.world.step(dt);const auto after=tool.world.mechanicalTotals();b->run({.max_steps=1});
                if(record){native_e+=after.kinetic_energy_j-before.kinetic_energy_j;native_p+=after.linear_momentum_kg_m_s-before.linear_momentum_kg_m_s;native_l+=after.angular_momentum_kg_m2_s-before.angular_momentum_kg_m2_s;}
            };
            require(!runNativeFixedTargetTrial(tool.world,*b,[&]{for(unsigned k=0;k<4;++k)step(false);return false;}),"surface rollback accepted");
            const auto restored=target.download(*b);
            require(restored.v==target.state.v&&restored.u==target.state.u&&restored.damage==target.state.damage&&restored.alive==target.state.alive&&restored.plastic_strain==target.state.plastic_strain&&b->status().total_steps==0&&b->status().external_point_transfer.transfers==0,"surface rollback leaked target history/time/account");
            near(length(tool.world.snapshot(1).linear_velocity_m_s-original_head.linear_velocity_m_s),0,0,"surface rollback head");
            near(length(tool.world.snapshot(10).linear_velocity_m_s-original_handle.linear_velocity_m_s),0,0,"surface rollback handle");
            const unsigned count=dt==1e-7?32:64;const auto start=std::chrono::steady_clock::now();
            for(unsigned k=0;k<count;++k)step(true);
            const auto final_state=target.download(*b);const auto final=totals(final_state,tool.world);const auto &s=b->status();
            require(s.broken_bonds==0,"short contact comparison left pre-fracture validity");
            require(contacts>0&&s.external_point_transfer.transfers==contacts,"surface reference did not deliver actual contact");
            const Vec3 p=final.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-transfer_p-s.bond_kick_roundoff_impulse_n_s;
            const Vec3 l=final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-transfer_l-geometry_couple-s.bond_kick_roundoff_angular_kg_m2_s;
            const double e=final.mechanicalEnergy()-initial.mechanicalEnergy()+loss+reconcile+s.removed_energy_j+s.plastic_work_j+s.plastic_return_numerical_loss_j-transfer_e;
            near(length(p-native_p),0,1e-9,"surface trajectory linear attribution");near(length(l-native_l),0,1e-9,"surface trajectory angular attribution");
            near(e-native_e,s.integration_numerical_energy_j,1e-10,"surface trajectory energy attribution");near(final.mass_kg,initial.mass_kg,1e-12,"surface introduced virtual mass into physical totals");
            require(std::abs(s.integration_numerical_energy_j)<.001*initial.mechanicalEnergy(),"surface integration exceeded retained 0.1% bound");
            if(dt==1e-7)coarse_error=std::abs(s.integration_numerical_energy_j);
            else require(std::abs(s.integration_numerical_energy_j)<.27*coarse_error,"surface timestep refinement failed");
            std::cout<<"SURFACE_CONTACT_EVIDENCE {\"material\":\""<<materialPresetName(preset)<<"\",\"width_m\":"<<width<<",\"cell_m\":0.04,\"dt_s\":"<<dt
                <<",\"steps\":"<<count<<",\"support_nodes\":"<<ids.size()<<",\"contacts\":"<<contacts<<",\"target_mass_kg\":"<<target.material.density_kg_m3*.000512
                <<",\"total_mass_kg\":"<<final.mass_kg<<",\"broken_bonds\":"<<s.broken_bonds<<",\"p_residual_n_s\":"<<length(p)<<",\"l_residual_kg_m2_s\":"<<length(l)
                <<",\"unallocated_energy_j\":"<<e<<",\"integration_error_j\":"<<s.integration_numerical_energy_j<<",\"native_step_energy_j\":"<<native_e
                <<",\"target_work_error_j\":"<<max_target_work<<",\"target_impulse_error_n_s\":"<<max_target_p<<",\"target_angular_error_kg_m2_s\":"<<max_target_l
                <<",\"wall_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<"}\n";
        }
    }
}
}
int main(){try{std::cout.precision(12);analyticalSurfaceOracles();bulkAtomicity();matchedNativeSurfaceTrajectories();std::cout<<"[PASS] bounded material surface transfer\n";return 0;}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
