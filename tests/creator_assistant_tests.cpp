#include "creator/CodexAssistant.hpp"
#include <nlohmann/json.hpp>
#include <cmath>
#include <fstream>
#include <iostream>
#include <thread>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace {
using namespace banjo;
using Json=nlohmann::json;
void require(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
template<class F> void rejects(F action){bool rejected=false;try{action();}catch(const std::exception&){rejected=true;}require(rejected,"Expected rejection");}
std::string read(const std::filesystem::path &path){std::ifstream in(path,std::ios::binary);return {std::istreambuf_iterator<char>(in),{}};}
void write(const std::filesystem::path &path,std::string_view text){std::ofstream out(path,std::ios::binary);out<<text;require(bool(out),"Fixture write failed");}
Json reply(std::string id) {return {{"reply_version",1},{"request_id",id},{"status","proposal"},{"explanation","An intact oak ball, with cost checked by the compiler."},{"recipe",Json::parse(CreatorWorld::recipeJson({}))}};}
AssistantReply wait(CodexAssistant &assistant) {
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    while(std::chrono::steady_clock::now()<deadline) {
        if(auto result=assistant.poll())return *result;
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    throw std::runtime_error("Assistant fixture did not finish in five seconds");
}
int fixture(int argc,char **argv) {
    if(std::string(argv[1])=="--argument-fixture") {
        Json args=Json::array();for(int i=2;i<argc;++i)args.push_back(argv[i]);std::cout<<args.dump();return 0;
    }
    // Deterministic provider fixture; never used as evidence of an LLM call.
    require(std::string(argv[1])=="exec","Unexpected fixture invocation");
    const auto request=Json::parse(read("request.json"));const auto id=request["request_id"].get<std::string>();
    require(read("input.txt").find("do not call tools")!=std::string::npos,"Missing bounded design instruction");
    Json result=reply(id);
    if(id=="hold") {
#ifdef _WIN32
        std::cout<<GetCurrentProcessId()<<'\n'<<std::flush;
#endif
        std::this_thread::sleep_for(std::chrono::seconds(30));
    }
    if(id=="failure")return 7;
    if(id=="oversized") {std::cout<<std::string(1024*1024+1,'x')<<std::flush;return 0;}
    if(id=="wrong-id")result["request_id"]="stale";
    if(id=="clarify"){result["status"]="clarification";result["recipe"]=nullptr;result["explanation"]="Hinges are not supported yet. Try an intact ball.";}
    write("response.json",result.dump());return 0;
}
void protocol() {
    auto j=reply("a");auto r=CodexAssistant::parseReply(j.dump(),"a");require(r.recipe&&r.recipe->material==MaterialPreset::Oak,"Proposal decoded");
    rejects([&]{(void)CodexAssistant::parseReply(j.dump(),"b");});
    j["status"]="clarification";rejects([&]{(void)CodexAssistant::parseReply(j.dump(),"a");});
    j["recipe"]=nullptr;require(!CodexAssistant::parseReply(j.dump(),"a").recipe,"Clarification has no object");
    j["mint_mass_kg"]=100;rejects([&]{(void)CodexAssistant::parseReply(j.dump(),"a");});
    rejects([&]{(void)CodexAssistant::parseReply("{\"request_id\":\"a\",\"request_id\":\"a\"}","a");});
    require(Json::parse(CodexAssistant::responseSchema())["additionalProperties"]==false,"Output schema rejects extra fields");
    ObjectRecipe box;box.schema_version=2;box.shape="box";box.dimensions_m={.08,.06,.1};
    j=reply("box");j["recipe"]=Json::parse(CreatorWorld::recipeJson(box));
    const auto parsed_box=CodexAssistant::parseReply(j.dump(),"box");
    require(parsed_box.recipe&&parsed_box.recipe->shape=="box"&&parsed_box.recipe->dimensions_m.z==.1,"Assistant carries full box dimensions through shared parser");
    j["recipe"]["placement"]["orientation_wxyz"]={2,0,0,0};
    rejects([&]{(void)CodexAssistant::parseReply(j.dump(),"box");});
    CreatorWorld world;const auto before=world.serialize();
    const auto request=Json::parse(CodexAssistant::requestDocument(world,"a","Make an oak ball.",{}));
    require(request["world"]["inventory"].empty()&&world.serialize()==before,"Request cannot collect or spend resources");
    require(request["world"]["capabilities"]["energy"]["fabrication_supported"]==false,"Assistant sees that energy-limited fabrication is unavailable");
    require(request["current_design_assessment"]["status"]=="needs_resources"&&request["current_design_assessment"]["material_requirements"][0]["inventory_mass_kg"]==0,"Assistant sees compiler-checked shortfall with no automatic collection");
    ObjectRecipe outside;outside.tangent_m=8;
    const auto invalid=Json::parse(CodexAssistant::requestDocument(world,"fix","Help fix this placement.",outside));
    require(invalid["current_design_assessment"]["status"]=="invalid_or_unsupported"&&world.serialize()==before,"invalid draft can be explained without bypassing validation");
    std::cout<<"[PASS] proposal/clarification, stale identity, duplicate fields and read-only request\n";
}
void selectedRevisionContext() {
    for(auto material:{MaterialPreset::Glass,MaterialPreset::Oak,MaterialPreset::Iron}) {
        CreatorWorld world;world.collect(std::string(materialPresetName(material))+"-pile");
        ObjectRecipe original;original.material=material;
        original.radius_m=std::cbrt(9.9/(makeReferenceMaterial(material).density_kg_m3*(4.0/3)*std::acos(-1)));
        const auto id=world.create("initial",original);world.step(120);const auto before=world.serialize();
        const auto request=Json::parse(CodexAssistant::requestDocument(world,"edit","Rebuild the selected object as a smaller block.",original,{},RevisionTarget{id,1}));
        require(!request["world"].contains("history")&&request["world"]["history_count"]==1,"Provider context omits receipt payload but retains count");
        require(request["editing"]["object_id"]==id&&request["editing"]["expected_revision"]==1,"Edit context binds the selected identity and authoring revision");
        const auto &available=request["editing"]["available_after_recovery"];
        require(available.size()==1&&available[0]["material"].get<std::string>()==materialPresetName(material),"Recovery cannot include an uncollected substance");
        require(std::abs(available[0]["mass_kg"].get<double>()-10)<1e-12&&std::abs(request["editing"]["recoverable_mass_kg"].get<double>()-9.9)<1e-12,"Selected recovery plus free stock is counted exactly once");
        require(std::abs(request["world"]["inventory"][0]["mass_kg"].get<double>()-.1)<1e-12,"Free stock remains distinct from recoverable matter");
        require(world.serialize()==before,"Editing context cannot reclaim or reset a moving object");
        rejects([&]{(void)CodexAssistant::requestDocument(world,"stale","Rebuild it.",original,{},RevisionTarget{id,0});});
        rejects([&]{(void)CodexAssistant::requestDocument(world,"missing","Rebuild it.",original,{},RevisionTarget{id+1,1});});
        ObjectRecipe box=original;box.schema_version=2;box.shape="box";box.dimensions_m={.08,.06,.1};
        box.tangent_m=2;
        const auto short_request=Json::parse(CodexAssistant::requestDocument(world,"short","Make this block and keep my sphere.",box));
        require(short_request["editing"].is_null()&&short_request["current_design_assessment"]["status"]=="needs_resources","new-design context does not reclaim existing material");
        const auto edit_request=Json::parse(CodexAssistant::requestDocument(world,"edit","Use the selected sphere to make this block.",box,{},RevisionTarget{id,1}));
        require(edit_request["current_design_assessment"]["status"]=="buildable"&&world.serialize()==before,"selected-revision requirements are read-only and include recovery");
        auto response=reply("edit");response["recipe"]=Json::parse(CreatorWorld::recipeJson(box));
        const auto proposal=CodexAssistant::parseReply(response.dump(),"edit");
        rejects([&]{(void)world.preview(*proposal.recipe);}); // Replacement requires the selected material credit.
        const auto preview=world.previewRebuild({id,1},*proposal.recipe);require(preview.creation.mass_kg>.1,"Recovery is necessary for every reference material");
        (void)world.rebuild("edit",{id,1},*proposal.recipe);
        rejects([&]{(void)CodexAssistant::requestDocument(world,"outdated","Change it again.",box,{},RevisionTarget{id,1});});
        const auto revised=Json::parse(CodexAssistant::requestDocument(world,"again","Change it again.",box,{},RevisionTarget{id,2}));
        require(revised["editing"]["expected_revision"]==2,"Follow-up binds the current version");
        world.reclaim("remove",{id,2});
        rejects([&]{(void)CodexAssistant::requestDocument(world,"gone","Rebuild it.",box,{},RevisionTarget{id,2});});
        require(Json::parse(CodexAssistant::requestDocument(world,"new","Make a new ball.",{}))["editing"].is_null(),"New creation has no implicit edit target");
    }
    std::cout<<"[PASS] glass/oak/iron selected revision context, resource recovery and stale/reclaimed targets\n";
}
void processTests(const std::filesystem::path &exe,const std::filesystem::path &root) {
    CreatorWorld world;world.collect("oak-pile");const auto before=world.serialize();
    CodexAssistant assistant(exe);
    const auto start=[&](const char *id){assistant.start(root,id,CodexAssistant::requestDocument(world,id,"Create a ball.",{}));};
    start("good");auto result=wait(assistant);require(result.recipe&&world.serialize()==before,"Provider cannot mutate inventory/world");
    const auto preview=world.preview(*result.recipe);require(preview.mass_kg>0,"Proposal uses independent object compiler");
    start("clarify");require(!wait(assistant).recipe&&world.serialize()==before,"Clarification leaves all material untouched");
    start("wrong-id");rejects([&]{(void)wait(assistant);});require(!assistant.running(),"Invalid response releases process ownership");
    start("failure");rejects([&]{(void)wait(assistant);});require(!assistant.running(),"Failed process releases request for retry");
    start("oversized");rejects([&]{(void)wait(assistant);});require(!assistant.running()&&world.serialize()==before,"Oversized provider output rejects without changing the world");
    start("hold");require(!assistant.poll(),"Live process polling does not wait for completion");
#ifdef _WIN32
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(3);unsigned long pid=0;
    while(std::chrono::steady_clock::now()<deadline) {
        auto data=read(assistant.requestDirectory()/"events.jsonl");if(!data.empty()){pid=std::stoul(data);break;}
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    require(pid!=0,"Live fixture process announced its ID");
    HANDLE observed_process=OpenProcess(SYNCHRONIZE,FALSE,pid);require(observed_process!=nullptr,"Can observe the owned live process");
    assistant.cancel();const auto state=WaitForSingleObject(observed_process,2000);CloseHandle(observed_process);
    require(state==WAIT_OBJECT_0,"Cancel terminates the actual owned process");
#else
    assistant.cancel();
#endif
    require(!assistant.running()&&!assistant.poll()&&world.serialize()==before,"Cancel cannot publish a response or debit material");
    start("retry");require(wait(assistant).recipe.has_value(),"A cancelled/failed request can be followed by a new request");
    auto review=Json::parse(CodexAssistant::requestDocument(world,"review-proposal","Review only.",{}));review["application"]="assembly_review";
    assistant.start(root,"review-proposal",review.dump());rejects([&]{(void)wait(assistant);});require(world.serialize()==before&&!assistant.running(),"review-only provider cannot return an executable recipe");
    rejects([&]{start("../escape");});
    rejects([&]{start("retry");});
    std::cout<<"[PASS] background completion, clarification, failure, cancellation, stale response and retry\n";

    const auto args_dir=root/"argument path with spaces";std::filesystem::create_directory(args_dir);write(args_dir/"input.txt","");
    ChildProcess process;const std::vector<std::string> values{"two words","quote\"inside","trailing\\","C:\\space path\\","$(not a command); & literal",""};
    auto args=values;args.insert(args.begin(),"--argument-fixture");
    process.start(exe,args,args_dir,args_dir/"input.txt",args_dir/"out.json",args_dir/"err.txt");
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(3);std::optional<unsigned> exit;
    while(std::chrono::steady_clock::now()<until&&!(exit=process.poll()))std::this_thread::sleep_for(std::chrono::milliseconds(10));
    require(exit&&*exit==0,"Argument fixture exited successfully");process.cancel();
    require(Json::parse(read(args_dir/"out.json"))==Json(values),"No-shell arguments preserve whitespace, quotes, slashes, metacharacters and empty strings");
    std::cout<<"[PASS] native process argument/handle boundary\n";
}
}
int main(int argc,char **argv) {
    try {
        if(argc>1)return fixture(argc,argv);
        protocol();selectedRevisionContext();
        if(ChildProcess::supported()) {
            const auto suffix=std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
            const auto root=std::filesystem::current_path()/("assistant-test-"+suffix);std::filesystem::create_directory(root);
            processTests(std::filesystem::absolute(argv[0]),root);
        }else std::cout<<"[SKIP] native Codex process adapter is Windows-only at this checkpoint\n";
        return 0;
    }catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}
}
