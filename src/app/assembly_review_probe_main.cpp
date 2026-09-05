#include "creator/CodexAssistant.hpp"
#include <nlohmann/json.hpp>
#include <fstream>
#include <iostream>
#include <thread>
using namespace banjo;
int main(int argc,char **argv){try{
    if(argc!=3)throw std::invalid_argument("Usage: banjo_assembly_review_probe COMMANDS.json NEW_WORKSPACE");
    const std::filesystem::path workspace=argv[2];if(!std::filesystem::create_directories(workspace))throw std::invalid_argument("Use a fresh review workspace");
    std::ifstream input(argv[1]);const auto commands=nlohmann::json::parse(input);unsigned index=0;
    for(const auto &command:commands){if(command.value("type",std::string{})!="test_assembly")continue;
        CreatorWorld world;const auto before=world.serialize();const auto id="assembly-review-"+std::to_string(index++);
        const auto document=CodexAssistant::assemblyReviewDocument(world,id,"Explain the measured test result and whether I can build this assembly now. Keep numerical test success separate from live creation support.",command.at("assembly").dump(),command.at("test").dump());
        CodexAssistant assistant;assistant.start(workspace,id,document);std::optional<AssistantReply> reply;
        while(!(reply=assistant.poll()))std::this_thread::sleep_for(std::chrono::milliseconds(50));
        if(reply->recipe||world.serialize()!=before)throw std::runtime_error("review cannot propose live creation or change world state");
        std::cout<<id<<" "<<reply->explanation<<std::endl;
    }
    if(index==0)throw std::invalid_argument("No assembly tests found");return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<std::endl;return 1;}}
