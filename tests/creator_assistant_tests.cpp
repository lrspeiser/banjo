#include "creator/CodexAssistant.hpp"
#include <nlohmann/json.hpp>
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
    std::cout<<"[PASS] proposal/clarification, stale identity, duplicate fields and read-only request\n";
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
        protocol();
        if(ChildProcess::supported()) {
            const auto suffix=std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
            const auto root=std::filesystem::current_path()/("assistant-test-"+suffix);std::filesystem::create_directory(root);
            processTests(std::filesystem::absolute(argv[0]),root);
        }else std::cout<<"[SKIP] native Codex process adapter is Windows-only at this checkpoint\n";
        return 0;
    }catch(const std::exception &e){std::cerr<<"[FAIL] "<<e.what()<<'\n';return 1;}
}
