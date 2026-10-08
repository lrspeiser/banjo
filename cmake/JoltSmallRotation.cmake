# Generate a consistent inline implementation for Jolt and every consumer in
# the build tree. Never edit the shared dependency checkout. The upstream
# one-microradian dead zone is not a valid time refinement for spinning bodies:
# reducing dt stops orientation integration while velocity and attachments move.
function(banjo_jolt_continuous_small_rotation target source_dir)
    set(relative_path "Jolt/Physics/Body/Body.inl")
    file(READ "${source_dir}/${relative_path}" source_text)
    set(original "if (len > 1.0e-6f)")
    set(replacement "if (len > 0.0f)")
    string(REPLACE "${original}" "" without "${source_text}")
    string(LENGTH "${source_text}" original_length)
    string(LENGTH "${without}" without_length)
    string(LENGTH "${original}" expression_length)
    math(EXPR expected_removed "2 * ${expression_length}")
    math(EXPR removed "${original_length} - ${without_length}")
    if(NOT removed EQUAL expected_removed)
        message(FATAL_ERROR "Pinned Jolt Add/SubRotationStep expressions changed; review small-rotation integration")
    endif()
    string(REPLACE "${original}" "${replacement}" patched "${source_text}")
    set(overlay "${CMAKE_CURRENT_BINARY_DIR}/jolt-small-rotation-overlay")
    get_filename_component(parent "${overlay}/${relative_path}" DIRECTORY)
    file(MAKE_DIRECTORY "${parent}")
    file(CONFIGURE OUTPUT "${overlay}/${relative_path}" CONTENT "${patched}" @ONLY)
    # Body.h includes "Body.inl" relative to itself. Copy its unchanged public
    # declaration into the overlay too, so the local include resolves here.
    file(READ "${source_dir}/Jolt/Physics/Body/Body.h" body_header)
    file(CONFIGURE OUTPUT "${overlay}/Jolt/Physics/Body/Body.h" CONTENT "${body_header}" @ONLY)
    target_include_directories(${target} BEFORE PUBLIC "${overlay}")
    target_compile_definitions(${target} PUBLIC BANJO_JOLT_CONTINUOUS_SMALL_ROTATION=1)
    # Outcome keys are compiled in banjo_core, which does not link Jolt. Keep
    # its solver identity consistent with the selected native integration.
    target_compile_definitions(banjo_core PUBLIC BANJO_JOLT_CONTINUOUS_SMALL_ROTATION=1)
    message(STATUS "Experimental Jolt small rotations: remove the one-microradian angular dead zone")
endfunction()
