#include "creator/CodexAssistant.hpp"
#include <fstream>
#include <iostream>
#include <thread>

int main(int argc,char **argv) {
    try {
        std::filesystem::path world_path,prompt_path,workspace,executable=banjo::ChildProcess::findExecutable("codex");
        std::string id;bool apply=false;
        for(int i=1;i<argc;++i) {
            const std::string option=argv[i];if(option=="--apply"){apply=true;continue;}
            if(++i>=argc)throw std::invalid_argument("missing option value");
            if(option=="--world")world_path=argv[i];else if(option=="--prompt-file")prompt_path=argv[i];
            else if(option=="--workspace")workspace=argv[i];else if(option=="--request-id")id=argv[i];
            else if(option=="--assistant-exe")executable=std::filesystem::absolute(argv[i]);else throw std::invalid_argument("unknown option");
        }
        if(world_path.empty()||prompt_path.empty()||workspace.empty()||id.empty())throw std::invalid_argument("Required: --world FILE --prompt-file FILE --workspace DIR --request-id ID [--apply]");
        if(std::filesystem::file_size(prompt_path)>500)throw std::invalid_argument("prompt exceeds 500 bytes");
        std::ifstream input(prompt_path,std::ios::binary);if(!input)throw std::runtime_error("cannot read prompt");
        const std::string prompt{std::istreambuf_iterator<char>(input),{}};
        auto world=banjo::CreatorWorld::load(world_path);const auto before=world.serialize();
        std::filesystem::create_directories(workspace);banjo::CodexAssistant assistant(executable);
        assistant.start(workspace,id,banjo::CodexAssistant::requestDocument(world,id,prompt,{}));
        std::cout<<"Assistant running; no world changes until a validated proposal is explicitly applied.\n"<<std::flush;
        while(true) {
            if(auto reply=assistant.poll()) {
                std::cout<<reply->explanation<<'\n';
                if(reply->recipe) {
                    const auto plan=world.preview(*reply->recipe);std::cout<<"Validated material cost: "<<plan.mass_kg<<" kg\n";
                    if(apply) {
                        (void)world.create(id,*reply->recipe);world.step(240);world.save(workspace/(id+"-world.json"));
                        std::ofstream result(workspace/(id+"-inspect.json"));result<<world.inspectJson();
                        if(!result)throw std::runtime_error("cannot save inspection");
                    }
                }else std::cout<<"Clarification only; no object created.\n";
                if((!apply||!reply->recipe)&&before!=world.serialize())throw std::logic_error("Proposal changed world before acceptance");
                return 0;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    }catch(const std::exception &e){std::cerr<<"Assistant probe error: "<<e.what()<<'\n';return 1;}
}
