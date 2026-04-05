cmake_minimum_required(VERSION 3.16)
project(voice_cpp_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(voice_cpp_engine SHARED
    src/voice_cpp_engine.cpp
)

target_compile_definitions(voice_cpp_engine PRIVATE VOICE_CPP_ENGINE_EXPORTS)

if (MSVC)
    target_compile_options(voice_cpp_engine PRIVATE /O2)
else()
    target_compile_options(voice_cpp_engine PRIVATE -O3)
    target_link_options(voice_cpp_engine PRIVATE -static-libgcc -static-libstdc++)
endif()

set_target_properties(voice_cpp_engine PROPERTIES
    PREFIX ""
)
