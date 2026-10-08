#include "fastlattice/NativeFixedContact.hpp"
#include "fastlattice/ConstituentPartition.hpp"
#include "material/MaterialCatalog.hpp"
#include "material/MaterialCompiler.hpp"
#include "matter/BoxLattice.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <fstream>
#include <filesystem>
#include <nlohmann/json.hpp>

namespace {
using namespace banjo;using namespace banjo::fastlattice;
void require(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
void near(double x,double y,double bound,const char *why){
    if(!std::isfinite(x)||std::abs(x-y)>bound)
        std::cerr<<why<<": measured="<<x<<" expected="<<y<<" difference="<<x-y<<" bound="<<bound<<'\n';
    require(std::isfinite(x)&&std::abs(x-y)<=bound,why);
}
template<class F> void rejects(F action,const char *why){bool refused=false;try{action();}catch(const std::exception&){refused=true;}require(refused,why);}
std::vector<ActiveNodeState> cube(double mass=2,Vec3 origin={}) {
    std::vector<ActiveNodeState> out;
    for(double x:{-.02,.02})for(double y:{-.02,.02})for(double z:{-.02,.02}) {
        const Vec3 p=origin+Vec3{x,y,z};
        out.push_back({p,p,Vec3{1,-2,.3}+cross(Vec3{.2,.5,-.7},p-origin),mass,{}});
    }
    return out;
}
void liveGraphSelectionOracles() {
    const auto nodes=cube();std::vector<std::uint32_t> a,b;
    for(unsigned i=0;i<nodes.size();++i)for(unsigned j=i+1;j<nodes.size();++j)
        if(std::abs(length(nodes[i].position_world_m-nodes[j].position_world_m)-.04)<1e-15){a.push_back(i);b.push_back(j);}
    MaterialContactTopology graph(8,a,b);std::vector<std::uint8_t> alive(a.size(),1);
    const auto position=[&](unsigned i){return nodes[i].position_world_m;};
    const auto mobile=[](unsigned){return true;};
    const auto region=graph.select(0,alive,{.08,3,64,4096},position,mobile);
    require(region.nodes==std::vector<std::uint32_t>{0,1,2,4,3,5,6,7}&&region.maximum_hop==3,"deterministic breadth-first support oracle");
    require(graph.select(0,alive,{.045,3,64,4096},position,mobile).nodes==std::vector<std::uint32_t>{0,1,2,4},"physical support radius oracle");
    require(graph.select(0,alive,{.08,1,64,4096},position,mobile).nodes==std::vector<std::uint32_t>{0,1,2,4},"bounded graph depth oracle");
    for(unsigned k=0;k<a.size();++k)if(nodes[a[k]].position_world_m.x!=nodes[b[k]].position_world_m.x)alive[k]=0;
    require(graph.select(0,alive,{.08,3,64,4096},position,mobile).nodes==std::vector<std::uint32_t>{0,1,2,3},"cut plane still spread contact into other piece");
    auto nearby=nodes;
    for(auto &n:nearby)if(n.position_world_m.x>0)n.position_world_m.x=-.019; // Near/overlap does not heal topology.
    require(graph.select(0,alive,{.08,3,64,4096},[&](unsigned i){return nearby[i].position_world_m;},mobile).nodes.size()==4,"touching disconnected pieces healed graph");
    std::fill(alive.begin(),alive.end(),std::uint8_t{0});
    require(graph.select(0,alive,{.08,3,64,4096},position,mobile).nodes==std::vector<std::uint32_t>{0},"isolated material borrowed surrounding support");
    std::fill(alive.begin(),alive.end(),std::uint8_t{1});
    const auto clamped=graph.select(0,alive,{.08,3,64,4096},position,[](unsigned i){return i!=1&&i!=2&&i!=4;});
    require(clamped.nodes==std::vector<std::uint32_t>{0}&&clamped.clamped_edge_visits==3,"region traversed clamps to remote cells");
    rejects([&]{(void)graph.select(0,alive,{.08,3,3,4096},position,mobile);},"node overflow silently truncated support");
    rejects([&]{(void)graph.select(0,alive,{.08,3,64,1},position,mobile);},"edge overflow silently truncated support");
    rejects([&]{(void)graph.select(8,alive,{.08,3,64,4096},position,mobile);},"invalid region seed admitted");
    rejects([&]{(void)graph.select(0,alive,{.08,3,64,4096},position,[](unsigned){return false;});},"clamped seed admitted");
    alive[0]=2;rejects([&]{(void)graph.select(0,alive,{.08,3,64,4096},position,mobile);},"invalid live bond flag admitted");
    rejects([&]{(void)graph.select(0,{}, {.08,3,64,4096},position,mobile);},"stale topology dimensions admitted");
    rejects([&]{(void)graph.select(0,alive,{.08,0,64,4096},position,mobile);},"unbounded/zero hop setting admitted");
    rejects([&]{(void)graph.select(0,alive,{.08,3,64,4096},[](unsigned){return Vec3{std::numeric_limits<double>::infinity(),0,0};},mobile);},"nonfinite current geometry admitted");
    const std::uint32_t invalid[]{8};rejects([&]{(void)MaterialContactTopology(8,invalid,invalid);},"invalid immutable endpoints admitted");
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
    Target(MaterialPreset preset,double dt=1e-7,double extent=.08,Vec3 origin={.08,0,0}):material(makeReferenceMaterial(preset,17)) {
        const auto law=withPlasticFlow(withStrengthDerivedFailure(compileElasticLatticeReference(material,.04,1),material),material);
        asset=generateBoxTileLattice({{extent,extent,extent},.04,1},law);matter.asset=&asset;matter.material=law;
        for(const auto &n:asset.nodes) {
            const Vec3 p=origin+n.local_position_m;
            matter.nodes.push_back({p,p,{},n.represented_volume_m3*material.density_kg_m3,{}});
            matter.reference_positions_world_m.push_back(p);
        }
        matter.bonds.resize(asset.bonds.size());schedule=buildLatticeSchedule(asset);
        state=buildLatticeState(matter,schedule,origin);
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
void capturedManifoldRegression() {
    // Actual failing pre-contact inputs, not stored fracture outcomes. The old
    // zero-start search refused this nine-contact glass state at 1.45336e-8 m/s.
    std::ifstream input(std::filesystem::path(__FILE__).parent_path()/"data/coupled-glass-contact-state.txt");
    require(input.good(),"missing captured coupled contact fixture");
    std::size_t node_count{},contact_count{},body_count{},link_count{};std::uint32_t striker{};double dt{};
    input>>node_count>>contact_count>>body_count>>link_count>>striker>>dt;
    require(node_count==18&&contact_count==9&&body_count==2&&link_count==1&&striker==0,
        "captured contact fixture header changed");
    const auto read_vec=[&](Vec3 &v){input>>v.x>>v.y>>v.z;};
    std::vector<ActiveNodeState> nodes(node_count);
    for(auto &n:nodes) {
        read_vec(n.position_world_m);read_vec(n.previous_position_world_m);read_vec(n.velocity_m_s);
        read_vec(n.spin_angular_velocity_rad_s);input>>n.mass_kg;
    }
    std::vector<FixedSurfaceContact> contacts(contact_count);
    for(auto &c:contacts) {
        std::size_t count{};input>>count;require(count<=node_count,"captured support exceeds actual nodes");
        c.nodes.resize(count);for(auto &id:c.nodes)input>>id;
        read_vec(c.surface_world_m);read_vec(c.normal_world);input>>c.gap_m>>c.settings.static_friction>>
            c.settings.dynamic_friction>>c.settings.restitution>>c.settings.restitution_speed_threshold_m_s>>c.settings.contact_margin_m;
    }
    std::vector<RigidMechanicalState> bodies(body_count);
    for(auto &b:bodies) {
        read_vec(b.motion.center_of_mass_world_m);
        input>>b.motion.orientation_world.w>>b.motion.orientation_world.x>>b.motion.orientation_world.y>>b.motion.orientation_world.z;
        read_vec(b.motion.linear_velocity_m_s);read_vec(b.motion.angular_velocity_rad_s);input>>b.mass_kg;
        for(auto &row:b.inertia_world_kg_m2.m)for(auto &x:row)input>>x;
    }
    std::vector<FixedVelocityLink> links(link_count);
    for(auto &link:links){input>>link.a>>link.b;read_vec(link.point_a_world_m);read_vec(link.point_b_world_m);}
    require(!input.fail(),"malformed captured manifold fixture");
    input>>std::ws;require(input.eof(),"unexpected captured manifold fixture tail");
    const auto result=evaluateFixedSurfaceManifold(nodes,contacts,bodies,links,striker,dt);
    require(result.active_contacts>0,"captured convergent contact discarded all impulses");
    near(length(result.momentum_residual_kg_m_s),0,1e-10,"captured manifold source momentum audit");
    near(length(result.angular_residual_kg_m2_s),0,1e-10,"captured manifold source angular audit");
    near(result.work_residual_j,0,1e-10,"captured manifold whole-system work audit");
    Vec3 momentum{},angular{};double energy_change=0;
    for(std::size_t a=0;a<nodes.size();++a) {
        const auto delta=result.node_velocities_m_s[a]-nodes[a].velocity_m_s;
        const auto impulse=nodes[a].mass_kg*delta;
        momentum+=impulse;angular+=cross(nodes[a].position_world_m,impulse);
        energy_change+=.5*nodes[a].mass_kg*dot(delta,result.node_velocities_m_s[a]+nodes[a].velocity_m_s);
    }
    for(std::size_t a=0;a<bodies.size();++a) {
        const auto &before=bodies[a],&after=result.bodies[a];
        const auto delta=after.motion.linear_velocity_m_s-before.motion.linear_velocity_m_s;
        const auto spin=after.motion.angular_velocity_rad_s-before.motion.angular_velocity_rad_s;
        const auto impulse=before.mass_kg*delta;
        momentum+=impulse;angular+=cross(before.motion.center_of_mass_world_m,impulse)+before.inertia_world_kg_m2*spin;
        energy_change+=.5*before.mass_kg*dot(delta,after.motion.linear_velocity_m_s+before.motion.linear_velocity_m_s)+
            .5*dot(spin,before.inertia_world_kg_m2*(after.motion.angular_velocity_rad_s+before.motion.angular_velocity_rad_s));
    }
    near(length(momentum),0,1e-10,"captured full material/source linear momentum");
    near(length(angular-result.geometry_couple_kg_m2_s),0,1e-10,"captured full material/source angular momentum");
    near(energy_change+result.reconciliation_loss_j+result.dissipated_energy_j,0,1e-10,
        "captured full material/source energy account");
    auto reversed=contacts;std::reverse(reversed.begin(),reversed.end());
    const auto reverse=evaluateFixedSurfaceManifold(nodes,reversed,bodies,links,striker,dt);
    for(std::size_t a=0;a<nodes.size();++a)
        near(length(result.node_velocities_m_s[a]-reverse.node_velocities_m_s[a]),0,0,"captured contact order changed response");
    std::cout<<"MANIFOLD_CAPTURE {\"contacts\":"<<contact_count<<",\"active\":"<<result.active_contacts
        <<",\"work_residual_j\":"<<result.work_residual_j<<",\"iterations\":"<<result.iterations<<"}\n";
}
void manifoldOracles() {
    capturedManifoldRegression();
    for(const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Target target(preset,1e-7,.08,{.08,0,0});Tool tool;
        auto backend=target.backend();std::vector<ActiveNodeState> nodes;
        for(const auto id:target.support())nodes.push_back(backend->externalContactPoint(id));
        const std::vector<FixedSurfaceContact> contacts{
            {target.support(),{.04,-.01,0},{1,0,0},0,{0,0,1}},
            {target.support(),{.04,.01,0},{1,0,0},0,{0,0,1}}};
        const auto first=makeMaterialContactStencil(nodes,contacts[0].surface_world_m);
        const auto prepared=tool.world.prepareExternalFixedPointContact(2,1,first.point,{1,0,0},0,1e-7,{0,0,1},{1e-5,1e-5,1e-5});
        const auto &metadata=prepared.receipt();std::vector<RigidMechanicalState> source;
        for(const auto id:metadata.body_ids)source.push_back(tool.world.mechanicalState(id));
        const auto index=static_cast<std::uint32_t>(std::find(metadata.body_ids.begin(),metadata.body_ids.end(),1)-metadata.body_ids.begin());
        const auto result=evaluateFixedSurfaceManifold(nodes,contacts,source,metadata.links,index,1e-7);
        double material_mass=0,source_mass=0;
        for(const auto &n:nodes)material_mass+=n.mass_kg;for(const auto &body:source)source_mass+=body.mass_kg;
        const double expected=12/(5/material_mass+1/source_mass);
        const Vec3 total=result.impulses_n_s[0]+result.impulses_n_s[1];
        near(length(total-Vec3{expected,0,0}),0,1e-9,"simultaneous symmetric elastic normal impulse oracle");
        near(result.dissipated_energy_j,0,1e-9,"elastic manifold invented contact loss");
        near(result.reconciliation_loss_j,0,1e-12,"compatible fixed source lost energy");
        near(result.work_residual_j,0,1e-10,"whole manifold kinetic work audit");
        auto reversed=contacts;std::reverse(reversed.begin(),reversed.end());
        const auto reverse=evaluateFixedSurfaceManifold(nodes,reversed,source,metadata.links,index,1e-7);
        for(std::size_t n=0;n<nodes.size();++n)
            near(length(result.node_velocities_m_s[n]-reverse.node_velocities_m_s[n]),0,0,"manifold depended on input contact order");
        Vec3 p{},l{};
        for(std::size_t n=0;n<nodes.size();++n) {
            const Vec3 j=nodes[n].mass_kg*(result.node_velocities_m_s[n]-nodes[n].velocity_m_s);
            p+=j;l+=cross(nodes[n].position_world_m,j);
        }
        for(std::size_t k=0;k<source.size();++k) {
            const auto &before=source[k],&after=result.bodies[k];
            const Vec3 j=before.mass_kg*(after.motion.linear_velocity_m_s-before.motion.linear_velocity_m_s);
            p+=j;l+=cross(before.motion.center_of_mass_world_m,j)+before.inertia_world_kg_m2*
                (after.motion.angular_velocity_rad_s-before.motion.angular_velocity_rad_s);
        }
        near(length(p),0,1e-10,"manifold full material/source momentum");
        near(length(l-result.geometry_couple_kg_m2_s),0,1e-10,"manifold full material/source angular momentum");
        for(const auto law:{PointRigidContactSettings{.4,.3,.5},PointRigidContactSettings{.001,.0005,.5}}) {
            FixedSurfaceContact contact{target.support(),{.04,.01,.015},{1,0,0},0,law};
            const auto stencil=makeMaterialContactStencil(nodes,contact.surface_world_m);
            const auto isolated=evaluatePointFixedAssemblyContact(stencil.point,source,metadata.links,index,{1,0,0},0,1e-7,law);
            const auto batch=evaluateFixedSurfaceManifold(nodes,{contact},source,metadata.links,index,1e-7);
            near(length(batch.impulses_n_s[0]-isolated.modal_contact.impulse_to_node_n_s),0,1e-9,"single-manifold sticking/slipping law changed");
            near(batch.dissipated_energy_j,isolated.modal_contact.dissipated_energy_j,1e-9,"single-manifold friction work changed");
        }
        auto invalid=contacts;invalid.back().nodes.push_back(999);
        rejects([&]{(void)evaluateFixedSurfaceManifold(nodes,invalid,source,metadata.links,index,1e-7);},"late manifold endpoint admitted");
        auto invalid_nodes=nodes;invalid_nodes.back().mass_kg=0;
        rejects([&]{(void)evaluateFixedSurfaceManifold(invalid_nodes,contacts,source,metadata.links,index,1e-7);},"invalid shared node admitted");
        std::vector<NativeSurfaceWitness> witnesses;
        for(const auto &c:contacts)witnesses.push_back({0,c.surface_world_m,c.normal_world,c.gap_m,c.settings});
        const auto initial=target.download(*backend);const auto old=tool.world.snapshot(1);
        require(!runNativeFixedTargetTrial(tool.world,*backend,[&]{
            const auto applied=applyNativeFixedLocalSurfaceManifold(tool.world,*backend,witnesses,{.1,3,64,4096},2,1,{1e-5,1e-5,1e-5});
            require(applied.source.contact.active_contacts==2&&applied.target.transfers==1,"manifold transfer ownership/count");
            return false;
        }),"false native manifold trial committed");
        const auto restored=target.download(*backend);
        require(restored.v==initial.v&&restored.u==initial.u&&restored.alive==initial.alive&&
            backend->status().external_point_transfer.transfers==0,"failed manifold trial leaked material state/account");
        near(length(tool.world.snapshot(1).linear_velocity_m_s-old.linear_velocity_m_s),0,0,"failed manifold trial kicked source");
        const auto plan=tool.world.prepareExternalFixedSurfaceManifold(2,1,nodes,contacts,1e-7,{1e-5,1e-5,1e-5});
        Tool another;
        rejects([&]{(void)another.world.commitExternalFixedSurfaceManifold(plan);},"another world committed a manifold plan");
        tool.world.step(1e-7);
        rejects([&]{(void)tool.world.commitExternalFixedSurfaceManifold(plan);},"elapsed native tick committed stale manifold");
        std::cout<<"MANIFOLD_ORACLE {\"material\":\""<<materialPresetName(preset)<<"\",\"target_mass_kg\":"<<material_mass
            <<",\"normal_impulse_n_s\":"<<total.x<<",\"work_residual_j\":"<<result.work_residual_j<<",\"iterations\":"<<result.iterations<<"}\n";
    }
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
void authoritativeTopologyAdmission() {
    Target target(MaterialPreset::Glass);Tool tool;const auto source=tool.world.snapshot(1);
    auto disconnected=target.state;
    // A prescribed damaged initial state, not a fracture result. This tests
    // ownership safety; the sustained cases below generate their own failures.
    for(unsigned k=0;k<disconnected.bond_count;++k)
        if(disconnected.x0[3*disconnected.bond_a[k]]!=disconnected.x0[3*disconnected.bond_b[k]])disconnected.alive[k]=0;
    auto backend=target.backend();backend->upload(disconnected,target.settings,{});
    const auto region=backend->externalContactRegion(0,{.08,3,64,4096});require(region.nodes.size()==4,"backend reused stale intact support");
    rejects([&]{(void)applyNativeFixedLocalSurfaceTransfer(tool.world,*backend,0,{.08,3,64,4096},2,1,{.04,.01,.01},{1,0,0},0,{}, {1e-5,1e-5,1e-5});},"planar damaged support silently accepted surface torque");
    require(target.download(*backend).v==disconnected.v&&backend->status().external_point_transfer.transfers==0,"unsupported damaged support changed target");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-source.linear_velocity_m_s),0,0,"unsupported damaged support changed source");
    auto changed=target.state;
    for(unsigned i=1;i<changed.node_count;++i)changed.u[3*i]+=1;
    backend->upload(changed,target.settings,{});
    require(backend->externalContactRegion(0,{.08,3,64,4096}).nodes.size()==1,"backend selected reference rather than current positions");
    backend->upload(target.state,target.settings,{});
    const auto before=backend->externalContactRegion(0,{.08,3,64,4096});
    require(before.nodes.size()==8,"restored upload failed contact topology refresh");
    require(!runNativeFixedTargetTrial(tool.world,*backend,[&]{
        const auto r=applyNativeFixedLocalSurfaceTransfer(tool.world,*backend,0,{.08,3,64,4096},2,1,{.04,.01,.01},{1,0,0},0,{}, {1e-5,1e-5,1e-5});
        require(r.region.nodes.size()==8&&r.source.contact.modal_contact.applied,"local transfer never exercised graph");
        tool.world.step(target.settings.dt);backend->run({.max_steps=1});return false;
    }),"local graph trial unexpectedly accepted");
    const auto after=backend->externalContactRegion(0,{.08,3,64,4096});
    require(before.nodes==after.nodes&&after.target_step==0&&backend->status().external_point_transfer.transfers==0,"rolled back contact reused changed graph clock");
    near(length(tool.world.snapshot(1).linear_velocity_m_s-source.linear_velocity_m_s),0,0,"local rollback failed source");
}
void variableContactStepOracles() {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Target target(preset);Tool tool;auto b=target.backend();
        const auto ids=target.support();
        const auto initial_totals=totals(target.state,tool.world);
        Vec3 contact_p{},contact_l{},contact_couple{},native_p{},native_l{};
        double contact_loss=0,contact_correction=0,native_energy=0;
        bool invoked=false;
        rejects([&]{b->advanceExternalContactStep(5e-8,[&]{invoked=true;});},"variable step outside reversible trial admitted");
        require(!invoked&&b->status().total_steps==0,"refused step invoked contact");
        const auto step=[&](double dt,bool record=false) {
            return b->advanceExternalContactStep(dt,[&] {
                near(b->externalContactTimestep(),dt,0,"contact used uploaded rather than scoped horizon");
                const auto result=applyNativeFixedSurfaceTransfer(tool.world,*b,ids,2,1,
                    {.04,.01,.01},{1,0,0},0,{}, {1e-5,1e-5,1e-5});
                near(result.horizon_s,dt,0,"native plan did not use actual step horizon");
                const auto native_before=tool.world.mechanicalTotals();
                tool.world.step(dt);
                if(record) {
                    const auto native_after=tool.world.mechanicalTotals();
                    contact_p+=result.source.momentum_error_kg_m_s;
                    contact_l+=result.source.angular_momentum_error_kg_m2_s;
                    contact_couple+=result.source.contact.geometry_couple_kg_m2_s;
                    contact_loss+=result.source.contact.modal_contact.dissipated_energy_j+result.source.contact.reconciliation_loss_j;
                    contact_correction+=result.source.numerical_energy_change_j;
                    native_p+=native_after.linear_momentum_kg_m_s-native_before.linear_momentum_kg_m_s;
                    native_l+=native_after.angular_momentum_kg_m2_s-native_before.angular_momentum_kg_m2_s;
                    native_energy+=native_after.mechanicalEnergy()-native_before.mechanicalEnergy();
                }
            });
        };
        require(runNativeFixedTargetTrial(tool.world,*b,[&]{step(1e-7,true);step(5e-8,true);return true;}),"variable contact trial refused");
        near(b->externalContactElapsedTime(),1.5e-7,3e-23,"variable accepted clock used step count times uploaded dt");
        near(b->externalContactTimestep(),1e-7,0,"accepted step leaked scoped configuration");
        require(b->status().total_steps==2&&b->status().external_point_transfer.transfers>0,"variable step did not perform real contact/integration");
        const auto final_totals=totals(target.download(*b),tool.world);const auto &account=b->status();
        const double p_residual=length(final_totals.linear_momentum_kg_m_s-initial_totals.linear_momentum_kg_m_s-
            contact_p-native_p-account.fixed_boundary.impulse_n_s-account.bond_kick_roundoff_impulse_n_s);
        const double l_residual=length(final_totals.angular_momentum_kg_m2_s-initial_totals.angular_momentum_kg_m2_s-
            contact_l-contact_couple-native_l-account.fixed_boundary.angular_impulse_kg_m2_s-account.bond_kick_roundoff_angular_kg_m2_s);
        const double e_residual=final_totals.mechanicalEnergy()-initial_totals.mechanicalEnergy()+contact_loss+
            account.removed_energy_j+account.plastic_work_j+account.plastic_return_numerical_loss_j-
            contact_correction-native_energy-account.integration_numerical_energy_j;
        near(p_residual,0,1e-9,"variable contact full linear attribution");
        near(l_residual,0,1e-9,"variable contact full angular attribution");
        near(e_residual,0,1e-10,"variable contact full energy attribution");
        near(final_totals.mass_kg,initial_totals.mass_kg,1e-12,"variable contact changed complete assembly mass");
        const auto initial=target.download(*b);const auto old=b->status();const auto head=tool.world.snapshot(1),handle=tool.world.snapshot(10);
        const auto unchanged=[&] {
            const auto now=target.download(*b);
            require(now.u==initial.u&&now.u_prev==initial.u_prev&&now.v==initial.v&&now.mass==initial.mass&&
                now.alive==initial.alive&&now.damage==initial.damage&&now.prev_tensile==initial.prev_tensile&&
                now.prev_compressive==initial.prev_compressive&&now.prev_shear==initial.prev_shear&&
                now.plastic_extension==initial.plastic_extension&&now.plastic_strain==initial.plastic_strain,
                "variable trial leaked node/bond history");
            require(b->status().total_steps==old.total_steps&&b->status().launches==old.launches&&
                b->status().external_point_transfer.transfers==old.external_point_transfer.transfers,
                "variable trial leaked status/transfer count");
            near(b->status().integration_numerical_energy_j,old.integration_numerical_energy_j,0,"variable trial leaked numerical ledger");
            near(b->status().external_point_transfer.work_j,old.external_point_transfer.work_j,0,"variable trial leaked transfer work");
            near(length(tool.world.snapshot(1).linear_velocity_m_s-head.linear_velocity_m_s),0,0,"variable trial leaked native velocity");
            near(length(tool.world.snapshot(1).center_of_mass_world_m-head.center_of_mass_world_m),0,0,"variable trial leaked native position");
            for(const auto &[id,snapshot]:{std::pair{1U,head},std::pair{10U,handle}}) {
                const auto body=tool.world.snapshot(id);
                near(length(body.center_of_mass_world_m-snapshot.center_of_mass_world_m),0,0,"variable trial leaked joined native position");
                near(length(body.linear_velocity_m_s-snapshot.linear_velocity_m_s),0,0,"variable trial leaked joined native velocity");
                near(length(body.angular_velocity_rad_s-snapshot.angular_velocity_rad_s),0,0,"variable trial leaked joined native spin");
                require(body.orientation_world.w==snapshot.orientation_world.w&&body.orientation_world.x==snapshot.orientation_world.x&&
                    body.orientation_world.y==snapshot.orientation_world.y&&body.orientation_world.z==snapshot.orientation_world.z,
                    "variable trial leaked joined native rotation");
            }
            near(b->externalContactElapsedTime(),1.5e-7,3e-23,"variable trial leaked accepted time");
            near(b->externalContactTimestep(),1e-7,0,"variable trial leaked step configuration");
        };
        require(!runNativeFixedTargetTrial(tool.world,*b,[&]{step(2.5e-8);step(1.25e-8);return false;}),"rejected variable trial accepted");
        unchanged();
        rejects([&]{(void)runNativeFixedTargetTrial(tool.world,*b,[&] {
            b->advanceExternalContactStep(2.5e-8,[&] {
                tool.world.step(2.5e-8);throw std::runtime_error("intentional callback failure");
            });return true;
        });},"throwing variable trial accepted");unchanged();
        require(runNativeFixedTargetTrial(tool.world,*b,[&] {
            for(double bad:{0.0,-1.0,2e-7,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()})
                rejects([&]{b->advanceExternalContactStep(bad,[]{});},"invalid variable horizon admitted");
            rejects([&]{b->advanceExternalContactStep(5e-8,{});},"empty variable callback admitted");
            b->advanceExternalContactStep(5e-8,[&] {
                rejects([&]{b->run({.max_steps=1});},"callback advanced target twice");
                rejects([&]{b->advanceExternalContactStep(2.5e-8,[]{});},"recursive variable step admitted");
                rejects([&]{b->setExternalForces({},0);},"callback replaced finite load schedule");
                rejects([&]{b->setExternalWrenches({},0);},"callback replaced finite wrench schedule");
                tool.world.step(5e-8);
            });return false;
        })==false,"callback guard trial accepted");unchanged();

        // Finite queued forces have a declared substep span. A smaller dt must
        // not silently shorten it. Uniform translation has no bond strain.
        auto loads=target.backend();std::vector<Vec3> forces(target.state.node_count);
        for(unsigned i=0;i<forces.size();++i)forces[i]={target.state.mass[i]*2,0,0};
        loads->setExternalForces(forces,2);
        require(runNativeFixedTargetTrial(tool.world,*loads,[&] {
            rejects([&]{loads->advanceExternalContactStep(5e-8,[]{});},"variable step shortened queued force duration");
            for(unsigned i=0;i<3;++i)loads->advanceExternalContactStep(1e-7,[&]{tool.world.step(1e-7);});
            loads->advanceExternalContactStep(5e-8,[&]{tool.world.step(5e-8);});return true;
        }),"finite force clock trial refused");
        const auto loaded=target.download(*loads);double mass=0;for(double m:loaded.mass)mass+=m;
        near(loads->externalContactElapsedTime(),3.5e-7,1e-22,"finite force clock incorrect");
        require(loads->status().external_load.steps==2,"finite load span changed");
        near(loads->status().external_load.elapsed_s,2e-7,1e-22,"finite force duration changed");
        near(loads->status().external_load.impulse_n_s.x,4e-7*mass,2e-20,"finite force impulse changed");
        // Internal spring roundoff redistributes tiny nodal velocities when
        // reconstructed positions are rounded. Test assembly momentum, which
        // internal action/reaction must preserve, rather than exact node copies.
        Vec3 load_momentum{};
        for(unsigned i=0;i<loaded.node_count;++i)load_momentum+=loaded.mass[i]*Vec3{loaded.v[3*i],loaded.v[3*i+1],loaded.v[3*i+2]};
        near(length(load_momentum-Vec3{4e-7*mass,0,0}),0,2e-20,"finite force assembly momentum incorrect");

        Target falling(preset);falling.settings.gravity={0,-9.81,0};auto gravity=falling.backend();
        require(runNativeFixedTargetTrial(tool.world,*gravity,[&] {
            for(double dt:{1e-7,5e-8,2.5e-8})gravity->advanceExternalContactStep(dt,[&]{tool.world.step(dt);});return true;
        }),"variable gravity trial refused");
        const auto fallen=falling.download(*gravity);const double time=1.75e-7;
        Vec3 gravity_momentum{},center_displacement{};
        for(unsigned i=0;i<fallen.node_count;++i) {
            gravity_momentum+=fallen.mass[i]*Vec3{fallen.v[3*i],fallen.v[3*i+1],fallen.v[3*i+2]};
            center_displacement+=fallen.mass[i]*Vec3{fallen.u[3*i],fallen.u[3*i+1],fallen.u[3*i+2]};
        }
        near(length(gravity_momentum-Vec3{0,-9.81*time*mass,0}),0,2e-20,"variable gravity momentum differs from analytical freefall");
        near(length(center_displacement/mass-Vec3{0,-.5*9.81*time*time,0}),0,1e-24,"variable gravity center differs from analytical freefall");
        near(gravity->externalContactElapsedTime(),time,1e-22,"variable gravity physical clock");
        near(gravity->status().gravity_load.elapsed_s,time,1e-22,"gravity ledger used uploaded horizon");
        near(gravity->status().gravity_load.impulse_n_s.y,-mass*9.81*time,2e-20,"variable gravity momentum ledger");
        require(fallen.mass==falling.state.mass,"variable stepping changed material mass");
        auto single=makeCpuLatticeBackend(target.schedule,Precision::Float);
        rejects([&]{(void)single->externalContactElapsedTime();},"float contact clock silently supported");
        rejects([&]{single->advanceExternalContactStep(5e-8,[]{});},"float variable contact silently supported");
        auto legacy=target.settings;legacy.bond_integrator=kBondXpbd;
        auto parallel=makeParallelCpuLatticeBackend(target.schedule,Precision::Double,2);parallel->upload(target.state,legacy,{});
        rejects([&]{(void)parallel->externalContactElapsedTime();},"parallel contact clock silently supported");
        rejects([&]{parallel->advanceExternalContactStep(5e-8,[]{});},"parallel variable contact silently supported");
        auto xpbd=target.backend();xpbd->upload(target.state,legacy,{});
        rejects([&]{(void)xpbd->externalContactElapsedTime();},"XPBD contact clock silently supported");
        rejects([&]{xpbd->advanceExternalContactStep(5e-8,[]{});},"XPBD variable contact silently supported");
        std::cout<<"VARIABLE_CONTACT {\"material\":\""<<materialPresetName(preset)<<"\",\"target_mass_kg\":"<<mass
            <<",\"accepted_time_s\":"<<b->externalContactElapsedTime()<<",\"gravity_time_s\":"<<time
            <<",\"gravity_impulse_n_s\":"<<gravity->status().gravity_load.impulse_n_s.y
            <<",\"attributed_p_residual_n_s\":"<<p_residual<<",\"attributed_l_residual_kg_m2_s\":"<<l_residual
            <<",\"attributed_e_residual_j\":"<<e_residual<<"}\n";
    }
}
NativeContactStepAudit surfaceAudit(const NativeFixedSurfaceTransfer &r) {
    NativeContactStepAudit a;
    a.contact_loss_j=r.source.contact.modal_contact.dissipated_energy_j;
    a.reconciliation_loss_j=r.source.contact.reconciliation_loss_j;
    a.source_numerical_energy_j=r.source.numerical_energy_change_j;
    a.source_numerical_impulse_n_s=r.source.momentum_error_kg_m_s;
    a.source_numerical_angular_kg_m2_s=r.source.angular_momentum_error_kg_m2_s;
    a.geometry_couple_kg_m2_s=r.source.contact.geometry_couple_kg_m2_s;
    a.active_manifolds=r.source.contact.modal_contact.applied?1:0;return a;
}
void simultaneousAdmissionOracle() {
    Tool tool;
    for(auto id:{1U,10U}) {
        auto pose=tool.world.snapshot(id);pose.linear_velocity_m_s={};pose.angular_velocity_rad_s={};
        tool.world.applyRigidState(id,pose);
    }
    auto nodes=cube();
    for(auto &node:nodes)node.velocity_m_s={-50*node.position_world_m.x,0,0};
    std::vector<std::uint32_t> ids;for(unsigned i=0;i<nodes.size();++i)ids.push_back(i);
    const PointRigidContactSettings frictionless{0,0,0};const PointContactRoundoffBudget budget{1e-12,1e-12,1e-12};
    const Vec3 left{-.04,0,0},right{.04,0,0};
    const auto isolated=makeMaterialContactStencil(nodes,left);
    rejects([&]{(void)tool.world.prepareExternalFixedPointContact(2,1,isolated.point,{-1,0,0},0,1e-7,frictionless,budget);},
        "isolated witness unexpectedly met strict native rounding budget");
    std::vector<FixedSurfaceContact> contacts{{ids,left,{-1,0,0},0,frictionless},{ids,right,{1,0,0},0,frictionless}};
    const auto full=tool.world.prepareExternalFixedSurfaceManifold(2,1,nodes,contacts,1e-7,budget).receipt();
    require(full.contact.active_contacts==2,"coupled symmetric admission omitted a contact");
    near(length(full.momentum_error_kg_m_s),0,1e-12,"symmetric coupled admission linear budget");
    near(full.numerical_energy_change_j,0,1e-12,"symmetric coupled admission energy budget");
    std::reverse(contacts.begin(),contacts.end());
    const auto reverse=tool.world.prepareExternalFixedSurfaceManifold(2,1,nodes,contacts,1e-7,budget).receipt();
    for(unsigned i=0;i<nodes.size();++i)
        near(length(full.contact.node_velocities_m_s[i]-reverse.contact.node_velocities_m_s[i]),0,1e-14,
            "first witness selected coupled native admission");
    std::cout<<"[PASS] coupled admission evaluates the actual manifold instead of its isolated first witness\n";
}
void slowRelativeManifoldOracle() {
    // A common translation must not force an unused isolated response through
    // a relative-speed audit before the actual simultaneous response is solved.
    auto nodes=cube();
    for(auto &node:nodes)node.velocity_m_s={6-2.5e-6*node.position_world_m.x,0,0};
    RigidMechanicalState source;source.mass_kg=1;
    source.inertia_world_kg_m2.m={{{.01,0,0},{0,.01,0},{0,0,.01}}};
    source.motion.linear_velocity_m_s={6,0,0};
    std::vector<std::uint32_t> ids;for(unsigned i=0;i<nodes.size();++i)ids.push_back(i);
    const PointRigidContactSettings law{0,0,0};
    const Vec3 left{-.04,.01,.01},right{.04,-.01,-.01};
    const auto isolated=makeMaterialContactStencil(nodes,left);
    rejects([&]{(void)evaluatePointRigidContact(isolated.point,source,{-1,0,0},0,1e-7,law);},
        "slow-relative isolated audit fixture no longer reproduces refusal");
    const std::vector<FixedSurfaceContact> contacts{{ids,left,{-1,0,0},0,law},{ids,right,{1,0,0},0,law}};
    const auto response=evaluateFixedSurfaceManifold(nodes,contacts,{source},{},0,1e-7);
    require(response.active_contacts==2,"slow-relative manifold omitted simultaneous contact");
    near(length(response.momentum_residual_kg_m_s),0,1e-12,"slow-relative manifold momentum");
    near(length(response.angular_residual_kg_m2_s),0,1e-12,"slow-relative manifold angular momentum");
    near(response.work_residual_j,0,1e-12,"slow-relative manifold work");
    auto rest_nodes=nodes;for(auto &node:rest_nodes)node.velocity_m_s.x-=6;
    auto rest_source=source;rest_source.motion.linear_velocity_m_s.x-=6;
    const auto rest=evaluateFixedSurfaceManifold(rest_nodes,contacts,{rest_source},{},0,1e-7);
    for(unsigned i=0;i<contacts.size();++i)
        near(length(response.impulses_n_s[i]-rest.impulses_n_s[i]),0,1e-14,
            "common translation changed simultaneous contact impulse");
    const auto invalid=[&](auto edit) {
        auto bad=contacts;edit(bad.back());
        rejects([&]{(void)evaluateFixedSurfaceManifold(nodes,bad,{source},{},0,1e-7);},
            "invalid late manifold declaration admitted after removing isolated solve");
    };
    invalid([](auto &c){c.normal_world={2,0,0};});
    invalid([](auto &c){c.gap_m=std::numeric_limits<double>::quiet_NaN();});
    invalid([](auto &c){c.settings.static_friction=-1;});
    invalid([](auto &c){c.settings.dynamic_friction=1;});
    invalid([](auto &c){c.settings.restitution=1.1;});
    invalid([](auto &c){c.settings.restitution_speed_threshold_m_s=-1;});
    invalid([](auto &c){c.settings.contact_margin_m=-1;});
    std::cout<<"[PASS] simultaneous slow-relative contact does not solve an unused isolated response\n";
}
void controlledContactOracles() {
    for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Target target(preset);Tool tool;auto b=target.backend();const auto ids=target.support();
        const auto initial_totals=totals(target.state,tool.world);
        require(tool.world.activeBodyIds()==std::vector<MatterBodyId>{1,2,10},"native participant inventory is not sorted/current");
        unsigned calls=0;
        const auto contact=[&](double dt) {
            ++calls;near(b->externalContactTimestep(),dt,0,"controlled contact used wrong horizon");
            return surfaceAudit(applyNativeFixedSurfaceTransfer(tool.world,*b,ids,2,1,
                {.04,.01,.01},{1,0,0},0,{}, {1e-5,1e-5,1e-5}));
        };
        const NativeContactAccuracySettings settings;
        const auto result=advanceNativeFixedTargetControlled(tool.world,*b,1e-7,settings,contact);
        require(result.accepted&&result.topology_agrees&&result.normalized_error<=1,"controlled contact failed to find an accurate interval");
        require(result.attempted_intervals==result.rejected_intervals+1&&calls==3*result.attempted_intervals,
            "controlled contact skipped full/half comparison");
        require(b->status().total_steps==2&&tool.world.stepCount()==2,"controlled trial leaked discarded coarse steps");
        near(b->externalContactElapsedTime(),result.accepted_interval_s,1e-22,"controlled contact committed incorrect time");
        require(result.accepted_audit.active_manifolds>0,"controlled contact lost accepted receipts");
        const auto final_totals=totals(target.download(*b),tool.world);const auto &s=b->status();const auto &a=result.accepted_audit;
        const double p_error=length(final_totals.linear_momentum_kg_m_s-initial_totals.linear_momentum_kg_m_s-
            a.source_numerical_impulse_n_s-a.native_step_impulse_n_s-s.fixed_boundary.impulse_n_s-s.bond_kick_roundoff_impulse_n_s);
        const double l_error=length(final_totals.angular_momentum_kg_m2_s-initial_totals.angular_momentum_kg_m2_s-
            a.source_numerical_angular_kg_m2_s-a.native_step_angular_kg_m2_s-a.geometry_couple_kg_m2_s-
            s.fixed_boundary.angular_impulse_kg_m2_s-s.bond_kick_roundoff_angular_kg_m2_s);
        const double e_error=final_totals.mechanicalEnergy()-initial_totals.mechanicalEnergy()+a.contact_loss_j+a.reconciliation_loss_j+
            s.removed_energy_j+s.plastic_work_j+s.plastic_return_numerical_loss_j-a.source_numerical_energy_j-a.native_step_energy_j-
            s.integration_numerical_energy_j;
        near(p_error,0,1e-9,"controlled contact linear attribution");near(l_error,0,1e-9,"controlled contact angular attribution");
        near(e_error,0,1e-10,"controlled contact energy attribution");near(final_totals.mass_kg,initial_totals.mass_kg,1e-12,"controlled contact changed mass");
        const auto original=target.download(*b);const auto previous=b->status();
        const auto head=tool.world.snapshot(1);const double clock=b->externalContactElapsedTime();const auto tick=tool.world.stepCount();
        const auto unchanged=[&] {
            const auto now=target.download(*b);
            require(now.u==original.u&&now.u_prev==original.u_prev&&now.v==original.v&&now.alive==original.alive&&
                now.damage==original.damage&&now.prev_tensile==original.prev_tensile&&now.prev_compressive==original.prev_compressive&&
                now.prev_shear==original.prev_shear&&now.plastic_strain==original.plastic_strain&&now.plastic_extension==original.plastic_extension,
                "refused accuracy trial leaked material history");
            require(b->status().total_steps==previous.total_steps&&b->status().external_point_transfer.transfers==previous.external_point_transfer.transfers,
                "refused accuracy trial leaked status");
            near(b->externalContactElapsedTime(),clock,0,"refused accuracy trial leaked time");
            require(tool.world.stepCount()==tick,"refused accuracy trial leaked native ticks");
            near(length(tool.world.snapshot(1).linear_velocity_m_s-head.linear_velocity_m_s),0,0,"refused accuracy trial kicked native source");
            near(length(tool.world.snapshot(1).center_of_mass_world_m-head.center_of_mass_world_m),0,0,"refused accuracy trial moved native source");
        };
        auto tight=settings;tight.maximum_halvings=0;
        tight.position_m=tight.velocity_m_s=tight.orientation_rad=tight.angular_velocity_rad_s=1e-30;
        tight.damage_fraction=tight.history_strain=tight.plastic_extension_m=tight.plastic_strain=1e-30;
        tight.energy_j=tight.impulse_n_s=tight.angular_impulse_kg_m2_s=1e-30;
        const auto refused=advanceNativeFixedTargetControlled(tool.world,*b,1e-7,tight,contact);
        require(!refused.accepted&&refused.rejected_intervals==1&&refused.accepted_interval_s==0&&
            refused.accepted_audit.active_manifolds==0,"accuracy exhaustion silently committed a candidate");unchanged();
        require(refused.error_bound>0&&!refused.error_metric.empty(),"accuracy refusal omitted its measured comparison");
        near(refused.compared_interval_s,1e-7,0,"accuracy refusal reported wrong trial interval");
        const auto difference=refused.error_full_value-refused.error_fine_value;
        const double measured=refused.error_is_vector?length(difference):std::abs(difference.x);
        near(measured/refused.error_bound,refused.normalized_error,0,"accuracy refusal values do not reproduce normalized error");
        auto vector_tight=settings;vector_tight.maximum_halvings=0;vector_tight.impulse_n_s=1e-30;
        const auto vector_refused=advanceNativeFixedTargetControlled(tool.world,*b,1e-7,vector_tight,contact);
        require(!vector_refused.accepted&&vector_refused.error_is_vector&&vector_refused.error_bound==1e-30,
            "impulse accuracy refusal lost its vector components");
        near(length(vector_refused.error_full_value-vector_refused.error_fine_value)/vector_refused.error_bound,
            vector_refused.normalized_error,0,"vector comparison does not reproduce accuracy error");unchanged();
        unsigned throwing_calls=0;
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,1e-7,settings,[&](double dt) {
            auto audit=contact(dt);if(++throwing_calls==3)throw std::runtime_error("intentional second-half failure");return audit;
        });},"second half exception accepted");unchanged();
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,1e-7,settings,[&](double dt) {
            tool.world.step(dt);return NativeContactStepAudit{};
        });},"callback native double step accepted");unchanged();
        auto invalid=settings;invalid.energy_j=std::numeric_limits<double>::quiet_NaN();
        const auto old_calls=calls;
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,1e-7,invalid,contact);},"nonfinite accuracy accepted");
        invalid=settings;invalid.maximum_halvings=21;
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,1e-7,invalid,contact);},"unbounded accuracy search accepted");
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,2e-7,settings,contact);},"oversized accuracy horizon accepted");
        require(calls==old_calls,"invalid accuracy request invoked contact");unchanged();
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,1e-7,settings,[](double) {
            NativeContactStepAudit a;a.contact_loss_j=-1;return a;
        });},"negative contact dissipation accepted");unchanged();
        std::vector<Vec3> queued(target.state.node_count,{1,0,0});b->setExternalForces(queued,2);
        rejects([&]{(void)advanceNativeFixedTargetControlled(tool.world,*b,1e-7,settings,contact);},"accuracy control shortened finite force duration");
        unchanged();b->setExternalForces({},0);
        std::cout<<"CONTROLLED_CONTACT {\"material\":\""<<materialPresetName(preset)<<"\",\"accepted_interval_s\":"<<result.accepted_interval_s
            <<",\"attempted_intervals\":"<<result.attempted_intervals<<",\"normalized_error\":"<<result.normalized_error
            <<",\"attributed_p_residual_n_s\":"<<p_error<<",\"attributed_l_residual_kg_m2_s\":"<<l_error
            <<",\"attributed_e_residual_j\":"<<e_error<<"}\n";
    }
}
std::vector<NativeSurfaceWitness> queriedManifoldWitnesses(const Target &target,LatticeBackend &b,Tool &tool) {
    const auto state=target.download(b);std::vector<NativeSurfaceWitness> witnesses;
    for(unsigned i=0;i<state.node_count;++i) {
        const Vec3 at=state.origin+Vec3{state.x0[3*i]+state.u[3*i],state.x0[3*i+1]+state.u[3*i+1],state.x0[3*i+2]+state.u[3*i+2]};
        require(tool.world.materialShapeContacts(10,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts.empty(),"controlled fixture omitted handle contact");
        const auto hits=tool.world.materialShapeContacts(1,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts;
        if(state.inv_mass[i]==0){require(hits.empty(),"controlled fixture omitted direct clamp contact");continue;}
        for(const auto &hit:hits) {
            const auto law=combineContactMaterials(compileContactMaterial(target.material),hit.body_contact);
            witnesses.push_back({i,hit.point_on_body_world_m,hit.normal_world,hit.gap_m,
                {law.static_friction,law.dynamic_friction,law.restitution}});
        }
    }
    return witnesses;
}
NativeContactStepAudit queriedManifoldAudit(const Target &target,LatticeBackend &b,Tool &tool,
    nlohmann::json *trace=nullptr,const std::vector<NativeSurfaceWitness> *fixed_witnesses=nullptr) {
    const auto witnesses=fixed_witnesses?*fixed_witnesses:queriedManifoldWitnesses(target,b,tool);
    nlohmann::json inputs=nlohmann::json::array();
    if(trace)for(const auto &w:witnesses) {
        const auto node=b.externalContactPoint(w.seed);
        inputs.push_back({{"seed",w.seed},{"gap_m",w.gap_m},
            {"point_m",nlohmann::json{w.surface_world_m.x,w.surface_world_m.y,w.surface_world_m.z}},
            {"normal",nlohmann::json{w.normal_world.x,w.normal_world.y,w.normal_world.z}},
            {"envelope_center_m",nlohmann::json{node.position_world_m.x,node.position_world_m.y,node.position_world_m.z}}});
    }
    const auto head=trace?tool.world.snapshot(1):RigidSnapshot{};
    const auto r=applyNativeFixedLocalSurfaceManifold(tool.world,b,witnesses,{.1,3,64,4096},2,1,{1e-5,1e-5,1e-5});
    if(trace)trace->push_back({{"time_s",b.externalContactElapsedTime()},{"dt_s",b.externalContactTimestep()},
        {"witnesses",inputs},{"active_contacts",r.source.contact.active_contacts},
        {"source_center_m",nlohmann::json{head.center_of_mass_world_m.x,head.center_of_mass_world_m.y,head.center_of_mass_world_m.z}},
        {"source_orientation_wxyz",nlohmann::json{head.orientation_world.w,head.orientation_world.x,head.orientation_world.y,head.orientation_world.z}},
        {"target_work_j",r.target.work_j},{"source_roundoff_energy_j",r.source.numerical_energy_change_j},
        {"reconciliation_loss_j",r.source.contact.reconciliation_loss_j},{"contact_loss_j",r.source.contact.dissipated_energy_j}});
    NativeContactStepAudit a;
    a.contact_loss_j=r.source.contact.dissipated_energy_j;a.reconciliation_loss_j=r.source.contact.reconciliation_loss_j;
    a.source_numerical_energy_j=r.source.numerical_energy_change_j;a.source_numerical_impulse_n_s=r.source.momentum_error_kg_m_s;
    a.source_numerical_angular_kg_m2_s=r.source.angular_momentum_error_kg_m2_s;a.geometry_couple_kg_m2_s=r.source.contact.geometry_couple_kg_m2_s;
    a.active_manifolds=r.source.contact.active_contacts?1:0;return a;
}
unsigned controlledSustainedContact() {
    unsigned open=0;
    for(double width:{.04,.12})for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        Target target(preset,1e-7,.12,{.1,0,0});Tool tool(width);
        for(unsigned i=0;i<target.state.node_count;++i)if(target.state.x0[3*i]>.039)target.state.inv_mass[i]=0;
        auto b=target.backend();const auto initial=totals(target.state,tool.world);NativeContactStepAudit sum;
        NativeContactAccuracySettings settings;settings.maximum_halvings=20;
        const double duration=2048e-7;double proposal=1e-7;
        unsigned accepted=0,rejected=0;double smallest=proposal,last_error=0;std::string refusal,metric;bool compared=false;
        NativeContactAccuracyResult last_comparison;
        const auto started=std::chrono::steady_clock::now();
        while(b->externalContactElapsedTime()<duration-1e-18&&accepted<100000) {
            const double remaining=duration-b->externalContactElapsedTime();
            compared=false;metric.clear();
            try {
                const auto r=advanceNativeFixedTargetControlled(tool.world,*b,std::min(proposal,remaining),settings,
                    [&](double){return queriedManifoldAudit(target,*b,tool);});
                rejected+=r.rejected_intervals;
                last_error=r.normalized_error;metric=r.error_metric;compared=true;last_comparison=r;
                if(!r.accepted) {refusal=r.topology_agrees?"accuracy budget exhausted":"topology comparison unresolved";break;}
                ++accepted;smallest=std::min(smallest,r.accepted_interval_s);proposal=r.suggested_interval_s;
                const auto &a=r.accepted_audit;
                sum.contact_loss_j+=a.contact_loss_j;sum.reconciliation_loss_j+=a.reconciliation_loss_j;
                sum.source_numerical_energy_j+=a.source_numerical_energy_j;sum.source_numerical_impulse_n_s+=a.source_numerical_impulse_n_s;
                sum.source_numerical_angular_kg_m2_s+=a.source_numerical_angular_kg_m2_s;sum.geometry_couple_kg_m2_s+=a.geometry_couple_kg_m2_s;
                sum.native_step_energy_j+=a.native_step_energy_j;sum.native_step_impulse_n_s+=a.native_step_impulse_n_s;
                sum.native_step_angular_kg_m2_s+=a.native_step_angular_kg_m2_s;sum.active_manifolds+=a.active_manifolds;
            }catch(const std::exception &e){refusal=e.what();break;}
        }
        if(accepted==100000&&b->externalContactElapsedTime()<duration-1e-18)refusal="accepted interval budget exhausted";
        if(!refusal.empty()) {
            // Separate delivery/reconciliation rounding from native witness
            // changes. Neither system advances, and the same actual geometry
            // declarations are used in both consecutive contact projections.
            const auto witnesses=queriedManifoldWitnesses(target,*b,tool);
            nlohmann::json trace=nlohmann::json::array();
            const auto clock=b->externalContactElapsedTime();const auto tick=tool.world.stepCount();
            require(!runNativeFixedTargetTrial(tool.world,*b,[&] {
                (void)queriedManifoldAudit(target,*b,tool,&trace,&witnesses);
                (void)queriedManifoldAudit(target,*b,tool,&trace,&witnesses);return false;
            }),"contact reapplication committed");
            near(b->externalContactElapsedTime(),clock,0,"contact reapplication advanced time");
            require(tool.world.stepCount()==tick,"contact reapplication advanced native time");
            std::cout<<"CONTACT_REAPPLICATION "<<nlohmann::json{{"material",materialPresetName(preset)},
                {"width_m",width},{"fixed_geometry",true},{"steps",trace}}.dump()<<std::endl;
        }
        if(!refusal.empty())for(double interval:{1e-7,1e-10,1e-12}) {
            nlohmann::json full=nlohmann::json::array(),half=nlohmann::json::array(),fixed_half=nlohmann::json::array();
            const auto witnesses=queriedManifoldWitnesses(target,*b,tool);
            const auto frozen=target.download(*b);const auto clock=b->externalContactElapsedTime();
            const auto tick=tool.world.stepCount();
            const auto trial=[&](unsigned steps,nlohmann::json &trace,bool fixed=false) {
                std::string error;
                try {
                    require(!runNativeFixedTargetTrial(tool.world,*b,[&] {
                        for(unsigned k=0;k<steps;++k)b->advanceExternalContactStep(interval/steps,[&] {
                            (void)queriedManifoldAudit(target,*b,tool,&trace,fixed?&witnesses:nullptr);tool.world.step(interval/steps);
                        });return false;
                    }),"contact refinement isolation committed");
                }catch(const std::exception &e){error=e.what();}
                return error;
            };
            const auto full_error=trial(1,full),half_error=trial(2,half);
            // Diagnostic only: retain the first actual witnesses to isolate
            // native requery from identical native/material stepping. This is
            // not an admissible production geometry cache for moving objects.
            const auto fixed_half_error=interval==1e-12?trial(2,fixed_half,true):std::string{};
            const auto restored=target.download(*b);
            require(restored.u==frozen.u&&restored.v==frozen.v&&restored.alive==frozen.alive,
                "contact refinement isolation changed material state");
            near(b->externalContactElapsedTime(),clock,0,"contact refinement isolation changed clock");
            require(tool.world.stepCount()==tick,"contact refinement isolation changed native clock");
            std::cout<<"CONTACT_STEP_REFINEMENT "<<nlohmann::json{{"material",materialPresetName(preset)},
                {"width_m",width},{"interval_s",interval},{"full",full},{"half",half},
                {"fixed_witness_half",fixed_half},{"fixed_witness_half_error",fixed_half_error},
                {"full_error",full_error},{"half_error",half_error}}.dump()<<std::endl;
        }
        if(!refusal.empty())for(double interval:{1e-7,1e-10,1e-12}) {
            // Isolate native stepping after the refused state. No new contact
            // impulse is applied. Both full and half experiments roll back.
            std::vector<RigidSnapshot> full,half;double full_energy=0,half_energy=0;
            const auto native_ids=tool.world.activeBodyIds();const auto frozen_time=b->externalContactElapsedTime();
            std::vector<RigidSnapshot> frozen;for(auto id:native_ids)frozen.push_back(tool.world.snapshot(id));
            const auto trial=[&](unsigned steps,std::vector<RigidSnapshot> &poses,double &energy) {
                require(!runNativeFixedTargetTrial(tool.world,*b,[&] {
                    for(unsigned k=0;k<steps;++k)b->advanceExternalContactStep(interval/steps,[&]{tool.world.step(interval/steps);});
                    for(auto id:native_ids)poses.push_back(tool.world.snapshot(id));
                    energy=tool.world.mechanicalTotals().mechanicalEnergy();return false;
                }),"native refinement isolation committed");
            };
            trial(1,full,full_energy);trial(2,half,half_energy);double position=0,velocity=0;
            nlohmann::json body_differences=nlohmann::json::array();
            const auto vector_json=[](Vec3 v){return nlohmann::json{v.x,v.y,v.z};};
            const auto quaternion_json=[](Quat q){return nlohmann::json{q.w,q.x,q.y,q.z};};
            for(std::size_t i=0;i<full.size();++i) {
                position=std::max(position,length(full[i].center_of_mass_world_m-half[i].center_of_mass_world_m));
                velocity=std::max(velocity,length(full[i].linear_velocity_m_s-half[i].linear_velocity_m_s));
                body_differences.push_back({{"body",native_ids[i]},
                    {"frozen_position_m",vector_json(frozen[i].center_of_mass_world_m)},
                    {"full_position_delta_m",vector_json(full[i].center_of_mass_world_m-frozen[i].center_of_mass_world_m)},
                    {"half_position_delta_m",vector_json(half[i].center_of_mass_world_m-frozen[i].center_of_mass_world_m)},
                    {"frozen_orientation_wxyz",quaternion_json(frozen[i].orientation_world)},
                    {"full_orientation_wxyz",quaternion_json(full[i].orientation_world)},
                    {"half_orientation_wxyz",quaternion_json(half[i].orientation_world)},
                    {"frozen_velocity_m_s",vector_json(frozen[i].linear_velocity_m_s)},
                    {"full_velocity_m_s",vector_json(full[i].linear_velocity_m_s)},
                    {"half_velocity_m_s",vector_json(half[i].linear_velocity_m_s)},
                    {"frozen_spin_rad_s",vector_json(frozen[i].angular_velocity_rad_s)},
                    {"full_spin_rad_s",vector_json(full[i].angular_velocity_rad_s)},
                    {"half_spin_rad_s",vector_json(half[i].angular_velocity_rad_s)}});
                const auto restored=tool.world.snapshot(native_ids[i]);
                near(length(restored.center_of_mass_world_m-frozen[i].center_of_mass_world_m),0,0,
                    "native isolation changed frozen position");
                near(length(restored.linear_velocity_m_s-frozen[i].linear_velocity_m_s),0,0,
                    "native isolation changed frozen velocity");
            }
            near(b->externalContactElapsedTime(),frozen_time,0,"native isolation changed accepted clock");
            std::cout<<"NATIVE_STEP_REFINEMENT "<<nlohmann::json{{"material",materialPresetName(preset)},{"width_m",width},
                {"interval_s",interval},{"maximum_position_difference_m",position},{"maximum_velocity_difference_m_s",velocity},
                {"energy_difference_j",full_energy-half_energy},{"body_differences",body_differences}}.dump()<<std::endl;
        }
        const auto state=target.download(*b);const auto final=totals(state,tool.world);const auto &s=b->status();
        const double p=length(final.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-sum.source_numerical_impulse_n_s-
            sum.native_step_impulse_n_s-s.fixed_boundary.impulse_n_s-s.bond_kick_roundoff_impulse_n_s);
        const double l=length(final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-sum.source_numerical_angular_kg_m2_s-
            sum.native_step_angular_kg_m2_s-sum.geometry_couple_kg_m2_s-s.fixed_boundary.angular_impulse_kg_m2_s-s.bond_kick_roundoff_angular_kg_m2_s);
        const double e=final.mechanicalEnergy()-initial.mechanicalEnergy()+sum.contact_loss_j+sum.reconciliation_loss_j+s.removed_energy_j+
            s.plastic_work_j+s.plastic_return_numerical_loss_j-sum.source_numerical_energy_j-sum.native_step_energy_j-s.integration_numerical_energy_j;
        near(p,0,1e-9,"controlled sustained linear attribution");near(l,0,1e-9,"controlled sustained angular attribution");
        near(e,0,1e-10,"controlled sustained energy attribution");near(final.mass_kg,initial.mass_kg,1e-12,"controlled sustained changed mass");
        require(s.total_steps==2*accepted&&tool.world.stepCount()==2*accepted,"controlled sustained leaked trial steps");
        if(!refusal.empty()||std::abs(b->externalContactElapsedTime()-duration)>1e-18)++open;
        std::cout<<"CONTROLLED_SUSTAINED "<<nlohmann::json{{"material",materialPresetName(preset)},{"width_m",width},
            {"accepted_time_s",b->externalContactElapsedTime()},{"accepted_intervals",accepted},{"rejected_intervals",rejected},
            {"minimum_interval_s",smallest},{"broken_bonds",s.broken_bonds},{"refusal",refusal},{"attributed_p_residual_n_s",p},
            {"last_normalized_error",compared?nlohmann::json(last_error):nlohmann::json(nullptr)},{"error_metric",metric},
            {"comparison_interval_s",last_comparison.compared_interval_s},{"comparison_bound",last_comparison.error_bound},
            {"comparison_is_vector",last_comparison.error_is_vector},
            {"comparison_full_value",nlohmann::json{last_comparison.error_full_value.x,last_comparison.error_full_value.y,last_comparison.error_full_value.z}},
            {"comparison_fine_value",nlohmann::json{last_comparison.error_fine_value.x,last_comparison.error_fine_value.y,last_comparison.error_fine_value.z}},
            {"attributed_l_residual_kg_m2_s",l},{"attributed_e_residual_j",e},{"integration_error_j",s.integration_numerical_energy_j},
            {"wall_s",std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()}}.dump()<<std::endl;
    }
    return open;
}
// Capture is read-only, sampled after accepted physical steps. No render clock,
// interpolation, fragment templates or extra impulses enter the experiment.
nlohmann::json vectorJson(Vec3 v){return {v.x,v.y,v.z};}
nlohmann::json contactFrame(const Target &target,LatticeBackend &backend,Tool &tool,unsigned step,double dt) {
    const auto state=target.download(backend);
    const auto partition=partitionConstituents(target.asset,target.schedule,state);
    nlohmann::json nodes=nlohmann::json::array(),bonds=nlohmann::json::array(),source=nlohmann::json::array();
    std::vector<unsigned> component(state.node_count);std::vector<bool> attached(state.node_count);
    for(unsigned c=0;c<partition.components.size();++c)for(auto n:partition.components[c].parent_nodes){component[n]=c;attached[n]=partition.components[c].attached_to_boundary;}
    for(unsigned i=0;i<state.node_count;++i){
        const Vec3 displacement{state.u[3*i],state.u[3*i+1],state.u[3*i+2]};
        const Vec3 p=state.origin+Vec3{state.x0[3*i],state.x0[3*i+1],state.x0[3*i+2]}+displacement;
        nodes.push_back({{"id",i},{"position_m",vectorJson(p)},{"displacement_m",vectorJson(displacement)},
            {"velocity_m_s",vectorJson({state.v[3*i],state.v[3*i+1],state.v[3*i+2]})},{"mass_kg",state.mass[i]},
            {"component",component[i]},{"attached",static_cast<bool>(attached[i])},{"clamped",state.inv_mass[i]==0}});
    }
    for(unsigned k=0;k<state.bond_count;++k)bonds.push_back({state.alive[k]!=0,state.damage[k]});
    for(auto id:{1U,10U}){
        const auto body=tool.world.snapshot(id);const auto q=body.orientation_world;
        source.push_back({{"id",id},{"position_m",vectorJson(body.center_of_mass_world_m)},
            {"orientation_wxyz",{q.w,q.x,q.y,q.z}},{"velocity_m_s",vectorJson(body.linear_velocity_m_s)},
            {"angular_velocity_rad_s",vectorJson(body.angular_velocity_rad_s)}});
    }
    return {{"step",step},{"time_s",step*dt},{"nodes",nodes},{"bond_state",bonds},{"source",source},
        {"components",partition.components.size()},{"broken_bonds",backend.status().broken_bonds},
        {"integration_error_j",backend.status().integration_numerical_energy_j}};
}
unsigned sustainedLocalContact(nlohmann::json *recording=nullptr, bool reverse=false, bool manifold=false,unsigned refinement_levels=2) {
    unsigned open_gates=0;
    for(double width:{.04,.12})for(auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        std::vector<std::uint8_t> coarse_alive;double coarse_error=0;
        for(unsigned level=0;level<refinement_levels;++level) {
            const double dt=std::ldexp(1e-7,-static_cast<int>(level));
            Target target(preset,dt,.12,{.1,0,0});Tool tool(width);
            for(unsigned i=0;i<target.state.node_count;++i)if(target.state.x0[3*i]>.039)target.state.inv_mass[i]=0;
            auto backend=target.backend();const auto initial=totals(target.state,tool.world);
            struct Ledger {
                double loss{},reconcile{},transfer_energy{},native_energy{};
                Vec3 transfer_p{},transfer_l{},geometry_couple{},native_p{},native_l{};
                unsigned contacts{},minimum_nodes{64},maximum_nodes{};
            } sum;
            std::string refusal;unsigned attempted=0,accepted=0;const unsigned count=2048U<<level;
            const auto started=std::chrono::steady_clock::now();
            nlohmann::json frames=nlohmann::json::array();
            nlohmann::json fracture_events=nlohmann::json::array();
            if(recording)frames.push_back(contactFrame(target,*backend,tool,0,dt));
            for(unsigned k=0;k<count;++k) {
                ++attempted;Ledger delta;const auto before=target.download(*backend);const auto old=backend->status();
                const auto head=tool.world.snapshot(1),handle=tool.world.snapshot(10);
                const bool ok=runNativeFixedTargetTrial(tool.world,*backend,[&] {
                    if(manifold) {
                    std::vector<NativeSurfaceWitness> witnesses;
                    for(unsigned order=0;order<before.node_count;++order) {
                        const unsigned i=reverse?before.node_count-1-order:order;
                        const Vec3 at=before.origin+Vec3{before.x0[3*i]+before.u[3*i],before.x0[3*i+1]+before.u[3*i+1],before.x0[3*i+2]+before.u[3*i+2]};
                        require(tool.world.materialShapeContacts(10,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts.empty(),"sustained fixture omitted handle contact");
                        const auto hits=tool.world.materialShapeContacts(1,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts;
                        if(before.inv_mass[i]==0){require(hits.empty(),"sustained fixture omitted direct clamp contact");continue;}
                        for(const auto &hit:hits) {
                            // Only support admission can end this bounded experiment.
                            // Any source-law or integrator failure still fails the test.
                            try {
                                const auto region=backend->externalContactRegion(i,{.1,3,64,4096});
                                std::vector<ActiveNodeState> points;
                                for(const auto n:region.nodes)points.push_back(backend->externalContactPoint(n));
                                (void)makeMaterialContactStencil(points,hit.point_on_body_world_m);
                            }catch(const std::invalid_argument &e){refusal=e.what();return false;}
                            const auto law=combineContactMaterials(compileContactMaterial(target.material),hit.body_contact);
                            witnesses.push_back({i,hit.point_on_body_world_m,hit.normal_world,hit.gap_m,
                                {law.static_friction,law.dynamic_friction,law.restitution}});
                        }
                    }
                    const auto r=applyNativeFixedLocalSurfaceManifold(tool.world,*backend,witnesses,{.1,3,64,4096},2,1,{1e-5,1e-5,1e-5});
                    if(r.source.contact.active_contacts) {
                        ++delta.contacts;
                        for(const auto &region:r.regions) {
                            delta.minimum_nodes=std::min(delta.minimum_nodes,static_cast<unsigned>(region.nodes.size()));
                            delta.maximum_nodes=std::max(delta.maximum_nodes,static_cast<unsigned>(region.nodes.size()));
                        }
                        delta.loss+=r.source.contact.dissipated_energy_j;delta.reconcile+=r.source.contact.reconciliation_loss_j;
                        delta.transfer_energy+=r.source.numerical_energy_change_j;delta.transfer_p+=r.source.momentum_error_kg_m_s;
                        delta.transfer_l+=r.source.angular_momentum_error_kg_m2_s;delta.geometry_couple+=r.source.contact.geometry_couple_kg_m2_s;
                    }
                    } else {
                    for(unsigned order=0;order<before.node_count;++order) {
                        const unsigned i=reverse?before.node_count-1-order:order;
                        const Vec3 at=before.origin+Vec3{before.x0[3*i]+before.u[3*i],before.x0[3*i+1]+before.u[3*i+1],before.x0[3*i+2]+before.u[3*i+2]};
                        require(tool.world.materialShapeContacts(10,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts.empty(),"sustained fixture omitted handle contact");
                        const auto hits=tool.world.materialShapeContacts(1,at,{PrimitiveKind::Box,0,{.04,.04,.04}},{},1e-5).contacts;
                        if(before.inv_mass[i]==0){require(hits.empty(),"sustained fixture omitted direct clamp contact");continue;}
                        for(const auto &hit:hits) {
                            // Only support admission can end this bounded experiment.
                            // Any source-law or integrator failure still fails the test.
                            try {
                                const auto region=backend->externalContactRegion(i,{.1,3,64,4096});
                                std::vector<ActiveNodeState> points;
                                for(const auto n:region.nodes)points.push_back(backend->externalContactPoint(n));
                                (void)makeMaterialContactStencil(points,hit.point_on_body_world_m);
                            }catch(const std::invalid_argument &e){refusal=e.what();return false;}
                            const auto law=combineContactMaterials(compileContactMaterial(target.material),hit.body_contact);
                            const auto r=applyNativeFixedLocalSurfaceTransfer(tool.world,*backend,i,{.1,3,64,4096},2,1,
                                hit.point_on_body_world_m,hit.normal_world,hit.gap_m,
                                {law.static_friction,law.dynamic_friction,law.restitution},{1e-5,1e-5,1e-5});
                            if(!r.source.contact.modal_contact.applied)continue;
                            ++delta.contacts;delta.minimum_nodes=std::min(delta.minimum_nodes,static_cast<unsigned>(r.region.nodes.size()));
                            delta.maximum_nodes=std::max(delta.maximum_nodes,static_cast<unsigned>(r.region.nodes.size()));
                            delta.loss+=r.source.contact.modal_contact.dissipated_energy_j;delta.reconcile+=r.source.contact.reconciliation_loss_j;
                            delta.transfer_energy+=r.source.numerical_energy_change_j;delta.transfer_p+=r.source.momentum_error_kg_m_s;
                            delta.transfer_l+=r.source.angular_momentum_error_kg_m2_s;delta.geometry_couple+=r.source.contact.geometry_couple_kg_m2_s;
                        }
                    }
                    }
                    const auto a=tool.world.mechanicalTotals();tool.world.step(dt);const auto b=tool.world.mechanicalTotals();backend->run({.max_steps=1});
                    delta.native_energy=b.kinetic_energy_j-a.kinetic_energy_j;delta.native_p=b.linear_momentum_kg_m_s-a.linear_momentum_kg_m_s;
                    delta.native_l=b.angular_momentum_kg_m2_s-a.angular_momentum_kg_m2_s;return true;
                });
                if(!ok) {
                    const auto restored=target.download(*backend);
                    require(!refusal.empty()&&restored.u==before.u&&restored.u_prev==before.u_prev&&restored.v==before.v&&
                        restored.alive==before.alive&&restored.damage==before.damage&&restored.plastic_strain==before.plastic_strain&&
                        restored.prev_tensile==before.prev_tensile&&restored.prev_compressive==before.prev_compressive&&restored.prev_shear==before.prev_shear&&
                        backend->status().total_steps==old.total_steps&&backend->status().external_point_transfer.transfers==old.external_point_transfer.transfers&&
                        backend->status().fixed_boundary.impulse_n_s.x==old.fixed_boundary.impulse_n_s.x,"unsupported live region leaked tentative target state/accounts");
                    for(const auto &[id,snapshot]:{std::pair{1U,head},std::pair{10U,handle}}) {
                        const auto now=tool.world.snapshot(id);
                        near(length(now.center_of_mass_world_m-snapshot.center_of_mass_world_m),0,0,"unsupported live region moved source");
                        near(length(now.linear_velocity_m_s-snapshot.linear_velocity_m_s),0,0,"unsupported live region kicked source");
                        near(length(now.angular_velocity_rad_s-snapshot.angular_velocity_rad_s),0,0,"unsupported live region spun source");
                    }
                    break;
                }
                ++accepted;sum.contacts+=delta.contacts;sum.minimum_nodes=std::min(sum.minimum_nodes,delta.minimum_nodes);sum.maximum_nodes=std::max(sum.maximum_nodes,delta.maximum_nodes);
                sum.loss+=delta.loss;sum.reconcile+=delta.reconcile;sum.transfer_energy+=delta.transfer_energy;sum.native_energy+=delta.native_energy;
                sum.transfer_p+=delta.transfer_p;sum.transfer_l+=delta.transfer_l;sum.geometry_couple+=delta.geometry_couple;sum.native_p+=delta.native_p;sum.native_l+=delta.native_l;
                if(recording&&accepted%(count/32)==0)frames.push_back(contactFrame(target,*backend,tool,accepted,dt));
                if(recording&&backend->status().broken_bonds!=old.broken_bonds)
                    fracture_events.push_back(contactFrame(target,*backend,tool,accepted,dt));
            }
            const auto state=target.download(*backend);const auto final=totals(state,tool.world);const auto &s=backend->status();
            const Vec3 p=final.linear_momentum_kg_m_s-initial.linear_momentum_kg_m_s-sum.transfer_p-s.fixed_boundary.impulse_n_s-s.bond_kick_roundoff_impulse_n_s;
            const Vec3 l=final.angular_momentum_kg_m2_s-initial.angular_momentum_kg_m2_s-sum.transfer_l-sum.geometry_couple-s.fixed_boundary.angular_impulse_kg_m2_s-s.bond_kick_roundoff_angular_kg_m2_s;
            const double energy=final.mechanicalEnergy()-initial.mechanicalEnergy()+sum.loss+sum.reconcile+s.removed_energy_j+s.plastic_work_j+s.plastic_return_numerical_loss_j-sum.transfer_energy;
            near(length(p-sum.native_p),0,1e-9,"live graph full linear attribution");near(length(l-sum.native_l),0,1e-9,"live graph full angular attribution");
            near(energy-sum.native_energy,s.integration_numerical_energy_j,1e-10,"live graph full energy attribution");near(final.mass_kg,initial.mass_kg,1e-12,"live graph changed material mass");
            require(sum.contacts>0&&s.external_point_transfer.transfers==sum.contacts&&s.total_steps==accepted,"live graph lost accepted transfer/time identity");
            require(std::abs(s.integration_numerical_energy_j)<.001*initial.mechanicalEnergy(),"live graph exceeded retained integration bound");
            if(preset==MaterialPreset::Oak)require(s.broken_bonds==0,"live graph made oak brittle");
            if(level>0) {
                if(coarse_alive!=state.alive) {
                    ++open_gates;std::cout<<"OPEN live-contact topology refinement: "<<materialPresetName(preset)<<", width "<<width<<", dt "<<dt<<'\n';
                }
                if(std::abs(s.integration_numerical_energy_j)>=.27*coarse_error) {
                    ++open_gates;std::cout<<"OPEN live-contact integration refinement: "<<materialPresetName(preset)<<", width "<<width<<", dt "<<dt<<'\n';
                }
            }
            coarse_alive=state.alive;coarse_error=std::abs(s.integration_numerical_energy_j);
            const auto partition=partitionConstituents(target.asset,target.schedule,state);
            unsigned attached=0;double detached_mass=0;
            for(const auto &component:partition.components) {
                if(component.attached_to_boundary)++attached;
                else for(double mass:component.state.mass)detached_mass+=mass;
            }
            if(recording){
                require(fracture_events.size()==s.failure_rounds,"fracture event capture lost an accepted failure round");
                if(frames.back().at("step").get<unsigned>()!=accepted)frames.push_back(contactFrame(target,*backend,tool,accepted,dt));
                nlohmann::json topology=nlohmann::json::array();
                for(unsigned k=0;k<state.bond_count;++k)topology.push_back({state.bond_a[k],state.bond_b[k]});
                recording->at("experiments").push_back({{"material",materialPresetName(preset)},{"width_m",width},{"dt_s",dt},{"cell_m",.04},
                    {"density_kg_m3",target.material.density_kg_m3},{"young_modulus_pa",target.material.young_modulus_pa},
                    {"accepted_steps",accepted},{"attempted_steps",attempted},{"unsupported_region",refusal},
                    {"bond_topology",topology},{"frames",frames},{"fracture_events",fracture_events},{"detached_mass_kg",detached_mass},{"contacts",sum.contacts},
                    {"attributed_linear_error_n_s",length(p-sum.native_p)},{"attributed_angular_error_kg_m2_s",length(l-sum.native_l)},
                    {"attributed_energy_error_j",energy-sum.native_energy-s.integration_numerical_energy_j}});
            }
            std::cout<<"LIVE_GRAPH_CONTACT_EVIDENCE {\"material\":\""<<materialPresetName(preset)<<"\",\"width_m\":"<<width<<",\"cell_m\":0.04,\"dt_s\":"<<dt
                <<",\"accepted_steps\":"<<accepted<<",\"attempted_steps\":"<<attempted<<",\"accepted_time_s\":"<<accepted*dt<<",\"contacts\":"<<sum.contacts
                <<",\"minimum_support_nodes\":"<<sum.minimum_nodes<<",\"maximum_support_nodes\":"<<sum.maximum_nodes<<",\"broken_bonds\":"<<s.broken_bonds
                <<",\"components\":"<<partition.components.size()<<",\"attached_components\":"<<attached<<",\"detached_mass_kg\":"<<detached_mass
                <<",\"unsupported_region\":\""<<refusal<<"\",\"total_mass_kg\":"<<final.mass_kg
                <<",\"p_residual_n_s\":"<<length(p)<<",\"l_residual_kg_m2_s\":"<<length(l)<<",\"unallocated_energy_j\":"<<energy
                <<",\"attributed_linear_error_n_s\":"<<length(p-sum.native_p)<<",\"attributed_angular_error_kg_m2_s\":"<<length(l-sum.native_l)
                <<",\"attributed_energy_error_j\":"<<energy-sum.native_energy-s.integration_numerical_energy_j
                <<",\"native_step_energy_j\":"<<sum.native_energy<<",\"integration_error_j\":"<<s.integration_numerical_energy_j
                <<",\"wall_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()<<"}\n";
        }
    }
    return open_gates;
}
void matchedNativeSurfaceTrajectories(bool local=false) {
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
                        const PointRigidContactSettings settings{law.static_friction,law.dynamic_friction,law.restitution};
                        const PointContactRoundoffBudget budget{1e-5,1e-5,1e-5};
                        const auto r=local?applyNativeFixedLocalSurfaceTransfer(tool.world,*b,i,{.08,3,64,4096},2,1,
                            hit.point_on_body_world_m,hit.normal_world,hit.gap_m,settings,budget):
                            applyNativeFixedSurfaceTransfer(tool.world,*b,ids,2,1,hit.point_on_body_world_m,hit.normal_world,hit.gap_m,settings,budget);
                        if(local)require(r.region.nodes.size()==8&&r.region.target_step==b->status().total_steps,"local comparison stale region");
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
            std::cout<<(local?"LOCAL_SURFACE_EVIDENCE ":"SURFACE_CONTACT_EVIDENCE ")<<"{\"material\":\""<<materialPresetName(preset)<<"\",\"width_m\":"<<width<<",\"cell_m\":0.04,\"dt_s\":"<<dt
                <<",\"steps\":"<<count<<",\"support_nodes\":"<<ids.size()<<",\"contacts\":"<<contacts<<",\"target_mass_kg\":"<<target.material.density_kg_m3*.000512
                <<",\"total_mass_kg\":"<<final.mass_kg<<",\"broken_bonds\":"<<s.broken_bonds<<",\"p_residual_n_s\":"<<length(p)<<",\"l_residual_kg_m2_s\":"<<length(l)
                <<",\"unallocated_energy_j\":"<<e<<",\"integration_error_j\":"<<s.integration_numerical_energy_j<<",\"native_step_energy_j\":"<<native_e
                <<",\"target_work_error_j\":"<<max_target_work<<",\"target_impulse_error_n_s\":"<<max_target_p<<",\"target_angular_error_kg_m2_s\":"<<max_target_l
                <<",\"wall_s\":"<<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<"}\n";
        }
    }
}
}
int main(int argc,char **argv){try{
    bool strict=false,reverse=false,manifold=false,oracles_only=false,controlled=false;std::string output;unsigned refinement_levels=2;bool refinement_requested=false;
    for(int i=1;i<argc;++i){const std::string option=argv[i];
        if(option=="--require-live-contact-convergence"&&!strict)strict=true;
        else if(option=="--coupled-manifold")manifold=true;
        else if(option=="--manifold-oracles-only")oracles_only=true;
        else if(option=="--controlled-manifold")controlled=true;
        else if(option=="--reverse-contact-order")reverse=true;
        else if(option=="--refinement-levels"&&!refinement_requested&&i+1<argc) {
            const std::string value=argv[++i];require(value.size()==1&&value[0]>='2'&&value[0]<='5',"refinement levels must be 2..5");
            refinement_levels=static_cast<unsigned>(value[0]-'0');refinement_requested=true;
        }
        else if(option=="--record"&&output.empty()&&i+1<argc)output=argv[++i];
        else require(false,"unknown surface-contact test option");
    }
    nlohmann::json recording={{"schema","banjo.contact-recording.v1"},{"kind","solver-recording"},{"experiments",nlohmann::json::array()}};
    if(refinement_levels>2) {
        recording["schema"]="banjo.contact-refinement.v1";
        recording["kind"]="solver-refinement-recording";
    }
    std::cout.precision(12);liveGraphSelectionOracles();analyticalSurfaceOracles();bulkAtomicity();authoritativeTopologyAdmission();
    require(!(oracles_only&&(strict||manifold||reverse||refinement_requested||!output.empty()||controlled)),"oracle-only mode cannot imply sustained acceptance");
    require(!controlled||(!strict&&!manifold&&!reverse&&!refinement_requested&&output.empty()),"controlled experiment uses its separate live accuracy gate");
    require(!refinement_requested||manifold,"extended refinement requires the explicit coupled manifold experiment");
    std::cout<<"NATIVE_ROTATION_PROFILE "<<JoltWorld::rotationIntegrationProfile()<<'\n';
    manifoldOracles();variableContactStepOracles();simultaneousAdmissionOracle();slowRelativeManifoldOracle();controlledContactOracles();
    if(oracles_only){std::cout<<"[PASS] coupled manifold analytical/native atomicity oracles\n";return 0;}
    if(controlled){const auto open=controlledSustainedContact();std::cout<<"Controlled sustained open gates: "<<open<<'\n';return open?1:0;}
    matchedNativeSurfaceTrajectories();matchedNativeSurfaceTrajectories(true);const auto open=sustainedLocalContact(output.empty()?nullptr:&recording,reverse,manifold,refinement_levels);
    if(!output.empty()){
        recording["open_convergence_gates"]=open;recording["coupled_manifold"]=manifold;recording["refinement_levels"]=refinement_levels;
        std::ofstream file(output,std::ios::binary);require(static_cast<bool>(file),"cannot open recording output");
        file<<recording.dump();file.flush();require(static_cast<bool>(file),"cannot write complete recording");
    }
    std::cout<<"[PASS] bounded material surface transfer; open sustained convergence gates: "<<open<<'\n';
    if(strict&&open){std::cerr<<"[FAIL] sustained surface-contact acceptance remains open\n";return 1;}
    return 0;
}catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}}
