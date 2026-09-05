#pragma once
#include "creator/CreatorWorld.hpp"
#include "platform/ChildProcess.hpp"
#include <chrono>

namespace banjo {
struct AssistantReply {
    std::string request_id,explanation;
    std::optional<ObjectRecipe> recipe;
};
// A provider adapter only returns a proposal/clarification. It never receives
// a mutable CreatorWorld or authority to create, debit, step or load a world.
class CodexAssistant {
public:
    explicit CodexAssistant(std::filesystem::path executable = ChildProcess::findExecutable("codex"));
    [[nodiscard]] bool available() const;
    [[nodiscard]] bool running() const {return running_;}
    [[nodiscard]] const std::filesystem::path &requestDirectory() const {return directory_;}
    void start(const std::filesystem::path &workspace,std::string request_id,std::string request_document);
    [[nodiscard]] std::optional<AssistantReply> poll();
    void cancel() noexcept;
    [[nodiscard]] static std::string responseSchema();
    [[nodiscard]] static std::string requestDocument(const CreatorWorld &world,std::string_view request_id,
        std::string_view prompt,const ObjectRecipe &draft,std::string_view previous_explanation={},std::optional<RevisionTarget> editing={});
    [[nodiscard]] static AssistantReply parseReply(std::string_view document,std::string_view expected_id);
private:
    ChildProcess process_;
    std::filesystem::path executable_,directory_;
    std::string request_id_;
    std::chrono::steady_clock::time_point started_;
    bool running_{};
};
}
