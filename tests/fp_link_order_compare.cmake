# Runs tests/fp_link_order_harness.cpp built twice -- alone, and with
# tests/fp_link_order_extra.cpp, our own copies of Jolt's solver and
# closest-point inlines, first on the link line -- and requires the two to
# print the same state, bit for bit (docs/floating-point-model.md).
#
#   cmake -DPLAIN=<program> -DEXTRA_FIRST=<program> -P tests/fp_link_order_compare.cmake

foreach(program PLAIN EXTRA_FIRST)
    if(NOT EXISTS "${${program}}")
        message(FATAL_ERROR "fp_link_order: there is no ${program} program at '${${program}}'")
    endif()
endforeach()
execute_process(COMMAND "${PLAIN}" RESULT_VARIABLE plain_result OUTPUT_VARIABLE plain ERROR_VARIABLE plain_error)
execute_process(COMMAND "${EXTRA_FIRST}" RESULT_VARIABLE extra_result OUTPUT_VARIABLE extra ERROR_VARIABLE extra_error)
if(NOT plain_result EQUAL 0 OR NOT extra_result EQUAL 0)
    message(FATAL_ERROR "fp_link_order: a harness failed (alone ${plain_result}, with the copies first "
                        "${extra_result}):\n${plain_error}\n${extra_error}")
endif()
string(REGEX MATCH "digest [0-9a-f]+" plain_digest "${plain}")
string(REGEX MATCH "digest [0-9a-f]+" extra_digest "${extra}")
if(plain_digest STREQUAL "")
    message(FATAL_ERROR "fp_link_order: the harness printed no state:\n${plain}")
endif()
if(NOT plain STREQUAL extra)
    message(FATAL_ERROR "fp_link_order: our copies of Jolt's inlines, first on the link line, changed what "
                        "the simulation computed (${plain_digest} alone, ${extra_digest} with them first):\n"
                        "--- alone\n${plain}--- with them first\n${extra}")
endif()
message(STATUS "fp_link_order: ${plain_digest} alone and with our copies of Jolt's inlines linked first")
