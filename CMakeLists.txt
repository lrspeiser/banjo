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
    src/physics/FractureComponentState.cpp
    src/physics/FractureTopology.cpp
    src/physics/CohesivePair.cpp
    src/physics/CohesiveSpatialPair.cpp
    src/physics/CohesiveRigidPair.cpp
    src/physics/ConservativeStep.cpp
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

if(BANJO_BUILD_PRECOMPUTE)
    add_executable(banjo_phase_pair_benchmark tools/phase_pair_benchmark.cpp)
    target_link_libraries(banjo_phase_pair_benchmark PRIVATE banjo_core)
    banjo_enable_warnings(banjo_phase_pair_benchmark)
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

    add_executable(banjo_material_stage_tests tests/material_stage_tests.cpp)
    target_link_libraries(banjo_material_stage_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_material_stage_tests)
    add_test(NAME banjo_material_stage_tests COMMAND banjo_material_stage_tests)

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
 add_executable(banjo_material_showcase_tests tests/material_showcase_tests.cpp)
 target_link_libraries(banjo_material_showcase_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_material_showcase_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_material_showcase_tests COMMAND banjo_material_showcase_tests)
 add_executable(banjo_contact_capacity_tests tests/contact_capacity_tests.cpp)
 target_link_libraries(banjo_contact_capacity_tests PRIVATE banjo_platform nlohmann_json::nlohmann_json)
 target_compile_definitions(banjo_contact_capacity_tests PRIVATE BANJO_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
 add_test(NAME banjo_contact_capacity_tests COMMAND banjo_contact_capacity_tests)
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
