# GLFW's active-window property lookup can return a foreign-process pointer
# when input queues are attached (for example by desktop automation). Resolve
# only windows owned by this GLFW instance. Patch a generated build copy so a
# shared FetchContent source checkout is never modified.
if(WIN32 AND TARGET glfw)
    get_target_property(banjo_glfw_dir glfw SOURCE_DIR)
    get_target_property(banjo_glfw_sources glfw SOURCES)
    file(READ "${banjo_glfw_dir}/win32_window.c" banjo_glfw_text)
    set(banjo_glfw_old "        window = GetPropW(handle, L\"GLFW\");")
    string(REGEX MATCHALL "window = GetPropW\\(handle, L\"GLFW\"\\)" banjo_glfw_matches "${banjo_glfw_text}")
    list(LENGTH banjo_glfw_matches banjo_glfw_match_count)
    if(NOT banjo_glfw_match_count EQUAL 1)
        message(FATAL_ERROR "Reassess the GLFW active-window guard against this dependency version")
    endif()
    string(REPLACE "${banjo_glfw_old}"
"        // Banjo: properties on another process's HWND are not local pointers.
        for (window = _glfw.windowListHead; window; window = window->next)
        {
            if (window->win32.handle == handle)
                break;
        }" banjo_glfw_text "${banjo_glfw_text}")
    file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated/glfw")
    set(banjo_glfw_generated "${CMAKE_CURRENT_BINARY_DIR}/generated/glfw/win32_window.c")
    # Avoid rewriting unchanged content and rebuilding GLFW on every configure.
    file(WRITE "${banjo_glfw_generated}.in" "${banjo_glfw_text}")
    configure_file("${banjo_glfw_generated}.in" "${banjo_glfw_generated}" COPYONLY)
    set(banjo_glfw_patched_sources)
    foreach(banjo_glfw_source IN LISTS banjo_glfw_sources)
        if(banjo_glfw_source STREQUAL "win32_window.c" OR banjo_glfw_source STREQUAL "${banjo_glfw_dir}/win32_window.c")
            list(APPEND banjo_glfw_patched_sources "${banjo_glfw_generated}")
        elseif(IS_ABSOLUTE "${banjo_glfw_source}" OR banjo_glfw_source MATCHES "^\\$<")
            list(APPEND banjo_glfw_patched_sources "${banjo_glfw_source}")
        else()
            list(APPEND banjo_glfw_patched_sources "${banjo_glfw_dir}/${banjo_glfw_source}")
        endif()
    endforeach()
    set_property(TARGET glfw PROPERTY SOURCES "${banjo_glfw_patched_sources}")
    target_include_directories(glfw PRIVATE "${banjo_glfw_dir}")
endif()
