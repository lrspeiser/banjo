# How cmake/FloatingPointModel.cmake reads compiler options, checked without a
# build: cmake -P tests/fp_model_guard_tests.cmake
#
# Each case is a command line's options in order, for one compiler family, and
# what the check must say: "" when they end in the model, or what breaks it.
# The options are the real ones -- Jolt's own flags, and the model this build
# adds after them. tests/fp_model_guard is the other half: a build whose
# targets break the model, which must not configure.

include("${CMAKE_CURRENT_LIST_DIR}/../cmake/FloatingPointModel.cmake")

set(cases 0)
set(failures "")
function(expect family expected)
    set(BANJO_FP_MODEL_FAMILY ${family})
    banjo_fp_model_options(options ${ARGN})
    banjo_fp_model_verdict(verdict ${options})
    if(NOT verdict STREQUAL expected)
        set(failures "${failures}\n  ${family} [${ARGN}]: said \"${verdict}\", should say \"${expected}\"" PARENT_SCOPE)
    endif()
endfunction()

set(jolt_msvc /Zc:__cplusplus /Gm- /MP /nologo /diagnostics:classic /FC /fp:except- /Zc:inline /GR- /wd4577 /fp:fast)
set(model_msvc "$<$<COMPILE_LANGUAGE:CXX>:/fp:precise>")
set(jolt_gnu -fno-rtti -fno-exceptions -Wno-stringop-overflow -Wno-psabi -ffp-contract=fast)
set(model_gnu "$<$<COMPILE_LANGUAGE:CXX>:-ffp-contract=off>")

# MSVC: /fp:precise is its default, and the last /fp: wins.
expect(MSVC "" /DWIN32 /D_WINDOWS /EHsc /O2 /Ob2 /DNDEBUG)
expect(MSVC "" ${jolt_msvc} /GS- /Gy /O2 /Oi /Ot ${model_msvc})
expect(MSVC "/fp:fast" ${jolt_msvc} /GS- /Gy /O2 /Oi /Ot)
expect(MSVC "/fp:fast" ${model_msvc} /fp:fast)
expect(MSVC "/fp:fast" ${model_msvc} -fp:fast)
expect(MSVC "/fp:strict" ${model_msvc} /fp:strict)
expect(MSVC "/fp:contract" ${model_msvc} /fp:contract)
expect(MSVC "" /fp:fast ${model_msvc} "$<$<COMPILE_LANGUAGE:C>:/fp:fast>")
expect(MSVC "/fp:fast" ${model_msvc} "$<$<CONFIG:Debug>:/fp:fast>")
expect(MSVC "/fp:fast" ${model_msvc} "$<$<COMPILE_LANGUAGE:CXX>:/fp:fast>")
expect(MSVC "" ${model_msvc} /arch:AVX2 /GR- /fp:except-)
# GCC and Clang contract unless told not to, and fast math is refused however
# it comes.
expect(GNU "no -ffp-contract=off, so the compiler contracts" -O3 -mavx2 -mfma)
expect(GNU "" ${jolt_gnu} -O3 ${model_gnu} -mavx2 -mfma)
expect(GNU "-ffp-contract=fast" ${jolt_gnu} -O3)
expect(GNU "-ffp-contract=fast" ${model_gnu} -ffp-contract=fast)
expect(GNU "-ffp-contract=on" ${model_gnu} -ffp-contract=on)
expect(GNU "-ffast-math" ${model_gnu} -ffast-math)
expect(GNU "-ffast-math" -ffast-math ${model_gnu})
expect(GNU "" -ffast-math -fno-fast-math ${model_gnu})
expect(GNU "-Ofast" ${model_gnu} -Ofast)
expect(GNU "-fassociative-math" ${model_gnu} -fassociative-math)
expect(GNU "-ffp-contract=on" ${model_gnu} -ffp-model=precise)
expect(GNU "" ${model_gnu} "$<$<COMPILE_LANGUAGE:C>:-ffast-math>")
expect(GNU "" ${model_gnu} "$<INSTALL_INTERFACE:-ffast-math>")
expect(GNU "-ffast-math" ${model_gnu} "$<BUILD_INTERFACE:-ffast-math>")

file(READ "${CMAKE_CURRENT_LIST_FILE}" self)
string(REGEX MATCHALL "\nexpect\\(" all "${self}")
list(LENGTH all cases)
if(failures)
    message(FATAL_ERROR "fp_model_guard_tests: some options were misread:${failures}")
endif()
message(STATUS "fp_model_guard_tests: all ${cases} cases read as they should")

# And the walk over real targets: tests/fp_model_guard gives one target and one
# file of another a fast option, and must be refused, naming those two files
# and no other.
if(NOT DEFINED BANJO_FP_MODEL_FAMILY)
    if(CMAKE_HOST_WIN32)
        set(BANJO_FP_MODEL_FAMILY MSVC)
    else()
        set(BANJO_FP_MODEL_FAMILY GNU)
    endif()
endif()
if(NOT GUARD_BINARY_DIR)
    set(GUARD_BINARY_DIR "${CMAKE_CURRENT_BINARY_DIR}/fp_model_guard")
endif()
set(generator "")
if(GUARD_GENERATOR)
    set(generator -G "${GUARD_GENERATOR}")
endif()
file(REMOVE_RECURSE "${GUARD_BINARY_DIR}")
execute_process(
    COMMAND "${CMAKE_COMMAND}" -S "${CMAKE_CURRENT_LIST_DIR}/fp_model_guard" -B "${GUARD_BINARY_DIR}"
            ${generator} -DBANJO_FP_MODEL_FAMILY=${BANJO_FP_MODEL_FAMILY}
    RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE output)
set(wrong "")
if(result EQUAL 0)
    string(APPEND wrong "\n  it configured")
endif()
foreach(expected "2 C++ file(s) would compile" "fast_target: fast_target.cpp" "one_fast_file: fast_file.cpp")
    string(FIND "${output}" "${expected}" at)
    if(at LESS 0)
        string(APPEND wrong "\n  it did not say \"${expected}\"")
    endif()
endforeach()
foreach(innocent "keeps_the_model:" "model_file.cpp")
    string(FIND "${output}" "${innocent}" at)
    if(NOT at LESS 0)
        string(APPEND wrong "\n  it named ${innocent}, which keeps the model")
    endif()
endforeach()
if(wrong)
    message(FATAL_ERROR "fp_model_guard_tests: the build that breaks the model (${BANJO_FP_MODEL_FAMILY}) "
            "was not refused as it should be:${wrong}\n--- its configure said:\n${output}")
endif()
message(STATUS "fp_model_guard_tests: the build that breaks the model (${BANJO_FP_MODEL_FAMILY}) is refused, naming its two files")
