# Builds that leave the floating-point model in each way a check can miss,
# beside one that keeps it. tests/fp_model_audit_tests.py configures this
# project and requires scripts/check-fp-model.py to name exactly the broken
# files, in exactly the configurations that break them: the reviewer's five
# escapes from 85b19ca's guard (no build type, SHELL:, a source chosen by a
# generator expression, a fast option reaching one configuration through a
# link, a safe option in Debug only), a file with an option of its own, and a
# file that asks for fast math in a pragma.
cmake_minimum_required(VERSION 3.25)
project(fp_model_audit_fixture LANGUAGES CXX)

include("${CMAKE_CURRENT_LIST_DIR}/../../cmake/FloatingPointModel.cmake")

if(MSVC)
    set(fast /fp:fast)
    set(unsafe /fp:fast)
    set(safe /fp:precise)
else()
    set(fast -ffast-math)
    set(unsafe -ffp-contract=fast)
    set(safe -ffp-contract=off)
endif()

# The model alone, as every engine target is built.
add_library(keeps_the_model STATIC keeps_the_model.cpp)

# A fast option on a target.
add_library(plain_fast STATIC plain_fast.cpp)
target_compile_options(plain_fast PRIVATE ${fast})

# The same, spelled SHELL:, which CMake expands and a property reader does not.
add_library(shell_fast STATIC shell_fast.cpp)
target_compile_options(shell_fast PRIVATE "SHELL:${fast}")

# A source the target gets through a generator expression. Written into the
# build so that it is only ever compiled here.
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/genex_source.cpp"
     "double genex_source(double a, double b, double c) { return a * b + c; }\n")
add_library(genex_source STATIC)
target_sources(genex_source PRIVATE "$<$<BOOL:1>:${CMAKE_CURRENT_BINARY_DIR}/genex_source.cpp>")
target_compile_options(genex_source PRIVATE ${fast})

# A fast option that reaches Release, and only Release, through what it links.
add_library(fast_usage INTERFACE)
target_compile_options(fast_usage INTERFACE ${fast})
add_library(release_usage STATIC release_usage.cpp)
target_link_libraries(release_usage PRIVATE "$<$<CONFIG:Release>:fast_usage>")

# Unsafe everywhere, with a safe option in Debug only. A reader of properties
# took the Debug-only option as rescuing every configuration; in fact it
# rescues none. It repeats the model's own option, and CMake drops a repeated
# option, keeping the first, so even Debug's command ends on the unsafe one.
add_library(debug_only_safe STATIC debug_only_safe.cpp)
target_compile_options(debug_only_safe PRIVATE ${unsafe} "$<$<CONFIG:Debug>:${safe}>")

# One file of a target with an option of its own; the other file keeps the model.
add_library(one_fast_file STATIC fast_file.cpp model_file.cpp)
set_source_files_properties(fast_file.cpp PROPERTIES COMPILE_OPTIONS "${fast}")

# No option at all, but the source asks for fast math itself.
add_library(fast_pragma STATIC fast_pragma.cpp)
