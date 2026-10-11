cmake_minimum_required(VERSION 3.25)

project(
    banjo
    VERSION 0.7.0
    DESCRIPTION "A matter-first runtime for editable-physics worlds"
    LANGUAGES C CXX)

option(BANJO_BUILD_TESTS "Build Banjo unit tests" ON)
option(BANJO_JOLT_CONTINUOUS_SMALL_ROTATION "Experimental: integrate native angular steps below one microradian" OFF)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
# Position-independent code everywhere, Jolt included: set before any target
# and any fetched dependency.
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
# One floating-point model for everything linked into the engine, Jolt
# included -- banjo-cpu-precise-v1: /fp:precise, or -fno-fast-math
# -ffp-contract=off -- and a build that audits the commands CMake generated
# before it compiles anything. Before any target and any fetched dependency, for
# the same reason as the line above. Why, and what it cost:
# cmake/FloatingPointModel.cmake and docs/floating-point-model.md.
include(cmake/FloatingPointModel.cmake)

function(banjo_enable_warnings target)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive-)
    else()
        target_compile_options(
            ${target}
            PRIVATE -Wall -Wextra -Wpedantic -Wconversion -Wshadow)
    endif()
endfunction()

add_library(banjo_friction_block src/physics/ContactFrictionBlock.cpp src/physics/ContactNormalBlock.cpp)
target_include_directories(banjo_friction_block PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
banjo_enable_warnings(banjo_friction_block)

add_library(
    banjo_core
    src/material/MaterialCompiler.cpp
    src/material/MaterialCatalog.cpp
    src/material/NetworkMaterial.cpp
    src/material/Plasticity.cpp
    src/material/ConnectorPlasticity.cpp
    src/material/SmallStrainLaw.cpp
    src/physics/SmallStrainPatch.cpp
    src/physics/DynamicPatch.cpp
    src/physics/SweptSphereTriangle.cpp
    src/physics/BoxSweep.cpp
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
    src/physics/RotationStrain.cpp
    src/physics/MaterialWrench.cpp
    src/physics/RigidStepWork.cpp
    src/physics/MechanicalAccounting.cpp
    src/physics/DoubleRigidDynamics.cpp
    src/physics/DoubleFixedSource.cpp
    src/physics/RollingKinematics.cpp
    src/physics/SphereMaterialContact.cpp
    src/physics/PointRigidContact.cpp
    src/physics/MaterialContactStencil.cpp
    src/physics/FixedAssemblyContact.cpp
    src/physics/ForceContactPhase.cpp
    src/physics/GripPull.cpp
    src/fracture/ActivationPolicy.cpp
    src/fracture/FracturePreview.cpp
    src/fracture/RuptureCascade.cpp
    src/fracture/EnergyRupture.cpp
    src/fracture/BondFailure.cpp
    src/fracture/QuasiStaticFracture.cpp
    src/fracture/SustainedLoad.cpp
    src/fracture/PieceGeometry.cpp
    src/fracture/BrittleBondSolver.cpp
    src/fracture/ConnectedComponents.cpp
    src/fracture/FragmentMassProperties.cpp
    src/fracture/FragmentGeometry.cpp
    src/fracture/CellSkin.cpp
    src/prediction/BallScenarioProjection.cpp
    src/prediction/ScenarioCache.cpp
    src/precompute/MaterialOutcome.cpp
    src/numeric/FpProfile.cpp)

target_include_directories(banjo_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(banjo_core PUBLIC banjo_friction_block)
# The profile's name, for what the engine reports and what its numerical caches
# are keyed by (src/numeric/FpProfile.hpp). Public, so every object sees the same.
target_compile_definitions(banjo_core PUBLIC BANJO_FP_PROFILE="${BANJO_FP_PROFILE}")
target_compile_features(banjo_core PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_core)

# The fast explicit lattice lane: the CPU lane's physics on a colour-parallel
# schedule, which the live world's breaking runs on.
add_library(
    banjo_fastlattice
    src/matter/BoxLattice.cpp
    src/matter/LatticeMerge.cpp
    src/fastlattice/LatticeSchedule.cpp
    src/fastlattice/FastLattice.cpp
    src/fastlattice/CpuLatticeBackend.cpp
    src/fastlattice/MaterialContactRegion.cpp
    src/fastlattice/DoubleFixedContact.cpp
    src/fastlattice/ParallelCpuLatticeBackend.cpp
    src/fastlattice/Refracture.cpp
    src/fastlattice/SolidMatterPatch.cpp
    src/fastlattice/ConstituentPartition.cpp
    src/fastlattice/Propagator.cpp)
target_link_libraries(banjo_fastlattice PUBLIC banjo_core)
target_compile_features(banjo_fastlattice PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_fastlattice)
# The CPU backend only: the CUDA backend went with the labs. The factory
# throws a clear error when a GPU is asked for, never a no-op.
target_sources(banjo_fastlattice PRIVATE src/fastlattice/CudaLatticeUnavailable.cpp)

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
target_link_libraries(Jolt PRIVATE banjo_friction_block)
include(cmake/JoltForceObservation.cmake)
include(cmake/JoltFrictionBlock.cmake)
banjo_jolt_force_observation(Jolt "${joltphysics_SOURCE_DIR}")
banjo_jolt_friction_block(Jolt "${joltphysics_SOURCE_DIR}")
if(BANJO_JOLT_CONTINUOUS_SMALL_ROTATION)
    include(cmake/JoltSmallRotation.cmake)
    banjo_jolt_continuous_small_rotation(Jolt "${joltphysics_SOURCE_DIR}")
endif()
# One file of ours compiled inside Jolt's own target, with Jolt's own flags,
# so banjo_fp_profile_tests can ask what Jolt's objects actually do with a
# NaN, an infinity, a signed zero and a product that could be fused.
target_sources(Jolt PRIVATE src/numeric/FpProbeJolt.cpp)

add_library(
    banjo_runtime
    src/physics/TetrahedronContact.cpp
    src/rigid/DrumRope.cpp
    src/rigid/JoltWorld.cpp
    src/rigid/RigidComponent.cpp
    src/rigid/LogFaceSpring.cpp
    src/sim/RollingBallExperiment.cpp
    src/numeric/FpProbeRuntime.cpp)
target_include_directories(banjo_runtime PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(banjo_runtime PUBLIC banjo_core Jolt)
# The drum's rope (rigid/DrumRope.cpp) is a Jolt constraint of our own, a
# class derived from JPH::TwoBodyConstraint, so it is compiled with Jolt's
# RTTI setting. Jolt is built without RTTI (CPP_RTTI_ENABLED), so its
# classes have no type information, and a class of ours derived from one
# and built with RTTI asks for its base's: GCC's link failed for want of
# `typeinfo for JPH::TwoBodyConstraint`. MSVC linked it; the rule is the
# same for both.
#
# Its floating-point model is everyone's (cmake/FloatingPointModel.cmake).
# It was once given Jolt's /fp:fast here, after its copy of Jolt's
# AxisConstraintPart replaced Jolt's own and moved a cut in
# banjo_blade_tests from 4.676 J to 4.192 J; that mended its own copies and
# left JoltWorld.cpp's and TetrahedronContact.cpp's as they were.
if (NOT CPP_RTTI_ENABLED)
    if (MSVC)
        set_source_files_properties(src/rigid/DrumRope.cpp src/rigid/LogFaceSpring.cpp PROPERTIES COMPILE_OPTIONS "/GR-")
    else()
        set_source_files_properties(src/rigid/DrumRope.cpp src/rigid/LogFaceSpring.cpp PROPERTIES COMPILE_OPTIONS "-fno-rtti")
    endif()
endif()
target_compile_features(banjo_runtime PUBLIC cxx_std_23)
banjo_enable_warnings(banjo_runtime)

# Structured creator input is parsed independently of the language model.
set(JSON_BuildTests OFF CACHE BOOL "" FORCE)
set(JSON_Install OFF CACHE BOOL "" FORCE)
FetchContent_Declare(nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG 65ee68451d8eb2b5f3a30b410476ab83deb3289b)
FetchContent_MakeAvailable(nlohmann_json)

# Python and Node run the machine suites and the floating-point audit;
# without them those tests are left out, never passed.
find_package(Python3 COMPONENTS Interpreter QUIET)
find_program(BANJO_NODE_EXECUTABLE node)

if(BANJO_BUILD_TESTS)
    add_executable(banjo_rigid_component_tests tests/rigid_component_tests.cpp)
    target_link_libraries(banjo_rigid_component_tests PRIVATE banjo_runtime)
    banjo_enable_warnings(banjo_rigid_component_tests)
    add_test(NAME banjo_rigid_component_tests COMMAND banjo_rigid_component_tests)
    add_executable(banjo_state_recorder_tests tests/state_recorder_tests.cpp)
    target_link_libraries(banjo_state_recorder_tests PRIVATE banjo_core Jolt)
    banjo_enable_warnings(banjo_state_recorder_tests)
    add_test(NAME banjo_state_recorder_tests COMMAND banjo_state_recorder_tests)
    add_executable(banjo_rotation_strain_tests tests/rotation_strain_tests.cpp)
    add_executable(banjo_rigid_step_work_tests tests/rigid_step_work_tests.cpp)
    add_executable(banjo_contact_friction_block_tests tests/contact_friction_block_tests.cpp)
    target_link_libraries(banjo_contact_friction_block_tests PRIVATE banjo_friction_block)
    banjo_enable_warnings(banjo_contact_friction_block_tests)
    add_test(NAME banjo_contact_friction_block_tests COMMAND banjo_contact_friction_block_tests)
    add_executable(banjo_contact_normal_block_tests tests/contact_normal_block_tests.cpp)
    add_executable(banjo_box_sweep_tests tests/box_sweep_tests.cpp)
    target_link_libraries(banjo_box_sweep_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_box_sweep_tests)
    add_test(NAME banjo_box_sweep_tests COMMAND banjo_box_sweep_tests)
    target_link_libraries(banjo_contact_normal_block_tests PRIVATE banjo_friction_block)
    banjo_enable_warnings(banjo_contact_normal_block_tests)
    add_test(NAME banjo_contact_normal_block_tests COMMAND banjo_contact_normal_block_tests)
    set_tests_properties(banjo_contact_normal_block_tests PROPERTIES TIMEOUT 60)
    target_link_libraries(banjo_rigid_step_work_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_rigid_step_work_tests)
    add_test(NAME banjo_rigid_step_work_tests COMMAND banjo_rigid_step_work_tests)
    target_link_libraries(banjo_rotation_strain_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_rotation_strain_tests)
    add_test(NAME banjo_rotation_strain_tests COMMAND banjo_rotation_strain_tests)
endif()

# The thermochemical network: matter inventories, reactions, heat paths,
# gas regions and pressure boundaries, with one energy ledger. It owns no
# geometry and no motion -- the live world tells it where things are and
# applies the forces it asks for -- so it builds and tests on its own.
add_library(banjo_thermo src/thermo/Thermochemistry.cpp src/thermo/ThermoWorld.cpp
                         src/thermo/ThermoJson.cpp src/thermo/ThermalMechanics.cpp)
target_link_libraries(banjo_thermo PUBLIC banjo_core PRIVATE nlohmann_json::nlohmann_json)
banjo_enable_warnings(banjo_thermo)
if(BANJO_BUILD_TESTS)
    add_executable(banjo_thermochemistry_tests tests/thermochemistry_tests.cpp)
    target_link_libraries(banjo_thermochemistry_tests PRIVATE banjo_thermo)
    banjo_enable_warnings(banjo_thermochemistry_tests)
    add_test(NAME banjo_thermochemistry_tests COMMAND banjo_thermochemistry_tests)
    # The three machines that gas pressure makes: a steam engine, a cannon
    # and a rocket, all one mechanism.
    add_executable(banjo_gas_pressure_tests tests/gas_pressure_tests.cpp)
    target_link_libraries(banjo_gas_pressure_tests PRIVATE banjo_thermo)
    banjo_enable_warnings(banjo_gas_pressure_tests)
    add_test(NAME banjo_gas_pressure_tests COMMAND banjo_gas_pressure_tests)
endif()
# Terrain and water: the ground as material held still, and rivers and
# lakes as columns of water on it, run where they are changing rather than
# everywhere they exist (docs/terrain-and-water.md). The water solver owns
# no bodies; the environment is where it meets the rigid world.
add_library(banjo_water src/water/ShallowWater.cpp src/water/WaterCoupling.cpp src/water/CompoundWaterSurface.cpp src/water/RiverNetwork.cpp src/water/FallingWater.cpp)
target_link_libraries(banjo_water PUBLIC banjo_core)
banjo_enable_warnings(banjo_water)
if(BANJO_BUILD_TESTS)
    add_executable(banjo_water_tests tests/water_tests.cpp)
    target_link_libraries(banjo_water_tests PRIVATE banjo_water)
    banjo_enable_warnings(banjo_water_tests)
    add_test(NAME banjo_water_tests COMMAND banjo_water_tests)
    add_executable(banjo_river_network_tests tests/river_network_tests.cpp)
    target_link_libraries(banjo_river_network_tests PRIVATE banjo_water)
    banjo_enable_warnings(banjo_river_network_tests)
    add_test(NAME banjo_river_network_tests COMMAND banjo_river_network_tests)
endif()
add_library(banjo_terrain src/terrain/TerrainField.cpp src/terrain/TerrainGenerator.cpp
                          src/terrain/GroundWork.cpp)
target_link_libraries(banjo_terrain PUBLIC banjo_core banjo_water)
banjo_enable_warnings(banjo_terrain)
if(BANJO_BUILD_TESTS)
    add_executable(banjo_terrain_tests tests/terrain_tests.cpp)
    target_link_libraries(banjo_terrain_tests PRIVATE banjo_terrain)
    banjo_enable_warnings(banjo_terrain_tests)
    add_test(NAME banjo_terrain_tests COMMAND banjo_terrain_tests)
endif()
add_library(banjo_environment src/terrain/Environment.cpp src/terrain/StreamedRegions.cpp src/terrain/GroundExcavation.cpp)
target_link_libraries(banjo_environment PUBLIC banjo_terrain banjo_water banjo_runtime
                                        PRIVATE nlohmann_json::nlohmann_json)
banjo_enable_warnings(banjo_environment)
add_library(banjo_circuits src/machines/Circuit.cpp)
target_include_directories(banjo_circuits PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_link_libraries(banjo_circuits PUBLIC nlohmann_json::nlohmann_json)
banjo_enable_warnings(banjo_circuits)
# Light: rays from the sun and lamps followed through the world's own
# shapes -- reflected, refracted, absorbed -- with one ledger of where the
# power went (docs/optics-checkpoint.md). It owns no geometry: the host
# answers where a ray meets a surface.
add_library(banjo_optics src/optics/OpticalProperties.cpp src/optics/RayOptics.cpp)
target_link_libraries(banjo_optics PUBLIC banjo_core)
banjo_enable_warnings(banjo_optics)
add_library(banjo_fastlattice_scene src/fastlattice/TileImpactScene.cpp
                                   src/fastlattice/LiveWorld.cpp
                                   src/fastlattice/ToolTerrain.cpp
                                   src/fastlattice/NativeToolUse.cpp
                                   src/fastlattice/NativeToolClearance.cpp
src/fastlattice/PreciseRigidScene.cpp)
target_link_libraries(banjo_fastlattice_scene PUBLIC banjo_fastlattice banjo_runtime banjo_thermo banjo_environment banjo_circuits banjo_optics PRIVATE nlohmann_json::nlohmann_json)
banjo_enable_warnings(banjo_fastlattice_scene)

# A live scene, driven a line at a time: the playground talks to this instead
# of asking for a recording and playing it back.
add_executable(banjo_live_world_run tools/live_world_run.cpp)
target_link_libraries(banjo_live_world_run PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
banjo_enable_warnings(banjo_live_world_run)

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

    # The floating-point audit (scripts/check-fp-model.py). Every configuration
    # of this build, audited from what CMake generated -- the build itself audits
    # only the configuration it builds -- and the audit's own checks: its rules,
    # and a fixture of builds that leave the model, each of which it must name.
    add_test(NAME banjo_fp_model_audit
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/scripts/check-fp-model.py
                     --build ${CMAKE_BINARY_DIR} --all-configs)
    add_test(NAME banjo_fp_model_audit_tests
             COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/fp_model_audit_tests.py)
    set_tests_properties(banjo_fp_model_audit_tests PROPERTIES ENVIRONMENT
        "BANJO_FP_FIXTURE_GENERATOR=${CMAKE_GENERATOR};BANJO_FP_FIXTURE_PLATFORM=${CMAKE_GENERATOR_PLATFORM};BANJO_FP_FIXTURE_CXX=${CMAKE_CXX_COMPILER};BANJO_FP_FIXTURE_REQUIRED=1")

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

    add_executable(banjo_plate_bending_tests tests/plate_bending_tests.cpp)
    target_link_libraries(banjo_plate_bending_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_plate_bending_tests)
    add_test(NAME banjo_plate_bending_tests COMMAND banjo_plate_bending_tests)
    add_executable(banjo_material_stage_tests tests/material_stage_tests.cpp)
    target_link_libraries(banjo_material_stage_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_material_stage_tests)
    add_test(NAME banjo_material_stage_tests COMMAND banjo_material_stage_tests)

    add_executable(banjo_implicit_fracture_tests tests/implicit_fracture_tests.cpp)
    target_link_libraries(banjo_implicit_fracture_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_implicit_fracture_tests)
    add_test(NAME banjo_implicit_fracture_tests COMMAND banjo_implicit_fracture_tests)
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

    add_executable(banjo_point_rigid_contact_tests tests/point_rigid_contact_tests.cpp)
    target_link_libraries(banjo_point_rigid_contact_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_point_rigid_contact_tests)
    add_test(NAME banjo_point_rigid_contact_tests COMMAND banjo_point_rigid_contact_tests)
    add_executable(banjo_force_contact_phase_tests tests/force_contact_phase_tests.cpp)
    target_link_libraries(banjo_force_contact_phase_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_force_contact_phase_tests)
    add_test(NAME banjo_force_contact_phase_tests COMMAND banjo_force_contact_phase_tests)

    add_executable(banjo_fixed_assembly_contact_tests tests/fixed_assembly_contact_tests.cpp)
    target_link_libraries(banjo_fixed_assembly_contact_tests PRIVATE banjo_core)
    banjo_enable_warnings(banjo_fixed_assembly_contact_tests)
    add_test(NAME banjo_fixed_assembly_contact_tests COMMAND banjo_fixed_assembly_contact_tests)

    add_executable(banjo_double_rigid_source_tests tests/double_rigid_source_tests.cpp)
    target_link_libraries(banjo_double_rigid_source_tests PRIVATE banjo_fastlattice)
    banjo_enable_warnings(banjo_double_rigid_source_tests)
    add_test(NAME banjo_double_rigid_source_tests COMMAND banjo_double_rigid_source_tests)

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

        add_executable(banjo_hinge_tests tests/hinge_tests.cpp)
        target_link_libraries(banjo_hinge_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_hinge_tests)
        add_test(NAME banjo_hinge_tests COMMAND banjo_hinge_tests)

        add_executable(banjo_degenerate_fragment_tests tests/degenerate_fragment_tests.cpp)
        target_link_libraries(banjo_degenerate_fragment_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_degenerate_fragment_tests)
        add_test(NAME banjo_degenerate_fragment_tests COMMAND banjo_degenerate_fragment_tests)

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

        add_executable(banjo_native_point_contact_tests tests/native_point_contact_tests.cpp)
        target_link_libraries(banjo_native_point_contact_tests PRIVATE banjo_runtime)
        banjo_enable_warnings(banjo_native_point_contact_tests)
        add_test(NAME banjo_native_point_contact_tests COMMAND banjo_native_point_contact_tests)
        # Exercises the full coupled contact search and transfer accounting.
        # Strict fracture/time refinement is a separate retained acceptance gate.

    # Two wheels that turn together at a ratio: gears in mesh, a chain between
    # sprockets, and teeth that strip when too much goes through them.
    add_executable(banjo_gear_tests tests/gear_tests.cpp)
    target_link_libraries(banjo_gear_tests PRIVATE banjo_runtime)
    banjo_enable_warnings(banjo_gear_tests)
    add_test(NAME banjo_gear_tests COMMAND banjo_gear_tests)

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

            add_executable(banjo_lattice_external_load_tests tests/lattice_external_load_tests.cpp)
            target_link_libraries(banjo_lattice_external_load_tests PRIVATE banjo_fastlattice)
            banjo_enable_warnings(banjo_lattice_external_load_tests)
            add_test(NAME banjo_lattice_external_load_tests COMMAND banjo_lattice_external_load_tests)

            add_executable(banjo_solid_matter_patch_tests tests/solid_matter_patch_tests.cpp)
            target_link_libraries(banjo_solid_matter_patch_tests PRIVATE banjo_fastlattice)
            banjo_enable_warnings(banjo_solid_matter_patch_tests)
            add_test(NAME banjo_solid_matter_patch_tests COMMAND banjo_solid_matter_patch_tests)
            add_executable(banjo_constituent_partition_tests tests/constituent_partition_tests.cpp)
            target_link_libraries(banjo_constituent_partition_tests PRIVATE banjo_fastlattice)
            banjo_enable_warnings(banjo_constituent_partition_tests)
            add_test(NAME banjo_constituent_partition_tests COMMAND banjo_constituent_partition_tests)

            # A scene that keeps running instead of being run: stepping, reading
            # where everything is, and taking hold of something.
            add_executable(banjo_live_world_tests tests/live_world_tests.cpp)
            target_link_libraries(banjo_live_world_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_live_world_tests)
            add_test(NAME banjo_live_world_tests COMMAND banjo_live_world_tests)
            add_executable(banjo_pickup_admission_tests tests/pickup_admission_tests.cpp)
            target_link_libraries(banjo_pickup_admission_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_pickup_admission_tests)
            add_test(NAME banjo_pickup_admission_tests COMMAND banjo_pickup_admission_tests)
            add_executable(banjo_tool_use_admission_tests tests/tool_use_admission_tests.cpp)
            target_link_libraries(banjo_tool_use_admission_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_tool_use_admission_tests)
            add_test(NAME banjo_tool_use_admission_tests COMMAND banjo_tool_use_admission_tests)
            add_executable(banjo_native_tool_use_tests tests/native_tool_use_tests.cpp)
            target_link_libraries(banjo_native_tool_use_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_native_tool_use_tests)
            add_test(NAME banjo_native_tool_use_tests COMMAND banjo_native_tool_use_tests)

            # The same world twice, with the threads on: a contact order that is
            # a function of the contacts and not of which worker finished first.
            add_executable(banjo_live_determinism_tests tests/live_determinism_tests.cpp)
            target_link_libraries(banjo_live_determinism_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_live_determinism_tests)
            add_test(NAME banjo_live_determinism_tests COMMAND banjo_live_determinism_tests)
            # Its check against the wall clock -- a foreseen fracture's first
            # run done inside its warning -- is a claim about the machine as much
            # as the engine: beside other heavy work it fails on any build. It
            # runs on its own, labelled performance, for the performance gate
            # (scripts/run-performance-gate.py) rather than every push. The rest
            # of the suite still reads the clock in places, so both run serially.
            add_test(NAME banjo_live_world_deadline COMMAND banjo_live_world_tests --deadline)
            set_tests_properties(banjo_live_world_tests banjo_live_world_deadline PROPERTIES RUN_SERIAL TRUE)
            set_tests_properties(banjo_live_world_deadline PROPERTIES LABELS performance)

            # What the build's objects -- ours, and Jolt's own -- do with NaNs,
            # infinities, signed zeros, denormals and a product that could be
            # fused, and what the engine's own checks make of NaNs, in the
            # profile they were built to (docs/floating-point-model.md).
            add_executable(banjo_fp_profile_tests tests/fp_profile_tests.cpp)
            target_link_libraries(banjo_fp_profile_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_fp_profile_tests)
            add_test(NAME banjo_fp_profile_tests COMMAND banjo_fp_profile_tests)

            # A room opened again from a scene that has changed keeps everything
            # the change did not touch: a saved world carried in thing by thing.
            add_executable(banjo_room_carry_tests tests/room_carry_tests.cpp)
            target_link_libraries(banjo_room_carry_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_room_carry_tests)
            add_test(NAME banjo_room_carry_tests COMMAND banjo_room_carry_tests)

            # Heat, chemistry and gas inside a live world: a heated gas lifting
            # a load through a real slide, a refused step taking its chemistry
            # back, a burning plank breaking and sharing out what it held.
            add_executable(banjo_thermo_live_tests tests/thermo_live_tests.cpp)
            target_link_libraries(banjo_thermo_live_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_thermo_live_tests)
            add_test(NAME banjo_thermo_live_tests COMMAND banjo_thermo_live_tests)

            # Heat changing what things can carry (docs/thermal-mechanics.md):
            # a heated oak peg gives way under its gate when the load passes
            # what its law leaves it, and not before; its cold twin, an
            # unloaded peg and an iron one hold; cooling gives back only what
            # was reversible; a refused step, a split and a restore keep the
            # history; a softening spring's energy goes to the ledger.
            add_executable(banjo_thermal_mechanics_tests tests/thermal_mechanics_tests.cpp)
            target_link_libraries(banjo_thermal_mechanics_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_thermal_mechanics_tests)
            add_test(NAME banjo_thermal_mechanics_tests COMMAND banjo_thermal_mechanics_tests)

            # One material state (docs/thermal-mechanics.md): the lattice a
            # heated body is broken in, its collision shape, its drawn shape,
            # its mass, centre of mass and inertia, and its attachments all
            # follow the same field the overload check and the reports read.
            add_executable(banjo_thermal_geometry_tests tests/thermal_geometry_tests.cpp)
            target_link_libraries(banjo_thermal_geometry_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_thermal_geometry_tests)
            add_test(NAME banjo_thermal_geometry_tests COMMAND banjo_thermal_geometry_tests)
            # The same source, built for the two tests that take minutes: the
            # owner's two loaded beams, one heated and one cold, in glass, oak
            # and iron, and the heater powers. Labelled long further down.
            add_executable(banjo_thermal_geometry_long_tests tests/thermal_geometry_tests.cpp)
            target_link_libraries(banjo_thermal_geometry_long_tests PRIVATE banjo_fastlattice_scene)
            target_compile_definitions(banjo_thermal_geometry_long_tests PRIVATE BANJO_THERMAL_GEOMETRY_LONG=1)
            banjo_enable_warnings(banjo_thermal_geometry_long_tests)
            add_test(NAME banjo_thermal_geometry_long_tests COMMAND banjo_thermal_geometry_long_tests)
            # It runs for many minutes: labelled long, so CI's -LE "long|performance"
            # leaves it out, and given the long suites' timeout.
            set(BANJO_LONG_TEST_TIMEOUT_S 7200 CACHE STRING "Timeout, in seconds, for the long suites")
            set_tests_properties(banjo_thermal_geometry_long_tests PROPERTIES
                LABELS long TIMEOUT ${BANJO_LONG_TEST_TIMEOUT_S})

            # Terrain and water in a live world: the owner's acceptance tests
            # for the valley -- conservation, a lake at rest, a dam, an outlet,
            # a cut block, a dig that stays local, a boulder undermined, a log
            # drifting, water carried into a reopened world, and the realtime
            # rule (docs/terrain-and-water.md).
            add_executable(banjo_valley_live_tests tests/valley_live_tests.cpp)
            target_link_libraries(banjo_valley_live_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_valley_live_tests)
            add_test(NAME banjo_valley_live_tests COMMAND banjo_valley_live_tests)

            # The ground beyond the valley: regions streamed in as somebody
            # nears an edge -- a seam with no step, a body walking across it,
            # digging out there, save and reopen, and what it costs
            # (docs/streamed-regions.md).
            add_executable(banjo_streamed_regions_tests tests/streamed_regions_tests.cpp)
            target_link_libraries(banjo_streamed_regions_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_streamed_regions_tests)
            add_test(NAME banjo_streamed_regions_tests COMMAND banjo_streamed_regions_tests)

            # Rolling resistance, M = c N r at every contact of a round body
            # (docs/rolling-resistance.md): the level deceleration 5/7 c g
            # against a zero-resistance control, the energy it takes, the
            # slope a ball rests on, N as the solver's own contact force, and
            # the ball by the river in the valley.
            add_executable(banjo_rolling_resistance_tests tests/rolling_resistance_tests.cpp)
            target_link_libraries(banjo_rolling_resistance_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_rolling_resistance_tests)
            add_test(NAME banjo_rolling_resistance_tests COMMAND banjo_rolling_resistance_tests)

            # Where cutting meets heat: a burning log cut in two keeps its fuel
            # and its fire, a refused step mid-cut changes nothing, and a hand
            # pushes once per step however the step is retried.
            add_executable(banjo_blade_thermo_tests tests/blade_thermo_tests.cpp)
            target_link_libraries(banjo_blade_thermo_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_blade_thermo_tests)
            add_test(NAME banjo_blade_thermo_tests COMMAND banjo_blade_thermo_tests)

            # Pins, as the scene sees them: a joint between two NAMES, which is
            # what has to survive the bodies underneath being destroyed and
            # rebuilt every time anything in their island breaks.
            add_executable(banjo_scene_joint_tests tests/scene_joint_tests.cpp)
            target_link_libraries(banjo_scene_joint_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_scene_joint_tests)
            add_test(NAME banjo_scene_joint_tests COMMAND banjo_scene_joint_tests)

            # Exact rigid parts that are not axis-aligned boxes of one
            # material: cylinders and turned parts, a part of its own
            # material, overlaps counted once -- a cart's wheelset, with
            # glass/oak/iron oracles for mass, inertia and rolling.
            add_executable(banjo_precise_rigid_parts_tests tests/precise_rigid_parts_tests.cpp)
            target_link_libraries(banjo_precise_rigid_parts_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_precise_rigid_parts_tests)
            add_test(NAME banjo_precise_rigid_parts_tests COMMAND banjo_precise_rigid_parts_tests)

            # Where a thing would go set down, and whether it fits: the
            # engine's half of placing a thing (docs/inventory-and-hands.md,
            # section 5), which the page's see-through copy asks.
            add_executable(banjo_placement_tests tests/placement_tests.cpp)
            target_link_libraries(banjo_placement_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_placement_tests)
            add_test(NAME banjo_placement_tests COMMAND banjo_placement_tests)

            # Motors on pins and the stores of energy they draw on: the machine
            # world's first joint that is driven, checked against the motor's
            # line and the energy it takes (docs/machine-world.md).
            add_executable(banjo_motor_tests tests/motor_tests.cpp)
            add_executable(banjo_circuit_tests tests/circuit_tests.cpp)
            target_link_libraries(banjo_circuit_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_circuit_tests)
            add_test(NAME banjo_circuit_tests COMMAND banjo_circuit_tests)
            # The machine world: general parts built into one live world, the
            # declaration checks, the chat's refusal and rehearsal loops, and an
            # engine run of the default chain (docs/machine-world-checkpoint.md).
            if(Python3_FOUND AND TARGET banjo_live_world_run)
                add_test(NAME banjo_machine_world_tests COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/machine_world_tests.py --engine $<TARGET_FILE:banjo_live_world_run>)
                set_tests_properties(banjo_machine_world_tests PROPERTIES TIMEOUT 300
                    ENVIRONMENT "BANJO_MACHINE_ENGINE=required" LABELS "native;world;machine")
                # The newer pieces, each in a small machine: gears, a pulley,
                # a motor, the sun, steam, a cannon, a dent and a knife.
                add_test(NAME banjo_machine_physics_tests COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/machine_physics_tests.py --engine $<TARGET_FILE:banjo_live_world_run>)
                set_tests_properties(banjo_machine_physics_tests PROPERTIES TIMEOUT 600
                    ENVIRONMENT "BANJO_MACHINE_ENGINE=required" LABELS "native;world;machine")
                # The puzzles (/play): every level solvable, and only that way.
                add_test(NAME banjo_machine_game_tests COMMAND ${Python3_EXECUTABLE}
                    ${CMAKE_CURRENT_SOURCE_DIR}/tests/machine_game_tests.py --engine $<TARGET_FILE:banjo_live_world_run>)
                set_tests_properties(banjo_machine_game_tests PROPERTIES TIMEOUT 600
                    ENVIRONMENT "BANJO_MACHINE_ENGINE=required" LABELS "native;world;machine")
                # The same puzzles in Chrome: a piece's ghost moved, turned,
                # set down and run, on a desktop and a phone.
                add_test(NAME banjo_machine_game_browser_tests COMMAND ${CMAKE_COMMAND} -E env
                    BANJO_LIVE_ENGINE=$<TARGET_FILE:banjo_live_world_run>
                    ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/machine_game_browser_tests.py)
                set_tests_properties(banjo_machine_game_browser_tests PROPERTIES TIMEOUT 300
                    LABELS "native;world;machine;browser")
            endif()
            target_link_libraries(banjo_motor_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_motor_tests)
            add_test(NAME banjo_motor_tests COMMAND banjo_motor_tests)

            # A machine's controller (docs/machine-world.md, "Operating a
            # machine"): a hoist held to its travel, a reverse that stops
            # first, a motor that gets nowhere stopped, a late command dropped,
            # and a restart that gives it back as it was told.
            add_executable(banjo_machine_control_tests tests/machine_control_tests.cpp)
            target_link_libraries(banjo_machine_control_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_machine_control_tests)
            add_test(NAME banjo_machine_control_tests COMMAND banjo_machine_control_tests)

            add_executable(banjo_cart_drive_tests tests/cart_drive_tests.cpp)
            target_link_libraries(banjo_cart_drive_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_cart_drive_tests)
            add_test(NAME banjo_cart_drive_tests COMMAND banjo_cart_drive_tests)

            # A rover that roams: a motor on each back wheel, a caster in front,
            # and a program that works the two wheels' controllers.
            add_executable(banjo_rover_roam_tests tests/rover_roam_tests.cpp)
            target_link_libraries(banjo_rover_roam_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_rover_roam_tests)
            add_test(NAME banjo_rover_roam_tests COMMAND banjo_rover_roam_tests)
            add_executable(banjo_drone_hover_tests tests/drone_hover_tests.cpp)
            target_link_libraries(banjo_drone_hover_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_drone_hover_tests)
            add_test(NAME banjo_drone_hover_tests COMMAND banjo_drone_hover_tests)

            # Solar panels: a room's sun, and what a panel on a part puts into the
            # store it is wired to -- square on, at an angle, in shade, and full.
            add_executable(banjo_solar_panel_tests tests/solar_panel_tests.cpp)
            target_link_libraries(banjo_solar_panel_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_solar_panel_tests)
            add_test(NAME banjo_solar_panel_tests COMMAND banjo_solar_panel_tests)

            # A day for the sun: it rises east, stands south at noon and sets
            # west on the world's own clock; its beam thins low in the sky; at
            # night a panel makes nothing; a saved world keeps its hour.
            add_executable(banjo_sun_day_tests tests/sun_day_tests.cpp)
            target_link_libraries(banjo_sun_day_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_sun_day_tests)
            add_test(NAME banjo_sun_day_tests COMMAND banjo_sun_day_tests)

            # Light (docs/optics-checkpoint.md): a mirror reflects at the angle it
            # was met; a glass slab shifts a ray by Snell's law; total internal
            # reflection; a glass ball concentrates sunlight; light heats what
            # absorbs it until it burns; a light sensor works a circuit switch;
            # the ledger closes; and a world with no light is untouched.
            add_executable(banjo_optics_tests tests/optics_tests.cpp)
            target_link_libraries(banjo_optics_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_optics_tests)
            add_test(NAME banjo_optics_tests COMMAND banjo_optics_tests)

            # Lit spots (docs/light-spots.md): a 4.5 kW beam off a mirror parts
            # an oak cord in seconds by taking the lit oak away, for the energy
            # per volume the thermochemistry gives; a weaker beam takes longer
            # and a weak one only warms; the mirror is not cut; glass is warmed
            # and never cut; ice melts by depth; the ledgers close.
            add_executable(banjo_light_spot_tests tests/light_spot_tests.cpp)
            target_link_libraries(banjo_light_spot_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_light_spot_tests)
            add_test(NAME banjo_light_spot_tests COMMAND banjo_light_spot_tests)

            # What a break costs: the charge the room's failure law makes for
            # a crack, against what the material itself declares, and what a
            # break actually took away.
            add_executable(banjo_break_cost_tests tests/break_cost_tests.cpp)
            target_link_libraries(banjo_break_cost_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_break_cost_tests)
            add_test(NAME banjo_break_cost_tests COMMAND banjo_break_cost_tests)

            # Things that slide: a portcullis in its grooves, a sliding door, a
            # bolt across a door. The test that matters is the first one -- a
            # raised grate falls when you let go, because nothing here knows
            # what a portcullis is.
            add_executable(banjo_slider_tests tests/slider_tests.cpp)
            target_link_libraries(banjo_slider_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_slider_tests)
            add_test(NAME banjo_slider_tests COMMAND banjo_slider_tests)

            # Ropes and chains: a link that pulls and does not push, made of
            # ordinary bodies tied to each other rather than a rope object.
            add_executable(banjo_rope_tests tests/rope_tests.cpp)
            target_link_libraries(banjo_rope_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_rope_tests)
            add_test(NAME banjo_rope_tests COMMAND banjo_rope_tests)

            # Pulleys and hoists: the IDEAL pulley, a cable-length relationship
            # rather than a wheel with a rope wrapped round it. The physical
            # alternative is in rope_tests -- bodies tied together and draped.
            # Supports, beams and levers -- and above all SUSTAINED load,
            # which the impact ledger cannot see: a plank at rest under a pile
            # of crates reports no contacts at all.
            # Attachments and latches: pegs, brackets, catches, locking bars.
            # A strength along the axis and another across it, because a peg
            # pulled out and a peg sheared fail at different loads.
            # Elastic elements, and the VALIDATION of the linear-spring model
            # they declare: Hooke's law, the work integral against the stored
            # energy, and the energy back out as motion.
            # A bow, built out of parts that already existed: elastics for
            # limbs, links for the string, a fixing for the nock. Nothing in the
            # engine knows what a bow is, and the arrow's speed comes out of the
            # stored energy rather than being chosen.
            add_executable(banjo_bow_tests tests/bow_tests.cpp)
            target_link_libraries(banjo_bow_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_bow_tests)
            add_test(NAME banjo_bow_tests COMMAND banjo_bow_tests)

            # The hand's own motions: a stroke made at the step's rate, what it
            # does to light and heavy things, the work the hand does, and the
            # previews that aim it. docs/interaction-profiles.md.
            add_executable(banjo_hand_stroke_tests tests/hand_stroke_tests.cpp)
            target_link_libraries(banjo_hand_stroke_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_hand_stroke_tests)
            add_test(NAME banjo_hand_stroke_tests COMMAND banjo_hand_stroke_tests)

            # Tools that work the ground: ground-work-v1 against its closed
            # forms, a point's work against the energy the tool lost, the same
            # swing twice, soil against rock, a pry carried, a point drawn out.
            # docs/ground-work.md.
            add_executable(banjo_ground_work_tests tests/ground_work_tests.cpp)
            target_link_libraries(banjo_ground_work_tests PRIVATE banjo_fastlattice_scene
                                                          nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_ground_work_tests)
            add_test(NAME banjo_ground_work_tests COMMAND banjo_ground_work_tests)
            add_executable(banjo_ground_excavation_tests tests/ground_excavation_tests.cpp)
            target_link_libraries(banjo_ground_excavation_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_ground_excavation_tests)
            add_test(NAME banjo_ground_excavation_tests COMMAND banjo_ground_excavation_tests)
            add_executable(banjo_local_cell_tools_tests tests/local_cell_tools_tests.cpp)
            target_link_libraries(banjo_local_cell_tools_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_local_cell_tools_tests)
            add_test(NAME banjo_local_cell_tools_tests COMMAND banjo_local_cell_tools_tests)

            add_executable(banjo_body_condition_tests tests/body_condition_tests.cpp)
            target_link_libraries(banjo_body_condition_tests PRIVATE banjo_fastlattice_scene nlohmann_json::nlohmann_json)
            banjo_enable_warnings(banjo_body_condition_tests)
            add_test(NAME banjo_body_condition_tests COMMAND banjo_body_condition_tests)

            add_executable(banjo_elastic_tests tests/elastic_tests.cpp)
            target_link_libraries(banjo_elastic_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_elastic_tests)
            add_test(NAME banjo_elastic_tests COMMAND banjo_elastic_tests)

            add_executable(banjo_fixing_tests tests/fixing_tests.cpp)
            target_link_libraries(banjo_fixing_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_fixing_tests)
            add_test(NAME banjo_fixing_tests COMMAND banjo_fixing_tests)

            # Blades, and cutting that changes what things are: the energy a cut
            # takes against what the declared law says it costs, partial cuts that
            # stay partial, pieces with their own mass and momentum, a rope that
            # drops its load, and the flat of the blade that does not cut it.
            # docs/cutting-model.md.
            add_executable(banjo_blade_tests tests/blade_tests.cpp)
            target_link_libraries(banjo_blade_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_blade_tests)
            add_test(NAME banjo_blade_tests COMMAND banjo_blade_tests)

            add_executable(banjo_beam_tests tests/beam_tests.cpp)
            target_link_libraries(banjo_beam_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_beam_tests)
            add_test(NAME banjo_beam_tests COMMAND banjo_beam_tests)

            add_executable(banjo_joint_interface_tests tests/joint_interface_tests.cpp)
            target_link_libraries(banjo_joint_interface_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_joint_interface_tests)
            add_test(NAME banjo_joint_interface_tests COMMAND banjo_joint_interface_tests)

            add_executable(banjo_pulley_tests tests/pulley_tests.cpp)
            target_link_libraries(banjo_pulley_tests PRIVATE banjo_fastlattice_scene)
            banjo_enable_warnings(banjo_pulley_tests)
            add_test(NAME banjo_pulley_tests COMMAND banjo_pulley_tests)

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

            add_executable(banjo_lattice_verlet_tests tests/lattice_verlet_tests.cpp)
            target_link_libraries(banjo_lattice_verlet_tests PRIVATE banjo_fastlattice)
            banjo_enable_warnings(banjo_lattice_verlet_tests)
            add_test(NAME banjo_lattice_verlet_tests COMMAND banjo_lattice_verlet_tests)

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

        # Adding a file must not change what the simulation computes: one Jolt
        # scene, built alone and with tests/fp_link_order_extra.cpp -- our own
        # copies of Jolt's solver and closest-point inlines -- first on the link
        # line, where the linker meets them before Jolt's, compared bit for bit.
        # Under one floating-point model the copies compute the same; under two,
        # the link order chose the arithmetic (docs/floating-point-model.md).
        add_executable(banjo_fp_link_order_plain tests/fp_link_order_harness.cpp)
        target_link_libraries(banjo_fp_link_order_plain PRIVATE Jolt)
        banjo_enable_warnings(banjo_fp_link_order_plain)
        add_executable(banjo_fp_link_order_extra_first tests/fp_link_order_extra.cpp tests/fp_link_order_harness.cpp)
        target_link_libraries(banjo_fp_link_order_extra_first PRIVATE Jolt)
        banjo_enable_warnings(banjo_fp_link_order_extra_first)
        add_test(NAME banjo_fp_link_order_tests
                 COMMAND ${CMAKE_COMMAND} -DPLAIN=$<TARGET_FILE:banjo_fp_link_order_plain>
                         -DEXTRA_FIRST=$<TARGET_FILE:banjo_fp_link_order_extra_first>
                         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/fp_link_order_compare.cmake)
    endif()
    if(BANJO_NODE_EXECUTABLE)
        add_test(NAME banjo_machine_view_tests COMMAND ${BANJO_NODE_EXECUTABLE}
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/machine_view_test.mjs)
        set_tests_properties(banjo_machine_view_tests PROPERTIES TIMEOUT 10 LABELS "client;machine")
    endif()
endif()
