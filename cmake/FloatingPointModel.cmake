# One floating-point model for everything compiled into the engine.
#
# An inline function -- a Jolt constraint part or vector operator, a helper in
# one of our own headers, a std:: template -- is compiled into every object
# file that uses it, and wherever the compiler does not inline it the linker
# keeps ONE copy, the first it meets. When two objects are compiled under
# different floating-point rules, which copy runs, and so what the arithmetic
# gives, depends on link order. Adding rigid/DrumRope.cpp once moved
# banjo_blade_tests' cut from 4.676 J to 4.192 J that way, and on 9317a5b
# Jolt's own solver ran JoltWorld.cpp's copy of
# MotionProperties::GetInverseInertiaForRotation while our tetrahedron contact
# ran Jolt's /fp:fast GJK and EPA (docs/floating-point-model.md).
#
# So every C++ object in the build compiles to one profile, banjo-cpu-precise-v1:
# IEEE arithmetic in the order the source writes it, no fused multiply-add the
# source did not ask for, no reassociation, special values kept.
#
#   MSVC's cl         /fp:precise, never /fp:fast, /fp:strict or /fp:contract
#   GCC, and Clang    -fno-fast-math -ffp-contract=off, and nothing else from
#   with its own      fast math
#   front end
#   anything else     no profile: refused rather than guessed at
#
# The options go on this directory before Jolt is added, so on Jolt's command
# lines they come after Jolt's own /fp:fast (-ffp-contract=fast) and win.
# Explicit fused multiply-adds -- std::fma, Jolt's FMA intrinsics under
# JPH_USE_FMADD -- are instructions the source asked for, the same in every
# object, and stay.
#
# Nothing here predicts what CMake will generate. The build has a target,
# banjo_fp_model_audit, that every compiled target waits for. It reads what
# CMake did generate -- its File API reply, the Ninja or Makefile commands or
# the Visual Studio projects, and the environment the build runs in -- with
# scripts/check-fp-model.py, and stops the build, naming each file, if any C++
# file would compile outside the profile. Include this before the first target.

include_guard(GLOBAL)

set(BANJO_FP_PROFILE "banjo-cpu-precise-v1")
set(_banjo_fp_auditor "${CMAKE_CURRENT_LIST_DIR}/../scripts/check-fp-model.py")

if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
    set(BANJO_FP_FAMILY msvc)
    set(BANJO_FP_OPTIONS "/fp:precise")
elseif(CMAKE_CXX_COMPILER_ID MATCHES "^(GNU|Clang|AppleClang)$"
       AND NOT CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "MSVC")
    set(BANJO_FP_FAMILY gnu)
    # Fast math off first, then contraction: -fno-fast-math puts back what
    # fast math changed, and the last -ffp-contract is the one that counts.
    set(BANJO_FP_OPTIONS "-fno-fast-math;-ffp-contract=off")
else()
    message(FATAL_ERROR
        "Floating-point model: there is no validated profile for the C++ compiler "
        "${CMAKE_CXX_COMPILER_ID} with the ${CMAKE_CXX_COMPILER_FRONTEND_VARIANT} front end. "
        "cmake/FloatingPointModel.cmake has profiles for MSVC's cl and for GCC and Clang "
        "with their own front end. Add one here, with its rules in scripts/check-fp-model.py, "
        "before building with this compiler.")
endif()
foreach(option IN LISTS BANJO_FP_OPTIONS)
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:${option}>)
endforeach()
# A Ninja or Makefile build's own commands, which the audit reads beside
# CMake's account of them. Visual Studio ignores it; its projects are read.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# What the audit needs besides CMake's own account: which profile, for which
# compiler, under which generator.
get_property(_banjo_fp_multi GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
if(_banjo_fp_multi)
    set(_banjo_fp_multi true)
else()
    set(_banjo_fp_multi false)
endif()
string(JOIN "\", \"" _banjo_fp_options_json ${BANJO_FP_OPTIONS})
file(WRITE "${CMAKE_BINARY_DIR}/banjo-fp-profile.json"
"{
  \"profile\": \"${BANJO_FP_PROFILE}\",
  \"family\": \"${BANJO_FP_FAMILY}\",
  \"options\": [\"${_banjo_fp_options_json}\"],
  \"compiler_id\": \"${CMAKE_CXX_COMPILER_ID}\",
  \"compiler_version\": \"${CMAKE_CXX_COMPILER_VERSION}\",
  \"frontend\": \"${CMAKE_CXX_COMPILER_FRONTEND_VARIANT}\",
  \"generator\": \"${CMAKE_GENERATOR}\",
  \"platform\": \"${CMAKE_GENERATOR_PLATFORM}\",
  \"build_type\": \"${CMAKE_BUILD_TYPE}\",
  \"multi_config\": ${_banjo_fp_multi}
}
")

# CMake's own account of what it generated: every configuration's targets, the
# files each compiles, and the ordered fragments of every compile and link
# command. Asked for here so that it is written at the end of this same run.
if(CMAKE_VERSION VERSION_GREATER_EQUAL 3.27)
    cmake_file_api(QUERY API_VERSION 1 CODEMODEL 2 TOOLCHAINS 1)
else()
    # Read at the start of the next run: the first build after a first
    # configure stops, and says to configure once more.
    file(WRITE "${CMAKE_BINARY_DIR}/.cmake/api/v1/query/codemodel-v2" "")
    file(WRITE "${CMAKE_BINARY_DIR}/.cmake/api/v1/query/toolchains-v1" "")
endif()

find_package(Python3 COMPONENTS Interpreter)
if(NOT Python3_Interpreter_FOUND)
    message(FATAL_ERROR "Floating-point model: the build audits its own compile commands with "
                        "scripts/check-fp-model.py, which needs Python 3.")
endif()
add_custom_target(banjo_fp_model_audit ALL
    COMMAND "${Python3_EXECUTABLE}" "${_banjo_fp_auditor}"
            --build "${CMAKE_BINARY_DIR}" --config "$<CONFIG>" --quiet
            --manifest "${CMAKE_BINARY_DIR}/fp-model-audit$<$<BOOL:$<CONFIG>>:-$<CONFIG>>.json"
    COMMENT "Floating-point model: auditing the commands CMake generated (${BANJO_FP_PROFILE})"
    VERBATIM)

function(_banjo_fp_model_targets directory out)
    get_property(targets DIRECTORY "${directory}" PROPERTY BUILDSYSTEM_TARGETS)
    get_property(subdirectories DIRECTORY "${directory}" PROPERTY SUBDIRECTORIES)
    foreach(subdirectory IN LISTS subdirectories)
        _banjo_fp_model_targets("${subdirectory}" more)
        list(APPEND targets ${more})
    endforeach()
    set(${out} "${targets}" PARENT_SCOPE)
endfunction()

# Once the directory that included this has been read: every target that
# compiles anything, Jolt's included, waits for the audit.
function(_banjo_fp_model_audit_first)
    _banjo_fp_model_targets("${CMAKE_CURRENT_SOURCE_DIR}" targets)
    foreach(target IN LISTS targets)
        get_target_property(type ${target} TYPE)
        get_target_property(imported ${target} IMPORTED)
        if(NOT imported AND type MATCHES "^(STATIC_LIBRARY|SHARED_LIBRARY|MODULE_LIBRARY|OBJECT_LIBRARY|EXECUTABLE)$")
            add_dependencies(${target} banjo_fp_model_audit)
        endif()
    endforeach()
endfunction()
cmake_language(DEFER CALL _banjo_fp_model_audit_first)
