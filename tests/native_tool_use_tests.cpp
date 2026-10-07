#include "native_tool_fixture.hpp"
#include "fastlattice/NativeToolUse.hpp"
#include <chrono>
#include <iostream>
namespace {
using namespace banjo_test;
int repeat_clearance_failures=0;
void nativeCycle(const std::string &material,const std::string &family) {
    auto f=fixture(material,family,false,.75,false,true);auto &world=*f.world;
    auto preview=world.toolUseAdmission(f.eye,f.direction(),2);std::string why;
    const double energy_before=world.mechanicalEnergyJ();
    double mass_before=0;for(const auto &part:world.poses())mass_before+=part.mass_kg;
    require(world.beginToolUse(f.eye,f.direction(),2,why,&preview),"native use start refused");
    require(world.toolUse().phase=="preparing" && world.time_s()==0,"use start advanced native time or skipped preparing");
    require(world.snapshot(why).empty() && !why.empty(),"active native action silently saved without its state");
    require(!world.beginToolUse(f.eye,f.direction(),2,why),"a repeated tap replaced an active tool action");
    bool acted=false,recovered=false;
    const auto wall_start=std::chrono::steady_clock::now();
    for(int i=0;i<1400 && world.toolUse().active;++i) {
        const auto before=world.toolUse();
        world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);
        const auto after=world.toolUse();acted=acted||after.phase=="acting";recovered=recovered||after.phase=="recovering";
        if(before.phase=="preparing" && after.phase=="preparing")
            require(world.environment()->terrain().ledger().dug.total()==0,"preparation performed unauthorized excavation");
    }
    const auto result=world.toolUse();
    const double wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-wall_start).count();
    std::cout<<"native cycle "<<material<<" "<<family<<", t="<<world.time_s()<<", wall s="<<wall
        <<", acted="<<acted<<", recovered="<<recovered<<", reason="<<result.reason
        <<", hand work J="<<result.hand_work_j<<", contact work J="<<result.contact_work_j
        <<", removal m3="<<result.loosened.total()<<", holding="<<world.hand().holding<<"\n";
    for(const auto &point:world.toolPoints())
        std::cout<<"final tip="<<point.tip_m.x<<","<<point.tip_m.y<<","<<point.tip_m.z
            <<", direction y="<<point.pointing.y<<", depth="<<point.depth_m<<"\n";
    std::cout<<"final grip speed="<<length(world.hand().grip_velocity_m_s)<<", target error="
        <<length(world.hand().target_m-world.hand().grip_m)<<"\n";
    require(!result.active,"native use failed to reach a bounded terminal state");
    require(acted && recovered,"native physical cycle did not reach contact and recovery");
    require(world.hand().holding=="handle","native physical cycle lost actual grip");
    require(world.carryingWithNativePlayer(),"native cycle failed to restore reusable carry authority");
    require(result.loosened.total()>0,"native cycle performed no useful excavation");
    double mass_after=0;for(const auto &part:world.poses())mass_after+=part.mass_kg;
    require(std::abs(mass_after-mass_before)<1e-10,"tool assembly lost or gained material during use");
    const auto debris=Json::parse(world.groundDebrisJson());
    require(!debris.at("bodies").empty(),"measured removal created no native constituent geometry");
    double volumes=0,fragment_mass=0;
    for(const auto &body:debris.at("bodies")) {
        require(body.at("work_source").get<std::string>().find("alice")!=std::string::npos,
            "native material release lost the action's work provenance");
        double cells_mass=0;
        for(const auto &cell:body.at("cells")) { volumes+=cell.at("volume_m3").get<double>();cells_mass+=cell.at("mass_kg").get<double>(); }
        require(std::abs(cells_mass-body.at("mass_kg").get<double>())<1e-8,"native fragment cells do not sum to body mass");
        fragment_mass+=cells_mass;
    }
    require(std::abs(volumes-result.loosened.total())<1e-9,"reported removal differs from released native cells");
    require(std::abs(world.environment()->terrain().residual().total())<1e-9,"terrain volume ledger failed closure");
    const auto actor=world.nativePlayers().front();
    const double unclosed=world.mechanicalEnergyJ()-energy_before-result.hand_work_j-actor.walk_work_j;
    std::cout<<"mass kg="<<mass_before<<", fragment kg="<<fragment_mass<<", raw unclosed mechanical/work J="<<unclosed<<"\n";
    const auto frozen=world.environment()->terrain().ledger().dug.total();
    for(int i=0;i<240;++i) {world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);}
    require(world.environment()->terrain().ledger().dug.total()==frozen,"idle carry excavated after the action ended");
    require(world.hand().holding=="handle","idle carry lost the recovered tool");
    const auto settled=Json::parse(world.groundDebrisJson());
    const auto collector=world.nativePlayers().front().state.center_of_mass_world_m+Vec3{0,.77,0};
    for(const auto &body:settled.at("bodies")) {
        const auto collected=Json::parse(world.collectGroundDebris(body.at("id").get<MatterBodyId>(),collector,3));
        require(collected.at("cells")==body.at("cells"),"repeat collection changed the released source cells");
    }
    require(Json::parse(world.groundDebrisJson()).at("bodies").empty(),"collection did not clear the released obstruction");
    require(std::abs(world.environment()->carriedKg()-fragment_mass)<1e-8,"repeat collection lost native material mass");
    f.target=world.toolUse().target_m;
    f.target.y=world.environment()->groundHeightAt(f.target.x,f.target.z);
    const auto repeat_preview=world.toolUseAdmission(f.eye,f.direction(),2);
    require(repeat_preview.terrain_column==preview.terrain_column,"repeat query silently switched the selected cell");
    std::cout<<"repeat target "<<f.target.x<<","<<f.target.y<<","<<f.target.z<<", hit="
        <<repeat_preview.target_m.x<<","<<repeat_preview.target_m.y<<","<<repeat_preview.target_m.z
        <<", column="<<repeat_preview.terrain_column<<"\n";
    require(world.beginToolUse(f.eye,f.direction(),2,why),"recovered tool could not start a second use");
    for(int i=0;i<1400 && world.toolUse().active;++i) {
        const auto phase=world.toolUse().phase;
        world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);
        if(world.toolUse().phase!=phase) {
            std::cout<<"repeat phase "<<phase<<" -> "<<world.toolUse().phase<<", t="<<world.time_s()<<"\n";
            for(const auto &point:world.toolPoints())std::cout<<"repeat tip="<<point.tip_m.x<<","<<point.tip_m.y<<","<<point.tip_m.z
                <<", depth="<<point.depth_m<<", pointing y="<<point.pointing.y<<"\n";
        }
    }
    std::cout<<"repeat "<<material<<" "<<family<<", phase="<<world.toolUse().phase<<", reason="<<world.toolUse().reason
        <<", holding="<<world.hand().holding<<", removal m3="<<world.toolUse().loosened.total()<<"\n";
    const auto repeated=world.toolUse();
    require(!repeated.active && world.hand().holding=="handle","repeat lost grip or failed bounded termination");
    const bool productive=repeated.reason.empty() && repeated.loosened.total()>0 && world.carryingWithNativePlayer();
    if(!productive) {
        ++repeat_clearance_failures;
        require(repeated.reason=="no_contact" || repeated.reason=="insufficient_work" || repeated.reason=="recovery_blocked",
            "repeat failed without an explicit physical boundary");
        std::cout<<"OPEN repeat clearance gate: "<<material<<" "<<family<<"\n";
    }
    const double increment=world.environment()->terrain().ledger().dug.total()-frozen;
    require(std::abs(increment-world.toolUse().loosened.total())<1e-9,"repeat credited an earlier action's material");
    std::cout<<"repeat "<<material<<" "<<family<<", removal m3="<<increment<<"\n";
}

void nativeCancellationAndStalePreview() {
    auto f=fixture("iron","pick",false,.75,false,true);auto &world=*f.world;std::string why;
    auto stale=world.toolUseAdmission(f.eye,f.direction(),2);++stale.matter_revision;
    require(!world.beginToolUse(f.eye,f.direction(),2,why,&stale) && why=="target_changed",
        "stale preview token admitted a physical action");
    require(world.time_s()==0 && world.carryingWithNativePlayer(),"stale admission mutated time or hand authority");
    require(world.beginToolUse(f.eye,f.direction(),2,why),"cancel fixture did not start");
    world.spawnNativePlayer("bob",{-1,.75,0});world.selectHand("bob");world.cancelToolUse();
    require(world.toolUse().phase=="idle","another actor inherited the first action");
    world.selectHand("alice");require(world.toolUse().active,"another actor's cancel stopped this action");
    world.cancelToolUse();
    for(int i=0;i<600 && world.toolUse().active;++i) {
        world.setNativePlayerWalk("alice",{},0,.5);world.setNativePlayerWalk("bob",{},0,.5);world.step(1.0/240);
    }
    require(!world.toolUse().active && world.toolUse().reason=="cancelled","preparation cancel did not recover explicitly");
    require(world.environment()->terrain().ledger().dug.total()==0,"cancelling before contact excavated ground");
    require(world.carryingWithNativePlayer(),"cancelled preparation left competing hand authority");
    auto dropped=fixture("iron","hoe",false,.75,false,true);
    require(dropped.world->beginToolUse(dropped.eye,dropped.direction(),2,why),"drop fixture did not start");
    dropped.world->release();
    require(!dropped.world->toolUse().active && dropped.world->toolUse().reason=="grip_released" &&
        dropped.world->hand().holding.empty(),"drop retained an active physical tool action");
}

// Declared initial geometry, not a simulated excavation claim: an isolated
// 100 mm column is already 60 mm below its neighbours. Only physical head
// width varies. Retain ordinary collision and record actual native outcomes.
void nativeDeclaredPitClearance(const std::string &material,double width) {
    auto f=fixture(material,"unfamiliar",false,.75,false,true,width);
    auto &world=*f.world;
    const auto setup=world.dig(.65,.15,.65,.15,.05,.06);
    require(setup.edit.cells.size()==1,"declared pit setup changed neighbouring columns");
    const double initial_dug=world.environment()->terrain().ledger().dug.total();
    double tool_mass=0;for(const auto &part:world.poses())tool_mass+=part.mass_kg;
    f.target={.65,world.environment()->groundHeightAt(.65,.15),.15};
    require(std::abs(f.target.y-.69)<1e-8,"declared pit does not have its specified depth");
    std::string why;
    require(world.beginToolUse(f.eye,f.direction(),2,why),"declared pit use admission refused");
    double lowest_tip=10;
    for(int i=0;i<1400 && world.toolUse().active;++i) {
        world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);
        for(const auto &point:world.toolPoints())lowest_tip=std::min(lowest_tip,point.tip_m.y);
    }
    const auto result=world.toolUse();
    require(!result.active && world.hand().holding=="handle","declared pit lost grip or failed bounded termination");
    require(std::abs(world.environment()->terrain().ledger().dug.total()-initial_dug-result.loosened.total())<1e-9,
        "declared setup material was credited as tool release");
    double retained_mass=0;for(const auto &part:world.poses())retained_mass+=part.mass_kg;
    require(std::abs(retained_mass-tool_mass)<1e-10,"declared pit changed tool material mass");
    double released_volume=0,released_mass=0;
    const auto released_debris=Json::parse(world.groundDebrisJson());
    for(const auto &body:released_debris.at("bodies")) {
        double cell_mass=0;
        for(const auto &cell:body.at("cells")) {
            released_volume+=cell.at("volume_m3").get<double>();cell_mass+=cell.at("mass_kg").get<double>();
        }
        require(std::abs(cell_mass-body.at("mass_kg").get<double>())<1e-8,"declared pit debris lost constituent mass");
        released_mass+=cell_mass;
    }
    require(std::abs(released_volume-result.loosened.total())<1e-9,"declared pit result differs from actual released cells");
    require(std::abs(world.environment()->terrain().residual().total())<1e-9,"declared pit terrain quantity ledger failed closure");
    std::cout<<"CLEARANCE_EVIDENCE "<<Json{{"material",material},{"head_width_m",width},
        {"column_width_m",.1},{"initial_pit_depth_m",.06},{"dt_s",1.0/240},
        {"scene_cell_m",.02},{"lowest_tip_m",lowest_tip},{"target_height_m",.69},
        {"tool_mass_kg",tool_mass},{"released_mass_kg",released_mass},
        {"released_m3",result.loosened.total()},{"contact_work_j",result.contact_work_j},
        {"reason",result.reason},{"elapsed_s",world.time_s()}}.dump()<<"\n";
    if(width<.1)require(result.reason.empty() && result.loosened.total()>0,
        "narrow physical head could not cut the declared narrow pit");
    else require(result.loosened.total()==0 && !result.reason.empty(),
        "wide physical head passed through untouched neighbouring terrain");
}

void nativeBuriedInterruption(const std::string &material,bool drop) {
    auto f=fixture(material,"pick",false,.75,false,true);auto &world=*f.world;std::string why;
    require(world.beginToolUse(f.eye,f.direction(),2,why),"buried interruption did not start");
    bool buried=false;
    for(int i=0;i<600 && world.toolUse().active;++i) {
        world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);
        for(const auto &point:world.toolPoints())
            buried=buried||(world.toolUse().phase=="acting" && point.depth_m>=.006 && world.toolUse().contact_work_j>.1);
        if(buried)break;
    }
    require(buried,"interruption fixture never reached a measured buried bite");
    if(drop)world.release();else world.cancelToolUse();
    for(int i=0;i<720;++i) {
        world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);
        if(!drop && !world.toolUse().active)break;
    }
    const auto result=world.toolUse();
    require(!result.active && result.reason==(drop?"grip_released":"cancelled"),"buried interruption did not finish explicitly");
    require(drop?world.hand().holding.empty():world.carryingWithNativePlayer(),"buried interruption left wrong hand authority");
    const auto debris=Json::parse(world.groundDebrisJson());double released=0;
    for(const auto &body:debris.at("bodies"))for(const auto &cell:body.at("cells"))released+=cell.at("volume_m3").get<double>();
    require(std::abs(released-result.loosened.total())<1e-9,"closing bite release missing from interrupted action");
    require(std::abs(world.environment()->terrain().ledger().dug.total()-released)<1e-9,"interruption duplicated or lost terrain volume");
    const double frozen_work=result.hand_work_j;
    for(int i=0;i<120;++i) {world.setNativePlayerWalk("alice",{},0,.5);world.step(1.0/240);}
    require(world.toolUse().hand_work_j==frozen_work,"finished interruption accumulated idle hand work");
    require(std::abs(world.environment()->terrain().ledger().dug.total()-released)<1e-9,"interrupted action continued excavating");
    std::cout<<"buried "<<(drop?"drop":"cancel")<<" "<<material<<", released m3="<<released<<"\n";
}

void controllerOracles() {
    LiveToolUseAdmission admission;admission.admitted=true;admission.tool="new-tool";admission.point=17;
    LiveToolContactPlan plan;plan.ready_grip_m={0,1,0};plan.ready_tip_m={0,.06,0};
    plan.contact.path_m={{0,1,0},{0,.86,0},{-.04,.86,0}};
    NativeToolFeedback actual;actual.connected=actual.reachable=true;actual.grip_m=plan.ready_grip_m;
    actual.tip_m={0,.3,0};actual.pointing={0,-1,0};actual.hand_work_j=5;
    NativeToolUseController controller(admission,plan,actual,0);
    const auto copied=controller;
    const auto wish=controller.wish(actual,0,1.0/240,80);
    require(!wish.cuts,"preparing wish authorized work");
    controller.accepted(actual,.01,{},"alice");
    require(controller.state().phase=="preparing","desired grip reached but wrong actual tip was admitted");
    actual.tip_m=plan.ready_tip_m;controller.accepted(actual,.02,{},"alice");
    require(controller.state().phase=="acting","actual ready frame did not admit contact");
    auto rollback=controller;
    const auto first=controller.wish(actual,.02,1.0/240,80);
    controller=rollback;
    const auto retry=controller.wish(actual,.02,1.0/240,80);
    require(length(first.grip_velocity_m_s-retry.grip_velocity_m_s)==0,"reversible retry changed the actuator wish");
    LiveGroundWork own;own.meeting_id=1;own.actor="alice";own.point=17;own.at_s=.03;own.work_j=2;own.loosened.soil_m3=.001;
    auto peer=own;peer.actor="bob";peer.work_j=100;peer.loosened.soil_m3=1;
    actual.hand_work_j=9;controller.accepted(actual,.04,{own,peer},"alice");
    require(controller.state().contact_work_j==2 && controller.state().hand_work_j==4 &&
        controller.state().loosened.soil_m3==.001,"action credited another actor's measured contact");
    controller.cancel(.04);
    require(!controller.wish(actual,.04,1.0/240,80).cuts && controller.state().phase=="recovering",
        "cancel retained cutting authority");
    require(controller.state().loosened.soil_m3==.001,"cancel erased material already released");
    controller=copied;actual.target_matches=false;
    require(!controller.wish(actual,0,1.0/240,80).cuts && controller.state().reason=="target_changed",
        "stale target authorized a cut");
    actual.connected=false;actual.grip_present=false;(void)controller.wish(actual,0,1.0/240,80);
    require(!controller.state().active && controller.state().reason=="grip_released","lost grip remained an active use");
    controller=copied;actual.grip_present=true;
    (void)controller.wish(actual,0,1.0/240,80);
    require(controller.state().reason=="capability_changed","disconnected point was reported as a released hand");
    controller=copied;actual.connected=true;actual.target_matches=true;
    own.open=true;controller.accepted(actual,.04,{own},"alice");controller.interrupt(.05,"grip_released");
    const auto frozen_work=controller.state().hand_work_j;
    own.open=false;own.loosened.soil_m3=.002;auto later=own;later.meeting_id=2;later.at_s=.05;later.loosened.soil_m3=1;
    actual.hand_work_j=100;controller.accepted(actual,.06,{own,later,peer},"alice");
    require(controller.state().loosened.soil_m3==.002 && controller.state().hand_work_j==frozen_work &&
        controller.state().ended_s==.05,"terminal refresh erased a closing bite or credited later work");
    controller.accepted(actual,.07,{},"alice");
    require(controller.state().loosened.soil_m3==.002,"clearing closed native reports erased the final action outcome");
    controller=copied;controller.accepted(actual,.04,{own},"alice");controller.cancel(.04);
    controller.accepted(actual,.045,{},"alice");
    require(controller.state().loosened.soil_m3==.002 && controller.state().contact_work_j==2,
        "a runner reply cleared measured work while recovery was still active");
    controller.accepted(actual,.046,{own},"alice");
    require(controller.state().loosened.soil_m3==.002 && controller.state().contact_work_j==2,
        "repeated observation of one meeting duplicated measured work");
}
}
int main(int argc,char **argv) {
    try {
        controllerOracles();nativeCancellationAndStalePreview();
        for(const auto &material:{"glass","oak","iron"}) {
            nativeBuriedInterruption(material,false);nativeBuriedInterruption(material,true);
            nativeDeclaredPitClearance(material,.04);nativeDeclaredPitClearance(material,.28);
        }
        for(const auto &material:{"glass","oak","iron"})
            for(const auto &family:{"pick","shovel","hoe","unfamiliar"})nativeCycle(material,family);
        if(argc==2 && std::string(argv[1])=="--require-repeat-yield" && repeat_clearance_failures>0) {
            std::cerr<<"repeat gameplay acceptance remains open: "<<repeat_clearance_failures<<" fixtures\n";return 1;
        }
        std::cout<<"native tool use scoped checks passed; repeat clearance gates open="<<repeat_clearance_failures<<"\n";return 0;
    } catch(const std::exception &error) {std::cerr<<error.what()<<"\n";return 1;}
}
