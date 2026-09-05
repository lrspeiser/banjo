#pragma once
#include <filesystem>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace banjo {
// One owned background process tree. No shell command strings are evaluated.
// Destruction/cancellation terminates only this tree. Poll never waits for exit.
class ChildProcess {
public:
    ChildProcess();
    ~ChildProcess();
    ChildProcess(const ChildProcess &) = delete;
    ChildProcess &operator=(const ChildProcess &) = delete;
    static std::filesystem::path findExecutable(const std::string &name);
    static bool supported();
    void start(const std::filesystem::path &executable,const std::vector<std::string> &arguments,
               const std::filesystem::path &directory,const std::filesystem::path &input,
               const std::filesystem::path &output,const std::filesystem::path &error);
    [[nodiscard]] std::optional<unsigned> poll() const;
    void cancel() noexcept;
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
}
