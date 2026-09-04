cmake_minimum_required(VERSION 3.24)

project(
    banjo
    VERSION 0.1.0
    DESCRIPTION "A matter-first runtime for editable-physics worlds"
    LANGUAGES CXX)

option(BANJO_BUILD_LAB "Build the headless rolling-ball laboratory" ON)
option(BANJO_BUILD_TESTS "Build Banjo unit tests" ON)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_library(
    banjo_core
    src/material/MaterialCompiler.cpp
    src/matter/Lattice.cpp
    src/fracture/ActivationPolicy.cpp
    src/fracture/BrittleBondSolver.cpp
    src/fracture/ConnectedComponents.cpp
    src/fracture/FragmentMassProperties.cpp)

target_include_directories(banjo_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_features(banjo_core PUBLIC cxx_std_23)

if(MSVC)
    target_compile_options(banjo_core PRIVATE /W4 /permissive-)
else()
    target_compile_options(banjo_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
endif()

if(BANJO_BUILD_LAB)
    include(FetchContent)

    # Jolt 5.6 enables optional compute backends by default. Disable them in this
    # CPU reference build so Vulkan/DX12/Metal shader tooling is not required.
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

    add_executable(
        banjo_lab
        src/app/main.cpp
        src/rigid/JoltWorld.cpp)
    target_link_libraries(banjo_lab PRIVATE banjo_core Jolt)
    target_compile_features(banjo_lab PRIVATE cxx_std_23)

    if(MSVC)
        target_compile_options(banjo_lab PRIVATE /W4 /permissive-)
    else()
        target_compile_options(banjo_lab PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
    endif()
endif()

if(BANJO_BUILD_TESTS)
    include(CTest)
    enable_testing()

    add_executable(banjo_tests tests/test_main.cpp)
    target_link_libraries(banjo_tests PRIVATE banjo_core)
    target_compile_features(banjo_tests PRIVATE cxx_std_23)

    if(MSVC)
        target_compile_options(banjo_tests PRIVATE /W4 /permissive-)
    else()
        target_compile_options(banjo_tests PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
    endif()

    add_test(NAME banjo_tests COMMAND banjo_tests)
endif()
