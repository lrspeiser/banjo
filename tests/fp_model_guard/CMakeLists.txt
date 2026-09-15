# A build that breaks the floating-point model twice -- a target given fast
# math of its own, and one file given it alone -- and must not configure.
# banjo_fp_model_guard_refuses (CMakeLists.txt) runs it and expects the
# refusal, naming those two files and nothing else. It needs no compiler: the
# check stops the configure before anything is generated.
cmake_minimum_required(VERSION 3.25)
project(fp_model_guard LANGUAGES NONE)

include("${CMAKE_CURRENT_LIST_DIR}/../../cmake/FloatingPointModel.cmake")

if(BANJO_FP_MODEL_FAMILY STREQUAL "MSVC")
    set(fast /fp:fast)
else()
    set(fast -ffp-contract=fast)
endif()

# The model alone, as everything in the engine is built: nothing to say.
add_library(keeps_the_model STATIC keeps_the_model.cpp)
# A target that asks for its own: refused.
add_library(fast_target STATIC fast_target.cpp)
target_compile_options(fast_target PRIVATE ${fast})
# One file of a target that asks for its own: refused, and only that file.
add_library(one_fast_file STATIC fast_file.cpp model_file.cpp)
set_source_files_properties(fast_file.cpp PROPERTIES COMPILE_OPTIONS ${fast})
