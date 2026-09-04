cmake_minimum_required(VERSION 3.25)

project(
    banjo
    VERSION 0.4.0
    DESCRIPTION "A matter-first runtime for editable-physics worlds"
    LANGUAGES C CXX)

option(BANJO_BUILD_LAB "Build the interactive rolling-ball visual laboratory" ON)
option(BANJO_BUILD_HEADLESS "Build the automated headless rolling-ball laboratory" ON)
option(BANJO_BUILD_PRECOMPUTE "Build the deterministic scenario precomputation tool" ON)
option(BANJO_BUILD_TESTS "Build Banjo unit tests" ON)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

function(banjo_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive-)
    else()
        target_compile_options(
            ${target}
            PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
    endif()
endfunction()

add_library(
    banjo_core
    src/material/MaterialCompiler.cpp
    src/material/MaterialCatalog.cpp
    src/matter/Lattice.cpp
    src/fracture/ActivationPolicy.cpp
    src/fracture/BrittleBondSolver.cpp
    src/fracture/ConnectedComponents.cpp
    src/fracture/FragmentMassProperties.cpp
    src/fracture/FragmentGeometry.cpp
    src/prediction/BallScenarioProjection.cpp
    src/prediction/ScenarioCache.cpp)

target_include_directories(banjo_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_features(banjo_core PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_core)

if(BANJO_BUILD_PRECOMPUTE)
    add_executable(banjo_precompute src/app/precompute_main.cpp)
    target_link_libraries(banjo_precompute PRIVATE banjo_core)
    target_compile_features(banjo_precompute PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_precompute)
endif()

if(BANJO_BUILD_LAB OR BANJO_BUILD_HEADLESS)
    include(FetchContent)

    set(JPH_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
    set(ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
    set(ENABLE_ALL_WARNINGS OFF CACHE BOOL "" FORCE)
    set(INTERPROCEDURAL_OPTIMIZATION OFF CACHE BOOL "" FORCE)
    set(DEBUG_RENDERER_IN_DEBUG_AND_RELEASE OFF CACHE BOOL "" FORCE)
    set(PROFILER_IN_DEBUG_AND_RELEASE OFF CACHE BOOL "" FORCE)
    set(JPH_USE_DX12 OFF CACHE BOOL "" FORCE)
    set(JPH_USE_VK OFF CACHE BOOL "" FORCE)
    set(JPH_USE_MTL OFF CACHE BOOL "" FORCE)
    set(JPH_USE_CPU_COMPUTE OFF CACHE BOOL "" FORCE)

    FetchContent_Declare(
        JoltPhysics
        GIT_REPOSITORY https://github.com/jrouwe/JoltPhysics.git
        GIT_TAG v5.6.0
        GIT_SHALLOW TRUE
        SOURCE_SUBDIR Build)
    FetchContent_MakeAvailable(JoltPhysics)

    add_library(
        banjo_runtime
        src/rigid/JoltWorld.cpp
        src/sim/RollingBallExperiment.cpp)
    target_include_directories(banjo_runtime PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(banjo_runtime PUBLIC banjo_core Jolt)
    target_compile_features(banjo_runtime PUBLIC cxx_std_23)
    banjo_enable_warnings(banjo_runtime)
endif()

if(BANJO_BUILD_HEADLESS)
    add_executable(banjo_headless src/app/headless_main.cpp)
    target_link_libraries(banjo_headless PRIVATE banjo_runtime)
    target_compile_features(banjo_headless PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_headless)
endif()

if(BANJO_BUILD_LAB)
    set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
    set(CUSTOMIZE_BUILD ON CACHE BOOL "" FORCE)
    set(USE_AUDIO OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_X11 ON CACHE BOOL "" FORCE)
    set(GLFW_BUILD_WAYLAND OFF CACHE BOOL "" FORCE)

    FetchContent_Declare(
        raylib
        GIT_REPOSITORY https://github.com/raysan5/raylib.git
        GIT_TAG 6.0
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(raylib)

    add_executable(banjo_lab src/viewer/main.cpp)
    target_link_libraries(banjo_lab PRIVATE banjo_runtime raylib)
    target_compile_features(banjo_lab PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_lab)
endif()

if(BANJO_BUILD_TESTS)
    include(CTest)
    enable_testing()

    add_executable(banjo_tests tests/test_main.cpp)
    target_link_libraries(banjo_tests PRIVATE banjo_core)
    target_compile_features(banjo_tests PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_tests)
    add_test(NAME banjo_tests COMMAND banjo_tests)

    add_executable(banjo_material_tests tests/material_prediction_tests.cpp)
    target_link_libraries(banjo_material_tests PRIVATE banjo_core)
    target_compile_features(banjo_material_tests PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_material_tests)
    add_test(NAME banjo_material_tests COMMAND banjo_material_tests)

    add_executable(banjo_constitutive_tests tests/constitutive_tests.cpp)
    target_link_libraries(banjo_constitutive_tests PRIVATE banjo_core)
    target_compile_features(banjo_constitutive_tests PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_constitutive_tests)
    add_test(NAME banjo_constitutive_tests COMMAND banjo_constitutive_tests)

    if(TARGET banjo_runtime)
        add_executable(banjo_runtime_tests tests/runtime_dynamics_tests.cpp)
        target_link_libraries(banjo_runtime_tests PRIVATE banjo_runtime)
        target_compile_features(banjo_runtime_tests PRIVATE cxx_std_23)
        banjo_enable_warnings(banjo_runtime_tests)
        add_test(NAME banjo_runtime_tests COMMAND banjo_runtime_tests)
    endif()
endif()
