cmake_minimum_required(VERSION 3.25)

project(
    banjo
    VERSION 0.7.0
    DESCRIPTION "A matter-first runtime for editable-physics worlds"
    LANGUAGES C CXX)

option(BANJO_BUILD_LAB "Build the interactive rolling-ball visual laboratory" ON)
option(BANJO_BUILD_HEADLESS "Build the automated headless rolling-ball laboratory" ON)
option(BANJO_BUILD_PRECOMPUTE "Build the deterministic scenario precomputation tools" ON)
option(BANJO_BUILD_TESTS "Build Banjo unit tests" ON)
option(BANJO_BUILD_CUDA "Build the CUDA backend of the fast explicit lattice fracture lane" OFF)
# nvcc contracts a*b+c into fused multiply-adds by default; MSVC (/fp:precise)
# never does. A fused operation rounds once where the CPU rounds twice, and the
# lattice's discrete failure decisions amplify that last-bit difference into a
# different fracture cascade. The lane's claim is that the GPU runs the CPU
# lane's physics, so contraction is off unless asked for; the cost is measured
# in docs/fast-gpu-checkpoint.md.
option(BANJO_CUDA_FMAD "Let nvcc fuse multiply-adds in the lattice kernel (breaks bitwise equality with the CPU backend)" OFF)

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
    src/material/NetworkMaterial.cpp
    src/material/Plasticity.cpp
    src/material/SmallStrainLaw.cpp
    src/physics/SmallStrainPatch.cpp
    src/physics/DynamicPatch.cpp
    src/physics/SweptSphereTriangle.cpp
    src/physics/SpherePatchWorld.cpp
    src/physics/SphereSurfaceContactStep.cpp
    src/physics/SpherePatchAdvance.cpp
    src/physics/PatchPressure.cpp
    src/material/PropertyVariation.cpp
    src/persistence/NumericStateDelta.cpp
    src/physics/ResolutionBudget.cpp
    src/thermal/ThermalKernel.cpp
    src/thermal/EnthalpyLaw.cpp
    src/matter/Lattice.cpp
    src/physics/ContactMechanics.cpp
    src/physics/CohesiveInterface.cpp
    src/physics/CohesiveFacet.cpp
    src/physics/CohesiveAssembly.cpp
    src/physics/CohesiveDynamicPatch.cpp
    src/physics/CohesiveSphereWorld.cpp
    src/physics/CorotatedTet.cpp
    src/physics/CorotatedCohesiveFacet.cpp
    src/physics/SpherePatchSnapshot.cpp
    src/physics/FractureOverlap.cpp
    src/physics/SegmentTriangleContact.cpp
    src/physics/SweptSegmentTriangle.cpp
    src/physics/PairedFacetContact.cpp
    src/physics/SpherePatchSnapshotCodec.cpp
    src/physics/TetrahedronContactImpulse.cpp
    src/physics/FractureComponentState.cpp
    src/physics/FractureTopology.cpp
    src/physics/CohesivePair.cpp
    src/physics/CohesiveSpatialPair.cpp
    src/physics/CohesiveRigidPair.cpp
    src/physics/ConservativeStep.cpp
    src/physics/FractureStep.cpp
    src/physics/ConservativeAdvance.cpp
    src/physics/NormalImpact.cpp
    src/physics/NormalCompliance.cpp
    src/physics/CompliantStep.cpp
    src/physics/CompliantAdvance.cpp
    src/physics/ElasticNewton.cpp
    src/physics/MechanicalAccounting.cpp
    src/physics/RollingKinematics.cpp
    src/physics/SphereMaterialContact.cpp
    src/fracture/ActivationPolicy.cpp
    src/fracture/FracturePreview.cpp
    src/fracture/RuptureCascade.cpp
    src/fracture/EnergyRupture.cpp
    src/fracture/BondFailure.cpp
    src/fracture/QuasiStaticFracture.cpp
    src/fracture/PieceGeometry.cpp
    src/fracture/BrittleBondSolver.cpp
    src/fracture/ConnectedComponents.cpp
    src/fracture/FragmentMassProperties.cpp
    src/fracture/FragmentGeometry.cpp
    src/fracture/CellSkin.cpp
    src/prediction/BallScenarioProjection.cpp
    src/prediction/ScenarioCache.cpp
    src/precompute/MaterialOutcome.cpp)

target_include_directories(banjo_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_features(banjo_core PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_core)

# Precomputed-basis (modal) fracture lane. Dense eigen work is kept in its own
# library so its threading and vector flags do not leak into banjo_core.
option(BANJO_MODAL_OPENMP "Thread the modal lane's dense products with OpenMP" ON)
add_library(
    banjo_modal
    src/modal/SymmetricEigen.cpp
    src/modal/ModalBasis.cpp
    src/modal/ModalFracture.cpp)
target_link_libraries(banjo_modal PUBLIC banjo_core)
target_compile_features(banjo_modal PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_modal)
if(MSVC)
    target_compile_options(banjo_modal PRIVATE /arch:AVX2)
endif()
if(BANJO_MODAL_OPENMP)
    find_package(OpenMP)
    if(OpenMP_CXX_FOUND)
        target_link_libraries(banjo_modal PUBLIC OpenMP::OpenMP_CXX)
    endif()
endif()

# The fast explicit lattice lane (docs/fast-gpu-checkpoint.md): the CPU
# lane's physics on a colour-parallel schedule. The C++ library always builds
# and carries the CPU backend; the CUDA backend is a separate target behind
# BANJO_BUILD_CUDA so the rest of the repository builds without a CUDA
# toolchain. Without it the GPU factory throws a clear error, never a no-op.
add_library(
    banjo_fastlattice
    src/matter/BoxLattice.cpp
    src/matter/LatticeMerge.cpp
    src/fastlattice/LatticeSchedule.cpp
    src/fastlattice/FastLattice.cpp
    src/fastlattice/CpuLatticeBackend.cpp
    src/fastlattice/ParallelCpuLatticeBackend.cpp
    src/fastlattice/Refracture.cpp
    src/fastlattice/Propagator.cpp)
target_link_libraries(banjo_fastlattice PUBLIC banjo_core)
target_compile_features(banjo_fastlattice PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_fastlattice)
if(BANJO_BUILD_CUDA)
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES OR "${CMAKE_CUDA_ARCHITECTURES}" STREQUAL "")
        set(CMAKE_CUDA_ARCHITECTURES 120)
    endif()
    enable_language(CUDA)
    find_package(CUDAToolkit REQUIRED)
    add_library(banjo_fastlattice_cuda STATIC src/fastlattice/CudaLatticeBackend.cu)
    target_include_directories(banjo_fastlattice_cuda PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
    set_target_properties(banjo_fastlattice_cuda PROPERTIES
        CUDA_STANDARD 20 CUDA_STANDARD_REQUIRED ON CUDA_SEPARABLE_COMPILATION OFF)
    if(NOT BANJO_CUDA_FMAD)
        target_compile_options(banjo_fastlattice_cuda PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:-fmad=false>)
    endif()
    target_link_libraries(banjo_fastlattice_cuda PUBLIC CUDA::cudart_static)
    target_link_libraries(banjo_fastlattice PUBLIC banjo_fastlattice_cuda)
    target_compile_definitions(banjo_fastlattice PUBLIC BANJO_HAS_CUDA=1)
else()
    target_sources(banjo_fastlattice PRIVATE src/fastlattice/CudaLatticeUnavailable.cpp)
endif()

if(BANJO_BUILD_PRECOMPUTE)
    add_executable(banjo_phase_pair_benchmark tools/phase_pair_benchmark.cpp)
    target_link_libraries(banjo_phase_pair_benchmark PRIVATE banjo_core)
    banjo_enable_warnings(banjo_phase_pair_benchmark)
    add_executable(banjo_lattice_dump tools/lattice_dump.cpp)
    target_link_libraries(banjo_lattice_dump PRIVATE banjo_core)
    banjo_enable_warnings(banjo_lattice_dump)
    add_executable(banjo_precompute src/app/precompute_main.cpp)
    target_link_libraries(banjo_precompute PRIVATE banjo_core)
    target_compile_features(banjo_precompute PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_precompute)
endif()

if(BANJO_BUILD_LAB OR BANJO_BUILD_HEADLESS)
    include(FetchContent)

    # Cohesive opening distances are below float position resolution, even
    # near ordinary gameplay coordinates. Preserve explicit OFF builds for
    # legacy saves/regression; new builds use the validated position format.
    option(DOUBLE_PRECISION "Use double-precision Jolt positions (saved-world identity)" ON)

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
    # Jolt defaults to the static MSVC runtime (/MT); Banjo and raylib use the
    # dynamic one (/MD), so the link fails on Visual Studio without this.
    set(USE_STATIC_MSVC_RUNTIME_LIBRARY OFF CACHE BOOL "" FORCE)

    FetchContent_Declare(
        JoltPhysics
        GIT_REPOSITORY https://github.com/jrouwe/JoltPhysics.git
        GIT_TAG v5.6.0
        GIT_SHALLOW TRUE
        SOURCE_SUBDIR Build)
    FetchContent_MakeAvailable(JoltPhysics)

    add_library(
        banjo_runtime
        src/physics/TetrahedronContact.cpp
        src/rigid/JoltWorld.cpp
        src/sim/RollingBallExperiment.cpp)
    target_include_directories(banjo_runtime PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
    target_link_libraries(banjo_runtime PUBLIC banjo_core Jolt)
    target_compile_features(banjo_runtime PUBLIC cxx_std_23)
    banjo_enable_warnings(banjo_runtime)

    # Structured creator input is parsed independently of the language model.
    set(JSON_BuildTests OFF CACHE BOOL "" FORCE)
    set(JSON_Install OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(nlohmann_json
        GIT_REPOSITORY https://github.com/nlohmann/json.git
        GIT_TAG 65ee68451d8eb2b5f3a30b410476ab83deb3289b)
    FetchContent_MakeAvailable(nlohmann_json)
    add_library(banjo_material_lab src/creator/BondedBowl.cpp src/creator/BowlRecording.cpp src/platform/BowlGeometry.cpp)
    target_link_libraries(banjo_material_lab PUBLIC banjo_core)
    banjo_enable_warnings(banjo_material_lab)
    add_library(banjo_platform src/platform/PlatformWorld.cpp src/platform/PlatformPlayback.cpp src/platform/CompiledObject.cpp src/platform/CompiledRuntime.cpp src/platform/NetworkWorld.cpp)
    target_link_libraries(banjo_platform PUBLIC banjo_runtime banjo_material_lab PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_platform)
    add_library(banjo_sparse_world src/world/SparseThermalWorld.cpp src/world/WorldLabFixture.cpp src/world/WorldPackage.cpp)
    target_link_libraries(banjo_sparse_world PUBLIC banjo_core PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_sparse_world)
    add_executable(banjo_world_cli src/app/world_main.cpp)
    target_link_libraries(banjo_world_cli PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_world_cli)
    add_executable(banjo_platform_cli src/app/platform_main.cpp)
    add_executable(banjo_playground_record tools/playground_record.cpp)
    target_link_libraries(banjo_playground_record PRIVATE banjo_platform nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_playground_record)
    target_link_libraries(banjo_platform_cli PRIVATE banjo_platform nlohmann_json::nlohmann_json)
    add_library(banjo_creator_runtime src/creator/CreatorWorld.cpp src/creator/BowlLab.cpp)
    target_link_libraries(banjo_creator_runtime PUBLIC banjo_runtime banjo_material_lab PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_creator_runtime)
    add_library(banjo_starter_runtime src/creator/StarterWorld.cpp)
    target_link_libraries(banjo_starter_runtime PUBLIC banjo_creator_runtime PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_starter_runtime)
    add_library(banjo_precision_conversion src/creator/PrecisionConversion.cpp)
    target_link_libraries(banjo_precision_conversion PUBLIC banjo_starter_runtime PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_precision_conversion)
    add_executable(banjo_starter_assistant_probe src/app/starter_assistant_probe_main.cpp)
    target_link_libraries(banjo_starter_assistant_probe PRIVATE banjo_starter_runtime banjo_creator_assistant)
    banjo_enable_warnings(banjo_starter_assistant_probe)
    add_executable(banjo_assembly_review_probe src/app/assembly_review_probe_main.cpp)
    target_link_libraries(banjo_assembly_review_probe PRIVATE banjo_creator_assistant nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_assembly_review_probe)
    add_library(banjo_creator_assistant src/creator/CodexAssistant.cpp src/platform/ChildProcess.cpp)
    target_link_libraries(banjo_creator_assistant PUBLIC banjo_creator_runtime PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_creator_assistant)
endif()

if(BANJO_BUILD_HEADLESS)
    add_executable(banjo_sphere_patch_adaptive_probe tools/sphere_patch_adaptive_probe.cpp)
    target_link_libraries(banjo_sphere_patch_adaptive_probe PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_sphere_patch_adaptive_probe)
    add_executable(banjo_sphere_patch_probe tools/sphere_patch_probe.cpp)
    target_link_libraries(banjo_sphere_patch_probe PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_sphere_patch_probe)
    add_executable(banjo_material_behavior_probe tools/material_behavior_probe.cpp)
    target_link_libraries(banjo_material_behavior_probe PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_material_behavior_probe)
    add_executable(banjo_dynamic_material_cli tools/dynamic_material_cli.cpp)
    target_link_libraries(banjo_dynamic_material_cli PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_dynamic_material_cli)
    add_executable(banjo_continuum_cli tools/continuum_patch_probe.cpp)
    target_link_libraries(banjo_continuum_cli PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_continuum_cli)
    add_executable(banjo_continuum_kernel_benchmark tools/continuum_kernel_benchmark.cpp)
    target_link_libraries(banjo_continuum_kernel_benchmark PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_continuum_kernel_benchmark)
    add_executable(banjo_object_state_probe tools/object_state_probe.cpp)
    target_link_libraries(banjo_object_state_probe PRIVATE banjo_core nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_object_state_probe)
    add_executable(banjo_precision_convert src/app/precision_convert_main.cpp)
    target_link_libraries(banjo_precision_convert PRIVATE banjo_precision_conversion)
    banjo_enable_warnings(banjo_precision_convert)
    add_executable(banjo_runtime_cohesive_probe src/app/runtime_cohesive_probe_main.cpp)
    target_link_libraries(banjo_runtime_cohesive_probe PRIVATE banjo_runtime)
    banjo_enable_warnings(banjo_runtime_cohesive_probe)
    add_executable(banjo_cohesive_pair_probe src/app/cohesive_pair_probe_main.cpp)
    target_link_libraries(banjo_cohesive_pair_probe PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_pair_probe)
    add_executable(banjo_cohesive_probe src/app/cohesive_probe_main.cpp)
    target_link_libraries(banjo_cohesive_probe PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_probe)
    add_executable(banjo_assistant_probe src/app/assistant_probe_main.cpp)
    target_link_libraries(banjo_assistant_probe PRIVATE banjo_creator_assistant)
    banjo_enable_warnings(banjo_assistant_probe)
    add_executable(banjo_creator_cli src/app/creator_main.cpp)
    target_link_libraries(banjo_creator_cli PRIVATE banjo_creator_runtime)
    banjo_enable_warnings(banjo_creator_cli)
    add_executable(banjo_solver_probe src/app/solver_probe_main.cpp)
    target_link_libraries(banjo_solver_probe PRIVATE banjo_core)
    banjo_enable_warnings(banjo_solver_probe)

    add_executable(banjo_modal_fracture_record tools/modal_fracture_record.cpp)
    target_link_libraries(banjo_modal_fracture_record PRIVATE banjo_modal banjo_runtime nlohmann_json::nlohmann_json)
    target_compile_features(banjo_modal_fracture_record PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_modal_fracture_record)

    add_executable(banjo_glass_diagnostic tools/glass_shatter_diagnostic.cpp)
    target_link_libraries(banjo_glass_diagnostic PRIVATE banjo_runtime)
    target_compile_features(banjo_glass_diagnostic PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_glass_diagnostic)

    add_executable(banjo_quasistatic_probe src/app/quasistatic_probe_main.cpp)
    target_link_libraries(banjo_quasistatic_probe PRIVATE banjo_runtime nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_quasistatic_probe)
    add_library(banjo_fastlattice_scene src/fastlattice/TileImpactScene.cpp
                                       src/fastlattice/LiveWorld.cpp)
    target_link_libraries(banjo_fastlattice_scene PUBLIC banjo_fastlattice banjo_runtime PRIVATE nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_fastlattice_scene)
    add_executable(banjo_fast_lattice_run tools/fast_lattice_run.cpp)
    target_link_libraries(banjo_fast_lattice_run PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_fast_lattice_run)
    # The C face of the engine, and the only target meant to leave this tree.
    #
    # Everything else here is built to be linked from inside the project, with
    # C++ types in the interface and no promise that anything stays put. This
    # one is a shared library behind a flat C header: a version to check, a
    # handle to hold, and no exception crossing the boundary. Anything that can
    # call a C function can drive a world -- which was the gap. Before this, a
    # host either vendored the whole tree and built it in C++, or spoke to a
    # subprocess.
    add_library(banjo_c SHARED src/capi/banjo.cpp)
    target_link_libraries(banjo_c PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
    target_include_directories(banjo_c PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>)
    target_compile_definitions(banjo_c PRIVATE BANJO_BUILDING_SHARED INTERFACE BANJO_SHARED)
    set_target_properties(banjo_c PROPERTIES
        OUTPUT_NAME banjo
        # Hide everything the header does not declare, so the exported surface
        # is the header and nothing else.
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN ON
        # The ABI version, in the file name. A host linking against it says
        # which one it was built for, and two of them can sit side by side.
        SOVERSION 3
        VERSION 3.0.0
        WINDOWS_EXPORT_ALL_SYMBOLS OFF)
    banjo_enable_warnings(banjo_c)

    # What it takes to hand this to someone else: the library, the one header,
    # and a CMake package so `find_package(Banjo)` works in their tree. There
    # were no install rules at all before this, which is the practical reason
    # nothing outside this repository could use the engine.
    include(GNUInstallDirs)
    include(CMakePackageConfigHelpers)
    install(TARGETS banjo_c EXPORT BanjoTargets
            RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
            LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
            ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
    install(FILES include/banjo/banjo.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/banjo)
    install(EXPORT BanjoTargets NAMESPACE Banjo::
            DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/Banjo)
    write_basic_package_version_file(
        "${CMAKE_CURRENT_BINARY_DIR}/BanjoConfigVersion.cmake"
        VERSION 3.0.0 COMPATIBILITY SameMajorVersion)
    file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/BanjoConfig.cmake"
         "include(\"\${CMAKE_CURRENT_LIST_DIR}/BanjoTargets.cmake\")\n")
    install(FILES "${CMAKE_CURRENT_BINARY_DIR}/BanjoConfig.cmake"
                  "${CMAKE_CURRENT_BINARY_DIR}/BanjoConfigVersion.cmake"
            DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/Banjo)

    # A consumer, built the way a consumer builds: C, against the header only.
    # It is a test as much as an example -- if the header needs a C++ compiler
    # or a type the header does not declare, this stops compiling.
    add_executable(banjo_c_example examples/drop.c)
    target_link_libraries(banjo_c_example PRIVATE banjo_c)
    set_property(TARGET banjo_c_example PROPERTY C_STANDARD 99)

    add_test(NAME banjo_capi_tests COMMAND banjo_c_example --test)

    # The same library driven from a language that cannot read a C++ header.
    # ctypes gets no help from the compiler, so a wrong argument type is a
    # silent pointer truncation rather than an error, and only running it finds
    # that out. Skipped rather than failed when there is no Python, because a
    # C++ tree should not stop building for the want of an interpreter.
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(Python3_FOUND)
        add_test(NAME banjo_ffi_tests
                 COMMAND ${Python3_EXECUTABLE}
                         ${CMAKE_CURRENT_SOURCE_DIR}/tests/banjo_ffi_tests.py)
        set_tests_properties(banjo_ffi_tests PROPERTIES
            ENVIRONMENT "BANJO_LIBRARY=$<TARGET_FILE:banjo_c>")
        # The two ways the playground can hold a world, run against the same
        # scene and compared. Claiming they are interchangeable is easy; this
        # is the part that makes it true.
        # The room on /world: what it is made of, that it fits the lane, and
        # that a change the engine would refuse is refused where the thing that
        # made it can be told.
        # The MCP server, driven as a real subprocess through the real protocol.
        add_test(NAME banjo_mcp_tests
                 COMMAND ${Python3_EXECUTABLE}
                         ${CMAKE_CURRENT_SOURCE_DIR}/tests/banjo_mcp_tests.py)
        set_tests_properties(banjo_mcp_tests PROPERTIES
            ENVIRONMENT "BANJO_LIBRARY=$<TARGET_FILE:banjo_c>")
        add_test(NAME banjo_world_room_tests
                 COMMAND ${Python3_EXECUTABLE}
                         ${CMAKE_CURRENT_SOURCE_DIR}/tests/world_room_tests.py)
        add_test(NAME banjo_live_lanes_agree_tests
                 COMMAND ${Python3_EXECUTABLE}
                         ${CMAKE_CURRENT_SOURCE_DIR}/tests/live_lanes_agree_tests.py)
        set_tests_properties(banjo_live_lanes_agree_tests PROPERTIES
            ENVIRONMENT "BANJO_LIBRARY=$<TARGET_FILE:banjo_c>")
    endif()

    # A live scene, driven a line at a time: the playground talks to this instead
    # of asking for a recording and playing it back.
    add_executable(banjo_live_world_run tools/live_world_run.cpp)
    target_link_libraries(banjo_live_world_run PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_live_world_run)
    # Algorithm 3: precomputed multi-step propagators with causal-cone patching.
    add_executable(banjo_fracture_algo3 tools/fracture_algo3.cpp)
    target_link_libraries(banjo_fracture_algo3 PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_fracture_algo3)

    # Physics check (a) for the energy-scaled criterion: a pre-cracked strip in
    # tension, whose crack speed and dissipation per unit crack area have known
    # answers (docs/criterion-energy-scaled-checkpoint.md, section 5).
    add_executable(banjo_criterion_strip_probe tools/criterion_strip_probe.cpp)
    target_link_libraries(banjo_criterion_strip_probe PRIVATE banjo_fastlattice banjo_runtime nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_criterion_strip_probe)

    add_executable(banjo_headless src/app/headless_main.cpp)
    target_link_libraries(banjo_headless PRIVATE banjo_runtime)
    target_compile_features(banjo_headless PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_headless)
endif()

if(BANJO_BUILD_LAB)
    add_executable(banjo_continuum_lab src/viewer/continuum.cpp)
    target_link_libraries(banjo_continuum_lab PRIVATE raylib nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_continuum_lab)
    set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
    set(CUSTOMIZE_BUILD ON CACHE BOOL "" FORCE)
    # CUSTOMIZE_BUILD exposes every raylib SUPPORT_* switch, and in this build
    # several that config.h leaves off came through enabled. Two of them break
    # the interactive viewer: custom frame control removes the buffer swap,
    # input polling, and frame timing from EndDrawing(), so the window stays
    # black and GetFrameTime() is always zero; busy-wait pegs a core. Force
    # both off so the lab behaves the same as a default raylib build.
    set(SUPPORT_CUSTOM_FRAME_CONTROL OFF CACHE BOOL "" FORCE)
    set(SUPPORT_BUSY_WAIT_LOOP OFF CACHE BOOL "" FORCE)
    set(USE_AUDIO OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_X11 ON CACHE BOOL "" FORCE)
    set(GLFW_BUILD_WAYLAND OFF CACHE BOOL "" FORCE)

    FetchContent_Declare(
        raylib
        GIT_REPOSITORY https://github.com/raysan5/raylib.git
        GIT_TAG 6.0
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(raylib)
    include(cmake/GuardGlfwActiveWindow.cmake)

    add_executable(banjo_lab src/viewer/main.cpp)
    target_link_libraries(banjo_lab PRIVATE banjo_runtime raylib)
    target_compile_features(banjo_lab PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_lab)
    add_executable(banjo_bowl src/viewer/bowl.cpp src/viewer/fracture_view.cpp)
    target_link_libraries(banjo_bowl PRIVATE banjo_creator_runtime raylib)
    banjo_enable_warnings(banjo_bowl)
    add_executable(banjo_workshop src/viewer/workshop.cpp)
    target_link_libraries(banjo_workshop PRIVATE banjo_creator_assistant raylib nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_workshop)
    add_executable(banjo_starter src/viewer/starter.cpp)
    target_link_libraries(banjo_starter PRIVATE banjo_starter_runtime banjo_creator_assistant raylib nlohmann_json::nlohmann_json)
    banjo_enable_warnings(banjo_starter)
    if(MSVC)
        target_link_options(banjo_workshop PRIVATE "/MAP:${CMAKE_CURRENT_BINARY_DIR}/banjo_workshop.map")
    endif()
endif()

if(BANJO_BUILD_TESTS)
    add_executable(banjo_patch_pressure_tests tests/patch_pressure_tests.cpp)
    target_link_libraries(banjo_patch_pressure_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_patch_pressure_tests)
    add_test(NAME banjo_patch_pressure_tests COMMAND banjo_patch_pressure_tests)
    add_executable(banjo_small_strain_law_tests tests/small_strain_law_tests.cpp)
    target_link_libraries(banjo_small_strain_law_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_small_strain_law_tests)
    add_test(NAME banjo_small_strain_law_tests COMMAND banjo_small_strain_law_tests)
    add_executable(banjo_swept_sphere_triangle_tests tests/swept_sphere_triangle_tests.cpp)
    target_link_libraries(banjo_swept_sphere_triangle_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_swept_sphere_triangle_tests)
    add_test(NAME banjo_swept_sphere_triangle_tests COMMAND banjo_swept_sphere_triangle_tests)
    add_executable(banjo_sphere_patch_world_tests tests/sphere_patch_world_tests.cpp)
    target_link_libraries(banjo_sphere_patch_world_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_sphere_patch_world_tests)
    add_test(NAME banjo_sphere_patch_world_tests COMMAND banjo_sphere_patch_world_tests)
    add_executable(banjo_sphere_patch_advance_tests tests/sphere_patch_advance_tests.cpp)
    target_link_libraries(banjo_sphere_patch_advance_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_sphere_patch_advance_tests)
    add_test(NAME banjo_sphere_patch_advance_tests COMMAND banjo_sphere_patch_advance_tests)
    add_executable(banjo_sphere_patch_friction_tests tests/sphere_patch_friction_tests.cpp)
    target_link_libraries(banjo_sphere_patch_friction_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_sphere_patch_friction_tests)
    add_test(NAME banjo_sphere_patch_friction_tests COMMAND banjo_sphere_patch_friction_tests)
    add_executable(banjo_cohesive_facet_tests tests/cohesive_facet_tests.cpp)
    target_link_libraries(banjo_cohesive_facet_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_facet_tests)
    add_test(NAME banjo_cohesive_facet_tests COMMAND banjo_cohesive_facet_tests)
    add_executable(banjo_cohesive_assembly_tests tests/cohesive_assembly_tests.cpp)
    target_link_libraries(banjo_cohesive_assembly_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_assembly_tests)
    add_test(NAME banjo_cohesive_assembly_tests COMMAND banjo_cohesive_assembly_tests)
    add_executable(banjo_cohesive_dynamic_patch_tests tests/cohesive_dynamic_patch_tests.cpp)
    target_link_libraries(banjo_cohesive_dynamic_patch_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_dynamic_patch_tests)
    add_test(NAME banjo_cohesive_dynamic_patch_tests COMMAND banjo_cohesive_dynamic_patch_tests)
    add_executable(banjo_cohesive_sphere_world_tests tests/cohesive_sphere_world_tests.cpp)
    target_link_libraries(banjo_cohesive_sphere_world_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_sphere_world_tests)
    add_test(NAME banjo_cohesive_sphere_world_tests COMMAND banjo_cohesive_sphere_world_tests)
    add_executable(banjo_corotated_tet_tests tests/corotated_tet_tests.cpp)
    target_link_libraries(banjo_corotated_tet_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_corotated_tet_tests)
    add_test(NAME banjo_corotated_tet_tests COMMAND banjo_corotated_tet_tests)
    add_executable(banjo_corotated_cohesive_facet_tests tests/corotated_cohesive_facet_tests.cpp)
    target_link_libraries(banjo_corotated_cohesive_facet_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_corotated_cohesive_facet_tests)
    add_test(NAME banjo_corotated_cohesive_facet_tests COMMAND banjo_corotated_cohesive_facet_tests)
    add_executable(banjo_sphere_patch_snapshot_tests tests/sphere_patch_snapshot_tests.cpp)
    target_link_libraries(banjo_sphere_patch_snapshot_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_sphere_patch_snapshot_tests)
    add_test(NAME banjo_sphere_patch_snapshot_tests COMMAND banjo_sphere_patch_snapshot_tests)
    add_executable(banjo_sphere_patch_snapshot_codec_tests tests/sphere_patch_snapshot_codec_tests.cpp)
    target_link_libraries(banjo_sphere_patch_snapshot_codec_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_sphere_patch_snapshot_codec_tests)
    add_test(NAME banjo_sphere_patch_snapshot_codec_tests COMMAND banjo_sphere_patch_snapshot_codec_tests)
    add_executable(banjo_swept_segment_triangle_tests tests/swept_segment_triangle_tests.cpp)
    target_link_libraries(banjo_swept_segment_triangle_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_swept_segment_triangle_tests)
    add_test(NAME banjo_swept_segment_triangle_tests COMMAND banjo_swept_segment_triangle_tests)
    add_executable(banjo_paired_facet_contact_tests tests/paired_facet_contact_tests.cpp)
    target_link_libraries(banjo_paired_facet_contact_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_paired_facet_contact_tests)
    add_test(NAME banjo_paired_facet_contact_tests COMMAND banjo_paired_facet_contact_tests)
    add_executable(banjo_facet_closure_energy_tests tests/facet_closure_energy_tests.cpp)
    target_link_libraries(banjo_facet_closure_energy_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_facet_closure_energy_tests)
    add_test(NAME banjo_facet_closure_energy_tests COMMAND banjo_facet_closure_energy_tests)
    add_executable(banjo_tetrahedron_contact_impulse_tests tests/tetrahedron_contact_impulse_tests.cpp)
    target_link_libraries(banjo_tetrahedron_contact_impulse_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_tetrahedron_contact_impulse_tests)
    add_test(NAME banjo_tetrahedron_contact_impulse_tests COMMAND banjo_tetrahedron_contact_impulse_tests)
    add_executable(banjo_corotated_cohesive_dynamic_tests tests/corotated_cohesive_dynamic_tests.cpp)
    target_link_libraries(banjo_corotated_cohesive_dynamic_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_corotated_cohesive_dynamic_tests)
    add_test(NAME banjo_corotated_cohesive_dynamic_tests COMMAND banjo_corotated_cohesive_dynamic_tests)
    add_executable(banjo_cutting_tearing_coupon_tests tests/cutting_tearing_coupon_tests.cpp)
    target_link_libraries(banjo_cutting_tearing_coupon_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cutting_tearing_coupon_tests)
    add_test(NAME banjo_cutting_tearing_coupon_tests COMMAND banjo_cutting_tearing_coupon_tests)
    add_executable(banjo_segment_triangle_contact_tests tests/segment_triangle_contact_tests.cpp)
    target_link_libraries(banjo_segment_triangle_contact_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_segment_triangle_contact_tests)
    add_test(NAME banjo_segment_triangle_contact_tests COMMAND banjo_segment_triangle_contact_tests)
    add_executable(banjo_metal_unload_equilibrium_tests tests/metal_unload_equilibrium_tests.cpp)
    target_link_libraries(banjo_metal_unload_equilibrium_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_metal_unload_equilibrium_tests)
    add_test(NAME banjo_metal_unload_equilibrium_tests COMMAND banjo_metal_unload_equilibrium_tests)
    add_executable(banjo_fracture_overlap_tests tests/fracture_overlap_tests.cpp)
    target_link_libraries(banjo_fracture_overlap_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_fracture_overlap_tests)
    add_test(NAME banjo_fracture_overlap_tests COMMAND banjo_fracture_overlap_tests)
    add_executable(banjo_metal_dent_acceptance_tests tests/metal_dent_acceptance_tests.cpp)
    target_link_libraries(banjo_metal_dent_acceptance_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_metal_dent_acceptance_tests)
    add_test(NAME banjo_metal_dent_acceptance_tests COMMAND banjo_metal_dent_acceptance_tests)
    add_executable(banjo_fracture_component_state_tests tests/fracture_component_state_tests.cpp)
    target_link_libraries(banjo_fracture_component_state_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_fracture_component_state_tests)
    add_test(NAME banjo_fracture_component_state_tests COMMAND banjo_fracture_component_state_tests)
    add_executable(banjo_fracture_topology_tests tests/fracture_topology_tests.cpp)
    target_link_libraries(banjo_fracture_topology_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_fracture_topology_tests)
    add_test(NAME banjo_fracture_topology_tests COMMAND banjo_fracture_topology_tests)
    add_executable(banjo_dynamic_patch_tests tests/dynamic_patch_tests.cpp)
    target_link_libraries(banjo_dynamic_patch_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_dynamic_patch_tests)
    add_test(NAME banjo_dynamic_patch_tests COMMAND banjo_dynamic_patch_tests)
    add_executable(banjo_small_strain_patch_tests tests/small_strain_patch_tests.cpp)
    target_link_libraries(banjo_small_strain_patch_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_small_strain_patch_tests)
    add_test(NAME banjo_small_strain_patch_tests COMMAND banjo_small_strain_patch_tests)
    add_executable(banjo_numeric_state_delta_tests tests/numeric_state_delta_tests.cpp)
    target_link_libraries(banjo_numeric_state_delta_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_numeric_state_delta_tests)
    add_test(NAME banjo_numeric_state_delta_tests COMMAND banjo_numeric_state_delta_tests)
    add_executable(banjo_property_variation_tests tests/property_variation_tests.cpp)
    target_link_libraries(banjo_property_variation_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_property_variation_tests)
    add_test(NAME banjo_property_variation_tests COMMAND banjo_property_variation_tests)
    add_executable(banjo_plasticity_tests tests/plasticity_tests.cpp)
    target_link_libraries(banjo_plasticity_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_plasticity_tests)
    add_test(NAME banjo_plasticity_tests COMMAND banjo_plasticity_tests)
    add_executable(banjo_cell_skin_tests tests/cell_skin_tests.cpp)
    target_link_libraries(banjo_cell_skin_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cell_skin_tests)
    add_test(NAME banjo_cell_skin_tests COMMAND banjo_cell_skin_tests)
    add_executable(banjo_fracture_preview_tests tests/fracture_preview_tests.cpp)
    target_link_libraries(banjo_fracture_preview_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_fracture_preview_tests)
    add_test(NAME banjo_fracture_preview_tests COMMAND banjo_fracture_preview_tests)
    add_executable(banjo_rupture_cascade_tests tests/rupture_cascade_tests.cpp)
    target_link_libraries(banjo_rupture_cascade_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_rupture_cascade_tests)
    add_test(NAME banjo_rupture_cascade_tests COMMAND banjo_rupture_cascade_tests)
    add_executable(banjo_energy_rupture_tests tests/energy_rupture_tests.cpp)
    target_link_libraries(banjo_energy_rupture_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_energy_rupture_tests)
    add_test(NAME banjo_energy_rupture_tests COMMAND banjo_energy_rupture_tests)
    if(TARGET banjo_runtime_cohesive_probe AND DOUBLE_PRECISION)
        add_test(NAME banjo_runtime_cohesive_accuracy COMMAND banjo_runtime_cohesive_probe
            "${CMAKE_CURRENT_BINARY_DIR}/runtime-cohesive-accuracy.csv" --require-accuracy)
        add_test(NAME banjo_runtime_tension_accuracy COMMAND banjo_runtime_cohesive_probe
            "${CMAKE_CURRENT_BINARY_DIR}/runtime-tension-accuracy.csv" --require-accuracy --jolt-surfaces)
    endif()
    add_executable(banjo_cohesive_spatial_tests tests/cohesive_spatial_tests.cpp)
    target_link_libraries(banjo_cohesive_spatial_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_spatial_tests)
    add_test(NAME banjo_cohesive_spatial_tests COMMAND banjo_cohesive_spatial_tests)
    add_executable(banjo_rigid_attachment_tests tests/rigid_attachment_tests.cpp)
    target_link_libraries(banjo_rigid_attachment_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_rigid_attachment_tests)
    add_test(NAME banjo_rigid_attachment_tests COMMAND banjo_rigid_attachment_tests)
    add_executable(banjo_cohesive_rigid_tests tests/cohesive_rigid_tests.cpp)
    target_link_libraries(banjo_cohesive_rigid_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_rigid_tests)
    add_test(NAME banjo_cohesive_rigid_tests COMMAND banjo_cohesive_rigid_tests)
    add_executable(banjo_cohesive_pair_tests tests/cohesive_pair_tests.cpp)
    target_link_libraries(banjo_cohesive_pair_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_pair_tests)
    add_test(NAME banjo_cohesive_pair_tests COMMAND banjo_cohesive_pair_tests)
    add_executable(banjo_cohesive_interface_tests tests/cohesive_interface_tests.cpp)
    target_link_libraries(banjo_cohesive_interface_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_cohesive_interface_tests)
    add_test(NAME banjo_cohesive_interface_tests COMMAND banjo_cohesive_interface_tests)
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

    add_executable(banjo_contact_tests tests/contact_mechanics_tests.cpp)
    target_link_libraries(banjo_contact_tests PRIVATE banjo_core)
    target_compile_features(banjo_contact_tests PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_contact_tests)
    add_test(NAME banjo_contact_tests COMMAND banjo_contact_tests)

    add_executable(banjo_constitutive_tests tests/constitutive_tests.cpp)
    target_link_libraries(banjo_constitutive_tests PRIVATE banjo_core)
    target_compile_features(banjo_constitutive_tests PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_constitutive_tests)
    add_test(NAME banjo_constitutive_tests COMMAND banjo_constitutive_tests)

    add_executable(banjo_bond_failure_orientation_tests tests/bond_failure_orientation_tests.cpp)
    target_link_libraries(banjo_bond_failure_orientation_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_bond_failure_orientation_tests)
    add_test(NAME banjo_bond_failure_orientation_tests COMMAND banjo_bond_failure_orientation_tests)
    add_executable(banjo_material_stage_tests tests/material_stage_tests.cpp)
    target_link_libraries(banjo_material_stage_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_material_stage_tests)
    add_test(NAME banjo_material_stage_tests COMMAND banjo_material_stage_tests)

    add_executable(banjo_implicit_fracture_tests tests/implicit_fracture_tests.cpp)
    target_link_libraries(banjo_implicit_fracture_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_implicit_fracture_tests)
    add_test(NAME banjo_implicit_fracture_tests COMMAND banjo_implicit_fracture_tests)
    add_executable(banjo_modal_eigen_tests tests/modal_eigen_tests.cpp)
    target_link_libraries(banjo_modal_eigen_tests PRIVATE banjo_modal)
    banjo_enable_warnings(banjo_modal_eigen_tests)
    add_test(NAME banjo_modal_eigen_tests COMMAND banjo_modal_eigen_tests)
    add_executable(banjo_modal_fracture_tests tests/modal_fracture_tests.cpp)
    target_link_libraries(banjo_modal_fracture_tests PRIVATE banjo_modal)
    banjo_enable_warnings(banjo_modal_fracture_tests)
    add_test(NAME banjo_modal_fracture_tests COMMAND banjo_modal_fracture_tests)
    add_executable(banjo_quasistatic_fracture_tests tests/quasistatic_fracture_tests.cpp)
    target_link_libraries(banjo_quasistatic_fracture_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_quasistatic_fracture_tests)
    add_test(NAME banjo_quasistatic_fracture_tests COMMAND banjo_quasistatic_fracture_tests)
    add_executable(banjo_conservative_step_tests tests/conservative_step_tests.cpp)
    target_link_libraries(banjo_conservative_step_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_conservative_step_tests)
    add_test(NAME banjo_conservative_step_tests COMMAND banjo_conservative_step_tests)

    add_executable(banjo_conservative_advance_tests tests/conservative_advance_tests.cpp)
    target_link_libraries(banjo_conservative_advance_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_conservative_advance_tests)
    add_test(NAME banjo_conservative_advance_tests COMMAND banjo_conservative_advance_tests)

    add_executable(banjo_compliant_step_tests tests/compliant_step_tests.cpp)
    target_link_libraries(banjo_compliant_step_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_compliant_step_tests)
    add_test(NAME banjo_compliant_step_tests COMMAND banjo_compliant_step_tests)

    add_executable(banjo_compliant_advance_tests tests/compliant_advance_tests.cpp)
    target_link_libraries(banjo_compliant_advance_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_compliant_advance_tests)
    add_test(NAME banjo_compliant_advance_tests COMMAND banjo_compliant_advance_tests)

    add_executable(banjo_outcome_tests tests/material_outcome_tests.cpp)
    target_link_libraries(banjo_outcome_tests PRIVATE banjo_core)
    target_compile_features(banjo_outcome_tests PRIVATE cxx_std_23)
    banjo_enable_warnings(banjo_outcome_tests)
    add_test(NAME banjo_outcome_tests COMMAND banjo_outcome_tests)

    add_executable(banjo_conservative_contact_tests tests/conservative_contact_tests.cpp)
    target_link_libraries(banjo_conservative_contact_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_conservative_contact_tests)
    add_test(NAME banjo_conservative_contact_tests COMMAND banjo_conservative_contact_tests)

    if(TARGET banjo_runtime)
        add_executable(banjo_spring_trial_tests tests/spring_trial_tests.cpp)
        target_link_libraries(banjo_spring_trial_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_spring_trial_tests)
        add_test(NAME banjo_spring_trial_tests COMMAND banjo_spring_trial_tests)
        add_executable(banjo_reversible_trial_tests tests/reversible_trial_tests.cpp)
        target_link_libraries(banjo_reversible_trial_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_reversible_trial_tests)
        add_test(NAME banjo_reversible_trial_tests COMMAND banjo_reversible_trial_tests)
        add_executable(banjo_runtime_tension_contact_tests tests/runtime_tension_contact_tests.cpp)
        target_link_libraries(banjo_runtime_tension_contact_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_runtime_tension_contact_tests)
        add_test(NAME banjo_runtime_tension_contact_tests COMMAND banjo_runtime_tension_contact_tests)
        add_executable(banjo_precision_conversion_tests tests/precision_conversion_tests.cpp)
        target_link_libraries(banjo_precision_conversion_tests PRIVATE banjo_precision_conversion nlohmann_json::nlohmann_json)
        banjo_enable_warnings(banjo_precision_conversion_tests)
        add_test(NAME banjo_precision_conversion_tests COMMAND banjo_precision_conversion_tests)
        add_executable(banjo_bowl_tests tests/bowl_lab_tests.cpp)
        target_link_libraries(banjo_bowl_tests PRIVATE banjo_creator_runtime nlohmann_json::nlohmann_json)
        banjo_enable_warnings(banjo_bowl_tests)
        add_test(NAME banjo_bowl_tests COMMAND banjo_bowl_tests)
        add_executable(banjo_starter_tests tests/starter_world_tests.cpp)
        target_link_libraries(banjo_starter_tests PRIVATE banjo_starter_runtime nlohmann_json::nlohmann_json)
        banjo_enable_warnings(banjo_starter_tests)
        add_test(NAME banjo_starter_tests COMMAND banjo_starter_tests)
        add_executable(banjo_assistant_tests tests/creator_assistant_tests.cpp)
        target_link_libraries(banjo_assistant_tests PRIVATE banjo_creator_assistant nlohmann_json::nlohmann_json)
        banjo_enable_warnings(banjo_assistant_tests)
        add_test(NAME banjo_assistant_tests COMMAND banjo_assistant_tests)
        add_executable(banjo_creator_tests tests/creator_world_tests.cpp)
        target_link_libraries(banjo_creator_tests PRIVATE banjo_creator_runtime nlohmann_json::nlohmann_json)
        banjo_enable_warnings(banjo_creator_tests)
        add_test(NAME banjo_creator_tests COMMAND banjo_creator_tests)

        add_executable(banjo_transfer_tests tests/transfer_accounting_tests.cpp)
        target_link_libraries(banjo_transfer_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_transfer_tests)
        add_test(NAME banjo_transfer_tests COMMAND banjo_transfer_tests)

        add_executable(banjo_contact_ownership_tests tests/contact_ownership_tests.cpp)
        target_link_libraries(banjo_contact_ownership_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_contact_ownership_tests)
        add_test(NAME banjo_contact_ownership_tests COMMAND banjo_contact_ownership_tests)

        add_executable(banjo_pair_impulse_tests tests/pair_impulse_tests.cpp)
        target_link_libraries(banjo_pair_impulse_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_pair_impulse_tests)
        add_test(NAME banjo_pair_impulse_tests COMMAND banjo_pair_impulse_tests)

        add_executable(banjo_tetrahedron_contact_tests tests/tetrahedron_contact_tests.cpp)
        target_link_libraries(banjo_tetrahedron_contact_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_tetrahedron_contact_tests)
        add_test(NAME banjo_tetrahedron_contact_tests COMMAND banjo_tetrahedron_contact_tests)

        add_executable(banjo_criterion_energy_tests tests/criterion_energy_tests.cpp)
        target_link_libraries(banjo_criterion_energy_tests PRIVATE banjo_fastlattice)
        banjo_enable_warnings(banjo_criterion_energy_tests)
        add_test(NAME banjo_criterion_energy_tests COMMAND banjo_criterion_energy_tests)

        if(TARGET banjo_fastlattice_scene)
            add_executable(banjo_fast_lattice_tests tests/fast_lattice_tests.cpp)
            target_link_libraries(banjo_fast_lattice_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_fast_lattice_tests)
            add_test(NAME banjo_fast_lattice_tests COMMAND banjo_fast_lattice_tests)

            # A scene that keeps running instead of being run: stepping, reading
            # where everything is, and taking hold of something.
            add_executable(banjo_live_world_tests tests/live_world_tests.cpp)
            target_link_libraries(banjo_live_world_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_live_world_tests)
            add_test(NAME banjo_live_world_tests COMMAND banjo_live_world_tests)

            # Breaking a piece that has already broken: the trigger against its
            # own derivation, the state a fragment carries back into the
            # lattice, the conservation of the round trip, backend parity
            # through a re-entry and the unchanged control.
            add_executable(banjo_refracture_tests tests/refracture_tests.cpp)
            target_link_libraries(banjo_refracture_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_refracture_tests)
            add_test(NAME banjo_refracture_tests COMMAND banjo_refracture_tests)

            # Axial plasticity in the lattice bond solve: the constitutive law
            # against material/NetworkMaterial.cpp, the coupon's known answer,
            # the energy ledger and backend parity through a scene that yields.
            add_executable(banjo_lattice_plasticity_tests tests/lattice_plasticity_tests.cpp)
            target_link_libraries(banjo_lattice_plasticity_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_lattice_plasticity_tests)
            add_test(NAME banjo_lattice_plasticity_tests COMMAND banjo_lattice_plasticity_tests)

            # Algorithm 3: the propagator premises and the exact parallel backend.
            add_executable(banjo_fracture_algo3_tests tests/fracture_algo3_tests.cpp)
            target_link_libraries(banjo_fracture_algo3_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_fracture_algo3_tests)
            add_test(NAME banjo_fracture_algo3_tests COMMAND banjo_fracture_algo3_tests)
        endif()

        add_executable(banjo_runtime_tests tests/runtime_dynamics_tests.cpp)
        target_link_libraries(banjo_runtime_tests PRIVATE banjo_runtime)
        target_compile_features(banjo_runtime_tests PRIVATE cxx_std_23)
        banjo_enable_warnings(banjo_runtime_tests)
        add_test(NAME banjo_runtime_tests COMMAND banjo_runtime_tests)
    endif()
endif()

if(BANJO_BUILD_TESTS AND TARGET banjo_creator_runtime)
 add_executable(banjo_bonded_bowl_tests tests/bonded_bowl_tests.cpp)
 target_link_libraries(banjo_bonded_bowl_tests PRIVATE banjo_creator_runtime)
 add_test(NAME banjo_bonded_bowl_tests COMMAND banjo_bonded_bowl_tests)
endif()

if(BANJO_BUILD_TESTS AND TARGET banjo_platform)
 add_executable(banjo_thermal_burn_acceptance tools/thermal_burn_acceptance.cpp)
 add_executable(banjo_thermal_experiment_cli tools/thermal_experiment_cli.cpp)
 add_executable(banjo_cohesive_sphere_probe tools/cohesive_sphere_probe.cpp)
 target_link_libraries(banjo_cohesive_sphere_probe PRIVATE banjo_core nlohmann_json::nlohmann_json)
 banjo_enable_warnings(banjo_cohesive_sphere_probe)
 target_link_libraries(banjo_thermal_experiment_cli PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 banjo_enable_warnings(banjo_thermal_experiment_cli)
 target_link_libraries(banjo_thermal_burn_acceptance PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 banjo_enable_warnings(banjo_thermal_burn_acceptance)
 add_executable(banjo_thermal_burn_acceptance_tests tests/thermal_burn_acceptance_tests.cpp)
 target_link_libraries(banjo_thermal_burn_acceptance_tests PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 banjo_enable_warnings(banjo_thermal_burn_acceptance_tests)
 add_test(NAME banjo_thermal_burn_acceptance_tests COMMAND banjo_thermal_burn_acceptance_tests)
 add_executable(banjo_thermal_frontier_tests tests/thermal_frontier_tests.cpp)
 target_link_libraries(banjo_thermal_frontier_tests PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 banjo_enable_warnings(banjo_thermal_frontier_tests)
 add_test(NAME banjo_thermal_frontier_tests COMMAND banjo_thermal_frontier_tests)
 add_executable(banjo_network_adaptive_tests tests/network_adaptive_tests.cpp)
 target_link_libraries(banjo_network_adaptive_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_network_adaptive_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 banjo_enable_warnings(banjo_network_adaptive_tests)
 add_test(NAME banjo_network_adaptive_tests COMMAND banjo_network_adaptive_tests)
 add_executable(banjo_thermal_region_join_tests tests/thermal_region_join_tests.cpp)
 target_link_libraries(banjo_thermal_region_join_tests PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 add_test(NAME banjo_thermal_region_join_tests COMMAND banjo_thermal_region_join_tests)
 add_executable(banjo_network_skin_tests tests/network_skin_tests.cpp)
 target_link_libraries(banjo_network_skin_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_network_skin_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_network_skin_tests COMMAND banjo_network_skin_tests)
 add_executable(banjo_world_package_tests tests/world_package_tests.cpp)
 target_link_libraries(banjo_world_package_tests PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_world_package_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_world_package_tests COMMAND banjo_world_package_tests)
 add_executable(banjo_enthalpy_law_tests tests/enthalpy_law_tests.cpp)
 target_link_libraries(banjo_enthalpy_law_tests PRIVATE banjo_core)
 add_test(NAME banjo_enthalpy_law_tests COMMAND banjo_enthalpy_law_tests)
 add_executable(banjo_thermal_kernel_tests tests/thermal_kernel_tests.cpp)
 target_link_libraries(banjo_thermal_kernel_tests PRIVATE banjo_core)
 add_test(NAME banjo_thermal_kernel_tests COMMAND banjo_thermal_kernel_tests)
 add_executable(banjo_sparse_world_tests tests/sparse_world_tests.cpp)
 target_link_libraries(banjo_sparse_world_tests PRIVATE banjo_sparse_world nlohmann_json::nlohmann_json)
 add_test(NAME banjo_sparse_world_tests COMMAND banjo_sparse_world_tests)
 add_executable(banjo_resolution_budget_tests tests/resolution_budget_tests.cpp)
 target_link_libraries(banjo_resolution_budget_tests PRIVATE banjo_core)
 add_test(NAME banjo_resolution_budget_tests COMMAND banjo_resolution_budget_tests)
 add_executable(banjo_network_material_tests tests/network_material_tests.cpp)
 target_link_libraries(banjo_network_material_tests PRIVATE banjo_core)
 add_test(NAME banjo_network_material_tests COMMAND banjo_network_material_tests)
 add_executable(banjo_network_runtime_tests tests/network_runtime_tests.cpp)
 target_link_libraries(banjo_network_runtime_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_network_runtime_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_network_runtime_tests COMMAND banjo_network_runtime_tests)
 # The network lane now runs on its own stability clock, several hundred
 # internal solves per host tick, so these multi-scenario 720-step runs cost
 # roughly an hour each rather than seconds. Coverage is unchanged; only the
 # price is. See docs/network-at-rest-stability-checkpoint.md.
 # The adaptive suite's tomato fixture is fully resolved under the 8,192-substep
 # cap and takes about 18 minutes, past ctest's default.
 set_tests_properties(banjo_network_skin_tests banjo_network_runtime_tests
     banjo_network_adaptive_tests
     PROPERTIES TIMEOUT 7200)
 add_executable(banjo_material_showcase_tests tests/material_showcase_tests.cpp)
 target_link_libraries(banjo_material_showcase_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_material_showcase_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_material_showcase_tests COMMAND banjo_material_showcase_tests)
 # Same stability clock as the skin and runtime suites: about an hour.
 set_tests_properties(banjo_material_showcase_tests PROPERTIES TIMEOUT 7200)
 add_executable(banjo_contact_capacity_tests tests/contact_capacity_tests.cpp)
 target_link_libraries(banjo_contact_capacity_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_contact_capacity_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_contact_capacity_tests COMMAND banjo_contact_capacity_tests)
 # Three 7^3 matter balls and a twice-stepped panel, fully resolved under the
 # substep cap: about 34 minutes (2,039 s measured).
 set_tests_properties(banjo_contact_capacity_tests PROPERTIES TIMEOUT 7200)
 add_executable(banjo_network_spring_tests tests/network_spring_tests.cpp)
 target_link_libraries(banjo_network_spring_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 add_test(NAME banjo_network_spring_tests COMMAND banjo_network_spring_tests)
 add_executable(banjo_compiled_runtime_tests tests/compiled_runtime_tests.cpp)
 target_link_libraries(banjo_compiled_runtime_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_compiled_runtime_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_compiled_runtime_tests COMMAND banjo_compiled_runtime_tests)
 add_executable(banjo_compiled_object_tests tests/compiled_object_tests.cpp)
 target_link_libraries(banjo_compiled_object_tests PRIVATE banjo_platform)
 add_test(NAME banjo_compiled_object_tests COMMAND banjo_compiled_object_tests)
 add_executable(banjo_platform_tests tests/platform_tests.cpp)
 target_link_libraries(banjo_platform_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 add_test(NAME banjo_platform_tests COMMAND banjo_platform_tests)
endif()

if(TARGET raylib AND TARGET banjo_platform)
 add_executable(banjo_world_lab src/viewer/world.cpp)
 target_link_libraries(banjo_world_lab PRIVATE banjo_sparse_world raylib nlohmann_json::nlohmann_json)
 banjo_enable_warnings(banjo_world_lab)
 add_executable(banjo_network_lab src/viewer/runtime.cpp)
 target_compile_definitions(banjo_network_lab PRIVATE BANJO_NETWORK_LAB=1)
 target_link_libraries(banjo_network_lab PRIVATE banjo_platform raylib nlohmann_json::nlohmann_json)
 add_executable(banjo_runtime_lab src/viewer/runtime.cpp)
 target_link_libraries(banjo_runtime_lab PRIVATE banjo_platform raylib nlohmann_json::nlohmann_json)
 add_executable(banjo_platform_lab src/viewer/platform.cpp)
 target_link_libraries(banjo_platform_lab PRIVATE banjo_platform raylib nlohmann_json::nlohmann_json)
endif()
