#include "fastlattice/SolidMatterPatch.hpp"
#include "material/MaterialCatalog.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <set>
#include <stdexcept>

namespace {
using namespace banjo;
using namespace banjo::fastlattice;
void require(bool yes,const char *why) {if (!yes) throw std::runtime_error(why);}
void near(double a,double b,double tol,const char *why) {require(std::isfinite(a)&&std::abs(a-b)<=tol,why);}
void balance(const SolidMatterPatch &patch) {
    const auto r=patch.report();
    near(r.energy_residual_j,0,1e-8*std::max(1.,std::abs(r.source_work_j)),"full patch energy ledger");
    near(length(r.momentum_residual_kg_m_s),0,1e-8,"full patch momentum ledger");
    near(length(r.angular_residual_kg_m2_s),0,1e-8,"full patch angular ledger");
    std::set<unsigned> ids;double mass=0,volume=0;
    for (const auto &part:patch.components()) for (const auto &cell:part.cells) {
        require(cell.source=="terrain:0:0:0","cell lost source identity");
        require(ids.insert(cell.source_node).second,"cell duplicated across components");
        mass+=cell.mass_kg;volume+=cell.volume_m3;
        near(cell.edge_m,.05,0,"component changed voxel geometry");
    }
    require(ids.size()==125,"source cells disappeared on fracture");
    near(mass,r.mass_kg,1e-10,"all component masses retain source mass");
    near(volume,.25*.25*.25,1e-12,"all cells retain terrain volume");
}
void materialsAndRetainedState() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Concrete}) {
        const auto material=makeReferenceMaterial(preset,17);
        SolidMatterPatch patch("terrain:0:0:0",{.25,.25,.25},.05,material);
        require(patch.components().size()==1,"whole patch starts prefragmented");
        near(patch.report().mass_kg,patch.asset().total_mass_kg,0,"declared cell mass");
        std::vector<Vec3> forces(125);
        const auto untouched=patch.pulse(forces,64,0);
        require(untouched.state.broken_bonds==0,"unloaded solid breaks itself");
        balance(patch);
        // Opposed surface tractions, same SI force/geometry across materials.
        // External fixture reaction is in the source ledger; this is not a
        // pickaxe velocity, prescribed shard motion, or human-strength claim.
        forces[2+5*(4+5*2)]={0,4e5,0};
        forces[2+5*(0+5*2)]={0,-4e5,0};
        const auto pulse=patch.pulse(forces,256,50000);
        balance(patch);
        require(pulse.accepted_steps==256&&!pulse.work_budget_reached,"comparison did not run the same time span");
        if (preset!=MaterialPreset::Iron)
            require(pulse.state.broken_bonds>0,"declared powered traction produces no fracture in weaker solid");
        else require(pulse.state.broken_bonds==0,"comparison fractured iron at the weaker-solid traction");
        const auto damage=patch.state().damage;
        const auto alive=patch.state().alive;
        const double clock=pulse.state.time_s;
        const auto continuation=patch.pulse(forces,128,50000);
        require(continuation.accepted_steps==128&&!continuation.work_budget_reached,"comparison continuation changed duration");
        require(continuation.state.time_s>clock,"second pulse resets the clock");
        for (unsigned i=0;i<alive.size();++i) {
            require(!(!alive[i]&&patch.state().alive[i]),"second pulse healed a broken bond");
            require(patch.state().damage[i]>=damage[i],"second pulse erased damage");
        }
        balance(patch);
        const auto r=patch.report();
        SolidMatterPatch refined("terrain:0:0:0",{.25,.25,.25},.05,material,{},.1,5e-8);
        std::vector<Vec3> unloaded(125);
        refined.pulse(unloaded,128,0);
        refined.pulse(forces,512,50000);
        refined.pulse(forces,256,50000);
        balance(refined);
        const auto finer=refined.report();
        near(finer.time_s,r.time_s,1e-18,"refinement changes the physical duration");
        require(refined.components().size()==patch.components().size(),"timestep refinement changes connected component count");
        require(std::abs(finer.integration_error_j)<std::abs(r.integration_error_j),"halving timestep does not reduce integration error");
        require(std::abs(r.integration_error_j)<1e-4*r.source_work_j,"integration error is too large relative to supplied work");
        std::cout<<material.name<<": h=.05 m, dt="<<r.timestep_s<<" s, mass="<<r.mass_kg
                 <<" kg, work="<<r.source_work_j<<" J, broken="<<r.broken_bonds
                 <<", components="<<patch.components().size()<<", energy residual="<<r.energy_residual_j
                 <<" J, integration error="<<r.integration_error_j<<", removed bond energy="<<r.removed_bond_energy_j
                 <<" J, P residual="<<length(r.momentum_residual_kg_m_s)
                 <<", L residual="<<length(r.angular_residual_kg_m2_s)
                 <<", first pulse wall="<<pulse.wall_s<<" s\n";
        std::cout<<"  dt/2: broken="<<finer.broken_bonds<<", work="<<finer.source_work_j
                 <<" J, integration error="<<finer.integration_error_j<<" J\n";
    }
}
void workBudgetAndInvalidInputsAreTransactional() {
    SolidMatterPatch patch("terrain:0:0:0",{.25,.25,.25},.05,makeReferenceMaterial(MaterialPreset::Oak,17));
    std::vector<Vec3> forces(125,Vec3{0,1e5,0});
    const auto before=patch.state();const auto report=patch.report();
    const auto zero=patch.pulse(forces,64,0);
    require(zero.work_budget_reached&&zero.accepted_steps==0,"zero budget accepts powered motion");
    require(patch.state().v==before.v&&patch.state().u==before.u&&patch.state().damage==before.damage,
            "over-budget trial leaked motion or damage");
    near(patch.report().time_s,report.time_s,0,"over-budget trial advanced time");
    const auto tiny=patch.pulse(forces,64,.001);
    require(tiny.work_budget_reached&&tiny.positive_work_j<=.001,"pulse overspent positive work");
    balance(patch);
    const auto stable=patch.state();
    try {patch.pulse({},1,1);require(false,"invalid force count accepted");} catch (const std::invalid_argument &) {}
    require(stable.v==patch.state().v&&stable.alive==patch.state().alive,"invalid pulse changed state");
    try {SolidMatterPatch incompatible("bad",{.25,.25,.25},.04,makeReferenceMaterial(MaterialPreset::Glass));
         require(false,"incompatible source volume silently rounded");} catch (const std::invalid_argument &) {}
}
void nonzeroSourceReactionAndUnloading() {
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron,MaterialPreset::Concrete}) {
        const auto material=makeReferenceMaterial(preset,17);
        const Vec3 center{2,.6,-1};
        SolidMatterPatch patch("terrain:0:0:0",{.25,.25,.25},.05,material,center);
        std::vector<Vec3> forces(125,Vec3{10,20,-30});
        const auto driven=patch.pulse(forces,100,1);
        const double dt=driven.state.timestep_s;
        const Vec3 impulse=Vec3{10,20,-30}*(125*100*dt);
        near(length(driven.state.source_impulse_n_s-impulse),0,1e-13,"nonzero source impulse");
        near(length(driven.state.source_angular_impulse_kg_m2_s-cross(center,impulse)),0,1e-13,"source reaction moment about world origin");
        near(driven.state.source_work_j,dot(impulse,impulse)/(2*driven.state.mass_kg),1e-14,"whole-block source kinetic work oracle");
        balance(patch);
        require(driven.state.broken_bonds==0,"uniform translation fractures solid");
        for(auto &f:forces) f=-f;
        const auto unloading=patch.pulse(forces,50,0);
        require(unloading.accepted_steps==50&&!unloading.work_budget_reached,"negative source work requires positive budget");
        near(unloading.positive_work_j,0,0,"unloading created positive source expenditure");
        near(unloading.state.positive_source_work_j,driven.state.positive_source_work_j,0,"unloading recharged source work account");
        balance(patch);
    }
}
void boundaryAttachmentAndReaction() {
    std::vector<std::uint32_t> fixed;
    for (unsigned z=0;z<5;++z) for (unsigned x=0;x<5;++x) fixed.push_back(x+5*(5*z));
    for (const auto preset:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        const auto material=makeReferenceMaterial(preset,17);
        SolidMatterPatch patch("terrain:0:0:0",{.25,.25,.25},.05,material,{2,.6,-1},.1,1e-7,fixed);
        require(patch.components().size()==1&&patch.components()[0].attached_to_boundary,
            "whole anchored source is incorrectly transferable debris");
        const auto before=patch.state();std::vector<Vec3> forces(125);
        forces[2+5*(4+5*2)]={10000,-20000,30000};
        const auto no_work=patch.pulse(forces,1,0);
        require(no_work.accepted_steps==0&&no_work.work_budget_reached&&patch.state().u==before.u&&
            patch.state().v==before.v&&length(patch.report().boundary_impulse_n_s)==0,
            "refused anchored pulse leaked state or reaction");
        const auto loaded=patch.pulse(forces,512,100);
        balance(patch);
        require(loaded.accepted_steps==512&&length(loaded.state.boundary_impulse_n_s)>0,
            "material traction never reaches declared boundary");
        for (const auto i:fixed) {
            require(patch.state().mass[i]==before.mass[i]&&patch.state().inv_mass[i]==0,
                "anchoring erased physical source mass");
            for (unsigned axis=0;axis<3;++axis)
                require(patch.state().u[3*i+axis]==before.u[3*i+axis]&&patch.state().v[3*i+axis]==0,
                    "declared boundary moved");
        }
        const auto &r=loaded.state;
        std::cout<<"Anchored "<<material.name<<": dt="<<r.timestep_s<<" mass="<<r.mass_kg
            <<" work="<<r.source_work_j<<" support impulse="<<length(r.boundary_impulse_n_s)
            <<" support angular="<<length(r.boundary_angular_impulse_kg_m2_s)
            <<" P/L residual="<<length(r.momentum_residual_kg_m_s)<<"/"<<length(r.angular_residual_kg_m2_s)
            <<" energy residual="<<r.energy_residual_j<<" integration="<<r.integration_error_j
            <<" broken="<<r.broken_bonds<<" components="<<patch.components().size()<<" wall="<<loaded.wall_s<<'\n';
    }
    for (const auto nodes:{std::vector<std::uint32_t>{125},std::vector<std::uint32_t>{0,0}}) {
        bool refused=false;
        try {SolidMatterPatch patch("bad",{.25,.25,.25},.05,makeReferenceMaterial(MaterialPreset::Iron),{},.1,1e-7,nodes);}
        catch (const std::invalid_argument &) {refused=true;}
        require(refused,"invalid boundary declaration accepted");
    }
    // Declared high laboratory traction exercises actual disconnection. This
    // is not a calibrated hand force, ground law or prescribed shard pattern.
    SolidMatterPatch separating("terrain:0:0:0",{.25,.25,.25},.05,
        makeReferenceMaterial(MaterialPreset::Glass,17),{},.1,1e-7,fixed);
    std::vector<Vec3> pull(125);pull[2+5*(4+5*2)]={0,1e6,0};
    const auto detached=separating.pulse(pull,512,50000);
    balance(separating);bool free=false,attached=false;
    for (const auto &part:separating.components()) {
        bool touches=false;
        for (const auto &cell:part.cells)
            touches=touches||std::find(fixed.begin(),fixed.end(),cell.source_node)!=fixed.end();
        require(part.attached_to_boundary==touches,"component attachment does not follow surviving source connectivity");
        free=free||!touches;attached=attached||touches;
    }
    require(detached.state.broken_bonds>0&&free&&attached,
        "material failure did not separate free matter from retained boundary");
    std::cout<<"Anchored glass disconnection: work="<<detached.state.source_work_j
        <<" broken="<<detached.state.broken_bonds<<" components="<<separating.components().size()<<'\n';
}
}
int main() {
    try {materialsAndRetainedState();workBudgetAndInvalidInputsAreTransactional();nonzeroSourceReactionAndUnloading();boundaryAttachmentAndReaction();}
    catch (const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
    std::cout<<"constituent solid reference passed (live terrain and soil adapters remain unqualified)\n";
}
