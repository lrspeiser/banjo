# One floating-point model for everything compiled into the engine.
#
# An inline function -- a Jolt constraint part or vector operator, a helper in
# one of our own headers, a std:: template -- is compiled into every object
# file that uses it, and the linker keeps ONE copy of it: the first it meets.
# When two objects are compiled under different floating-point rules, which
# copy survives, and so what the arithmetic gives, depends on link order.
# Adding rigid/DrumRope.cpp once moved banjo_blade_tests' cut from 4.676 J to
# 4.192 J that way. Measured on 9317a5b, where only that file had been fixed,
# Jolt's own solver ran JoltWorld.cpp's /fp:precise copy of
# MotionProperties::GetInverseInertiaForRotation, while our tetrahedron
# contact ran Jolt's /fp:fast copies of its GJK and EPA routines
# (docs/floating-point-model.md).
#
# So every C++ object in the build is compiled to one model: IEEE arithmetic in
# the order the source writes it, with no fused multiply-add the source did not
# ask for and no reassociation.
#
#   MSVC        /fp:precise (Visual Studio 2022 does not contract under it),
#               never /fp:fast, /fp:strict or /fp:contract
#   GCC, Clang  -ffp-contract=off, and nothing from -ffast-math
#
# Jolt compiles itself /fp:fast (-ffp-contract=fast on GCC). The model is put
# on this directory before Jolt is added, so on every command line it comes
# after Jolt's own flags and wins there too. Jolt's FMA intrinsics
# (JPH_USE_FMADD) are explicit instructions, the same in every object, and stay.
#
# Include this before the first target. It applies the model and, once the
# directory that included it has been read, checks every target and every C++
# file of every target, Jolt's included. A target or file that has been given a
# floating-point option of its own stops the configure, and is named.

include_guard(GLOBAL)

# How this compiler spells the options. tests/fp_model_guard sets it to check
# the guard without a compiler.
if(NOT DEFINED BANJO_FP_MODEL_FAMILY)
    if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
        set(BANJO_FP_MODEL_FAMILY MSVC)
    else()
        set(BANJO_FP_MODEL_FAMILY GNU)
    endif()
endif()
if(BANJO_FP_MODEL_FAMILY STREQUAL "MSVC")
    set(BANJO_FP_MODEL_OPTION "/fp:precise")
else()
    set(BANJO_FP_MODEL_OPTION "-ffp-contract=off")
endif()

# banjo_fp_model_verdict(<out> <option>...)
#
# Reads compiler options in command-line order, as the compiler does -- the
# last of a kind wins -- and sets <out> to "" if they end in the model, or else
# to what breaks it.
function(banjo_fp_model_verdict out)
    set(unsafe "")
    if(BANJO_FP_MODEL_FAMILY STREQUAL "MSVC")
        set(model "precise")            # MSVC's default
        set(contract "")
        foreach(option IN LISTS ARGN)
            if(option MATCHES "^[-/]fp:(precise|fast|strict)$")
                set(model "${CMAKE_MATCH_1}")
            elseif(option MATCHES "^[-/]fp:contract$")
                set(contract "${option}")
            endif()
        endforeach()
        if(NOT model STREQUAL "precise")
            set(unsafe "/fp:${model}")
        elseif(contract)
            set(unsafe "${contract}")
        endif()
    else()
        set(contract "")                # GCC contracts unless told not to
        set(fast "")
        foreach(option IN LISTS ARGN)
            if(option MATCHES "^-ffp-contract=(off|on|fast)$")
                set(contract "${CMAKE_MATCH_1}")
            elseif(option MATCHES "^-ffp-model=(precise|strict)$")
                if(CMAKE_MATCH_1 STREQUAL "strict")
                    set(contract "off")
                else()
                    set(contract "on")
                endif()
            elseif(option STREQUAL "-fno-fast-math")
                set(fast "")
            elseif(option MATCHES "^-f(fast-math|unsafe-math-optimizations|associative-math|reciprocal-math|finite-math-only|no-signed-zeros|cx-limited-range)$"
                   OR option MATCHES "^-ffp-model=(fast|aggressive)$" OR option STREQUAL "-Ofast")
                set(fast "${option}")
            endif()
        endforeach()
        if(fast)
            set(unsafe "${fast}")
        elseif(NOT contract STREQUAL "off")
            if(contract)
                set(unsafe "-ffp-contract=${contract}")
            else()
                set(unsafe "no -ffp-contract=off, so the compiler contracts")
            endif()
        endif()
    endif()
    set(${out} "${unsafe}" PARENT_SCOPE)
endfunction()

# banjo_fp_model_options(<out> <item>...)
#
# The items that can change the model, out of a list of compile options or
# flags, as they read for C++ with this compiler. A generator expression that
# only chooses a language, a compiler, a configuration or the build tree is
# read for C++ and every configuration; one it cannot read stops the configure
# rather than pass unchecked.
function(banjo_fp_model_options out)
    set(result "")
    foreach(item IN LISTS ARGN)
        if(NOT item MATCHES "fp:|fp-contract|fp-model|fast-math|Ofast|unsafe-math|associative-math|reciprocal-math|finite-math|signed-zeros|cx-limited")
            continue()
        endif()
        _banjo_fp_model_unwrap("${item}" option)
        if(NOT option STREQUAL "")
            list(APPEND result "${option}")
        endif()
    endforeach()
    set(${out} "${result}" PARENT_SCOPE)
endfunction()

# What an option given as a generator expression gives C++ with this compiler,
# in any configuration: $<condition:value> with a condition on the language,
# the compiler or the configuration, and $<BUILD_INTERFACE:value>. Sets <out>
# to the value, or to "" when it gives C++ nothing here.
function(_banjo_fp_model_unwrap item out)
    set(value "${item}")
    while(value MATCHES "^\\$<")
        if(value MATCHES "^\\$<BUILD_INTERFACE:(.*)>$")
            set(value "${CMAKE_MATCH_1}")
            continue()
        elseif(value MATCHES "^\\$<INSTALL_INTERFACE:")
            set(value "")
            break()
        elseif(NOT value MATCHES "^\\$<\\$<")
            message(FATAL_ERROR "Floating-point model: the option ${item} is a generator expression "
                    "this check cannot read (cmake/FloatingPointModel.cmake). Write it plainly.")
        endif()
        # The condition is a generator expression of its own: find its end.
        string(LENGTH "${value}" length)
        set(depth 0)
        set(close -1)
        set(index 2)
        while(index LESS length)
            string(SUBSTRING "${value}" ${index} 2 pair)
            if(pair STREQUAL "$<")
                math(EXPR depth "${depth} + 1")
                math(EXPR index "${index} + 2")
                continue()
            endif()
            string(SUBSTRING "${value}" ${index} 1 char)
            if(char STREQUAL ">")
                math(EXPR depth "${depth} - 1")
                if(depth EQUAL 0)
                    set(close ${index})
                    break()
                endif()
            endif()
            math(EXPR index "${index} + 1")
        endwhile()
        math(EXPR colon "${close} + 1")
        string(SUBSTRING "${value}" ${colon} 1 char)
        if(close LESS 0 OR NOT char STREQUAL ":")
            message(FATAL_ERROR "Floating-point model: the option ${item} is a generator expression "
                    "this check cannot read (cmake/FloatingPointModel.cmake). Write it plainly.")
        endif()
        math(EXPR condition_length "${close} - 1")
        string(SUBSTRING "${value}" 2 ${condition_length} condition)
        math(EXPR start "${close} + 2")
        math(EXPR value_length "${length} - ${start} - 1")
        string(SUBSTRING "${value}" ${start} ${value_length} value)
        if(condition MATCHES "COMPILE_LANG(UAGE|_AND_ID):([^:>]*)")
            if(NOT CMAKE_MATCH_2 MATCHES "(^|,)CXX(,|$)")
                set(value "")
                break()
            endif()
        endif()
        if(CMAKE_CXX_COMPILER_ID AND condition MATCHES "CXX_COMPILER_ID:([^:>]*)")
            if(NOT CMAKE_MATCH_1 MATCHES "(^|,)${CMAKE_CXX_COMPILER_ID}(,|$)")
                set(value "")
                break()
            endif()
        endif()
    endwhile()
    set(${out} "${value}" PARENT_SCOPE)
endfunction()

function(_banjo_fp_model_targets directory out)
    get_property(targets DIRECTORY "${directory}" PROPERTY BUILDSYSTEM_TARGETS)
    get_property(subdirectories DIRECTORY "${directory}" PROPERTY SUBDIRECTORIES)
    foreach(subdirectory IN LISTS subdirectories)
        _banjo_fp_model_targets("${subdirectory}" more)
        list(APPEND targets ${more})
    endforeach()
    set(${out} "${targets}" PARENT_SCOPE)
endfunction()

# The options a target is given by what it links (their usage requirements),
# followed through the libraries those link in turn.
function(_banjo_fp_model_usage target out)
    set(options "")
    set(seen "")
    get_target_property(pending ${target} LINK_LIBRARIES)
    while(pending)
        list(POP_FRONT pending item)
        if(item MATCHES "^\\$<LINK_ONLY:(.*)>$" OR item MATCHES "^\\$<BUILD_INTERFACE:(.*)>$")
            set(item "${CMAKE_MATCH_1}")
        endif()
        if(NOT TARGET "${item}" OR item IN_LIST seen)
            continue()
        endif()
        list(APPEND seen "${item}")
        get_target_property(aliased "${item}" ALIASED_TARGET)
        if(aliased)
            set(item "${aliased}")
        endif()
        get_target_property(interface "${item}" INTERFACE_COMPILE_OPTIONS)
        if(interface)
            list(APPEND options ${interface})
        endif()
        get_target_property(more "${item}" INTERFACE_LINK_LIBRARIES)
        if(more)
            list(APPEND pending ${more})
        endif()
    endwhile()
    set(${out} "${options}" PARENT_SCOPE)
endfunction()

# Checks every target under this directory; see the top of this file.
function(banjo_check_fp_model)
    if(CMAKE_CONFIGURATION_TYPES)
        set(configurations ${CMAKE_CONFIGURATION_TYPES})
    else()
        set(configurations "${CMAKE_BUILD_TYPE}")
    endif()
    _banjo_fp_model_targets("${CMAKE_CURRENT_SOURCE_DIR}" targets)
    set(broken "")
    set(checked 0)
    foreach(target IN LISTS targets)
        get_target_property(type ${target} TYPE)
        get_target_property(imported ${target} IMPORTED)
        if(imported OR NOT type MATCHES "^(STATIC_LIBRARY|SHARED_LIBRARY|MODULE_LIBRARY|OBJECT_LIBRARY|EXECUTABLE)$")
            continue()
        endif()
        get_target_property(directory ${target} SOURCE_DIR)
        get_target_property(sources ${target} SOURCES)
        get_target_property(target_options ${target} COMPILE_OPTIONS)
        get_target_property(target_flags ${target} COMPILE_FLAGS)
        _banjo_fp_model_usage(${target} usage)
        get_directory_property(language_flags DIRECTORY "${directory}" DEFINITION CMAKE_CXX_FLAGS)
        separate_arguments(language_flags UNIX_COMMAND "${language_flags}")
        if(NOT target_options)
            set(target_options "")
        endif()
        if(NOT target_flags)
            set(target_flags "")
        endif()
        separate_arguments(target_flags UNIX_COMMAND "${target_flags}")
        foreach(source IN LISTS sources)
            if(source MATCHES "\\$<")
                continue()
            endif()
            cmake_path(ABSOLUTE_PATH source BASE_DIRECTORY "${directory}" NORMALIZE OUTPUT_VARIABLE path)
            get_property(language SOURCE "${path}" TARGET_DIRECTORY ${target} PROPERTY LANGUAGE)
            if(language)
                if(NOT language STREQUAL "CXX")
                    continue()
                endif()
            elseif(NOT path MATCHES "\\.(cpp|cc|cxx|c\\+\\+|C|ixx)$")
                continue()
            endif()
            get_property(source_options SOURCE "${path}" TARGET_DIRECTORY ${target} PROPERTY COMPILE_OPTIONS)
            get_property(source_flags SOURCE "${path}" TARGET_DIRECTORY ${target} PROPERTY COMPILE_FLAGS)
            separate_arguments(source_flags UNIX_COMMAND "${source_flags}")
            math(EXPR checked "${checked} + 1")
            foreach(configuration IN LISTS configurations)
                set(configuration_flags "")
                if(configuration)
                    string(TOUPPER "${configuration}" upper)
                    get_directory_property(configuration_flags DIRECTORY "${directory}"
                                           DEFINITION CMAKE_CXX_FLAGS_${upper})
                    separate_arguments(configuration_flags UNIX_COMMAND "${configuration_flags}")
                endif()
                # The order a command line has them in: the language's flags,
                # the configuration's, the target's own and what it links, and
                # last the file's.
                banjo_fp_model_options(options ${language_flags} ${configuration_flags} ${target_flags}
                                       ${target_options} ${usage} ${source_flags} ${source_options})
                banjo_fp_model_verdict(verdict ${options})
                if(verdict)
                    set(shown "${path}")
                    cmake_path(IS_PREFIX CMAKE_SOURCE_DIR "${path}" NORMALIZE inside)
                    if(inside)
                        cmake_path(RELATIVE_PATH path BASE_DIRECTORY "${CMAKE_SOURCE_DIR}" OUTPUT_VARIABLE shown)
                    endif()
                    list(APPEND broken "  ${target}: ${shown} (${configuration}): ${verdict}")
                    break()
                endif()
            endforeach()
        endforeach()
    endforeach()
    if(broken)
        list(LENGTH broken count)
        list(SUBLIST broken 0 20 shown)
        string(JOIN "\n" shown ${shown})
        message(FATAL_ERROR
            "Floating-point model: ${count} C++ file(s) would compile under rules other than the "
            "rest of the build, so which copy of an inline function the linker keeps -- and what "
            "the arithmetic gives -- would depend on link order:\n${shown}\n"
            "Everything linked into the engine uses ${BANJO_FP_MODEL_OPTION} and nothing from "
            "fast math. Take the option off the target or the file; the reasons are in "
            "cmake/FloatingPointModel.cmake and docs/floating-point-model.md.")
    endif()
    message(STATUS "Floating-point model: ${checked} C++ files checked, all ${BANJO_FP_MODEL_OPTION}")
endfunction()

# tests/fp_model_guard_tests.cmake includes this as a script, for the
# functions alone.
if(NOT CMAKE_SCRIPT_MODE_FILE)
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:${BANJO_FP_MODEL_OPTION}>)
    cmake_language(DEFER CALL banjo_check_fp_model)
endif()
