#include "platform/ChildProcess.hpp"
#include <stdexcept>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#endif

namespace banjo {
#ifdef _WIN32
namespace {
struct Handle {
    HANDLE value{};
    ~Handle(){if(value&&value!=INVALID_HANDLE_VALUE)CloseHandle(value);}
    Handle()=default;
    explicit Handle(HANDLE v):value(v){}
    Handle(const Handle&)=delete;
    Handle &operator=(const Handle&)=delete;
};
void check(bool ok,const char *message) {if(!ok)throw std::runtime_error(std::string(message)+" (Windows error "+std::to_string(GetLastError())+")");}
std::wstring wide(const std::string &text) {
    if(text.empty())return {};
    const int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),nullptr,0);
    check(count>0,"Invalid UTF-8 argument");std::wstring result(static_cast<std::size_t>(count),L'\0');
    check(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text.data(),static_cast<int>(text.size()),result.data(),count)==count,"Cannot encode argument");return result;
}
// Windows CommandLineToArgvW/MSVC rules: backslashes before a quote or the
// closing quote are doubled. Metacharacters never pass through cmd/PowerShell.
std::wstring quote(const std::wstring &text) {
    std::wstring result=L"\"";std::size_t slashes=0;
    for(wchar_t c:text) {
        if(c==L'\\'){++slashes;continue;}
        result.append(slashes*(c==L'\"'?2:1),L'\\');slashes=0;
        if(c==L'\"')result+=L'\\';result+=c;
    }
    result.append(slashes*2,L'\\');return result+L'\"';
}
}
class ChildProcess::Impl {public:Handle process,job;};
bool ChildProcess::supported(){return true;}
std::filesystem::path ChildProcess::findExecutable(const std::string &name) {
    const auto input=wide(name);std::wstring result(32768,L'\0');
    const DWORD count=SearchPathW(nullptr,input.c_str(),L".exe",static_cast<DWORD>(result.size()),result.data(),nullptr);
    if(count==0||count>=result.size())return {};result.resize(count);return result;
}
void ChildProcess::start(const std::filesystem::path &executable,const std::vector<std::string> &arguments,
                         const std::filesystem::path &directory,const std::filesystem::path &input,
                         const std::filesystem::path &output,const std::filesystem::path &error) {
    if(impl_)throw std::logic_error("A child process is already owned");
    auto next=std::make_unique<Impl>();
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES),nullptr,TRUE};
    Handle in(CreateFileW(input.c_str(),GENERIC_READ,FILE_SHARE_READ,&attributes,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr));
    Handle out(CreateFileW(output.c_str(),GENERIC_WRITE,FILE_SHARE_READ,&attributes,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
    Handle err(CreateFileW(error.c_str(),GENERIC_WRITE,FILE_SHARE_READ,&attributes,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
    check(in.value!=INVALID_HANDLE_VALUE&&out.value!=INVALID_HANDLE_VALUE&&err.value!=INVALID_HANDLE_VALUE,"Cannot open child process streams");
    next->job.value=CreateJobObjectW(nullptr,nullptr);check(next->job.value!=nullptr,"Cannot create child job");
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    check(SetInformationJobObject(next->job.value,JobObjectExtendedLimitInformation,&limits,sizeof(limits))!=0,"Cannot set child job lifetime");
    STARTUPINFOEXW startup{};startup.StartupInfo.cb=sizeof(startup);startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput=in.value;startup.StartupInfo.hStdOutput=out.value;startup.StartupInfo.hStdError=err.value;
    SIZE_T size=0;InitializeProcThreadAttributeList(nullptr,1,0,&size);
    std::vector<unsigned char> buffer(size);startup.lpAttributeList=reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(buffer.data());
    check(InitializeProcThreadAttributeList(startup.lpAttributeList,1,0,&size)!=0,"Cannot initialize child handle list");
    struct AttributeCleanup {LPPROC_THREAD_ATTRIBUTE_LIST value;~AttributeCleanup(){DeleteProcThreadAttributeList(value);}} cleanup{startup.lpAttributeList};
    HANDLE handles[]{in.value,out.value,err.value};
    check(UpdateProcThreadAttribute(startup.lpAttributeList,0,PROC_THREAD_ATTRIBUTE_HANDLE_LIST,handles,sizeof(handles),nullptr,nullptr)!=0,"Cannot restrict child handles");
    std::wstring command=quote(executable.wstring());for(const auto &arg:arguments)command+=L" "+quote(wide(arg));
    PROCESS_INFORMATION info{};
    check(CreateProcessW(executable.c_str(),command.data(),nullptr,nullptr,TRUE,CREATE_NO_WINDOW|CREATE_SUSPENDED|EXTENDED_STARTUPINFO_PRESENT,
                         nullptr,directory.c_str(),&startup.StartupInfo,&info)!=0,"Cannot launch assistant executable");
    next->process.value=info.hProcess;Handle thread(info.hThread);
    if(!AssignProcessToJobObject(next->job.value,next->process.value)) {
        const auto error_code=GetLastError();TerminateProcess(next->process.value,1);SetLastError(error_code);check(false,"Cannot contain assistant process tree");
    }
    check(ResumeThread(thread.value)!=static_cast<DWORD>(-1),"Cannot resume assistant process");impl_=std::move(next);
}
std::optional<unsigned> ChildProcess::poll() const {
    if(!impl_)throw std::logic_error("No child process is owned");
    const DWORD state=WaitForSingleObject(impl_->process.value,0);
    if(state==WAIT_TIMEOUT)return std::nullopt;check(state==WAIT_OBJECT_0,"Cannot poll child process");
    DWORD exit=0;check(GetExitCodeProcess(impl_->process.value,&exit)!=0,"Cannot read child exit code");return static_cast<unsigned>(exit);
}
void ChildProcess::cancel() noexcept {impl_.reset();}
#else
class ChildProcess::Impl {};
bool ChildProcess::supported(){return false;}
std::filesystem::path ChildProcess::findExecutable(const std::string &){return {};}
void ChildProcess::start(const std::filesystem::path &,const std::vector<std::string> &,const std::filesystem::path &,
                         const std::filesystem::path &,const std::filesystem::path &,const std::filesystem::path &) {
    throw std::runtime_error("Automatic Codex process integration currently requires Windows; use the manual proposal bridge");
}
std::optional<unsigned> ChildProcess::poll() const {throw std::logic_error("No supported child process");}
void ChildProcess::cancel() noexcept {impl_.reset();}
#endif
ChildProcess::ChildProcess()=default;
ChildProcess::~ChildProcess(){cancel();}
}
