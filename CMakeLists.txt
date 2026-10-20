cmake_minimum_required(VERSION 3.20)
project(DreamSeed VERSION 0.1.0 LANGUAGES C CXX)

option(DREAMSEED_WARNINGS_AS_ERRORS "Treat DreamSeed warnings as errors" OFF)
option(DREAMSEED_ENABLE_SANITIZERS "Enable address and undefined behavior sanitizers" OFF)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)
FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG 9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03
)
FetchContent_MakeAvailable(nlohmann_json)

if(DREAMSEED_ENABLE_SANITIZERS)
  if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
  else()
    message(FATAL_ERROR "Sanitizers require Clang or GCC")
  endif()
endif()

function(dreamseed_set_warnings target)
  if(MSVC)
    target_compile_options(${target} PRIVATE /W4)
    if(DREAMSEED_WARNINGS_AS_ERRORS)
      target_compile_options(${target} PRIVATE /WX)
    endif()
  else()
    target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    if(DREAMSEED_WARNINGS_AS_ERRORS)
      target_compile_options(${target} PRIVATE -Werror)
    endif()
  endif()
endfunction()

set(CUBIOMES_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/cubiomes)
add_library(cubiomes STATIC
  ${CUBIOMES_DIR}/noise.c
  ${CUBIOMES_DIR}/biomes.c
  ${CUBIOMES_DIR}/layers.c
  ${CUBIOMES_DIR}/biomenoise.c
  ${CUBIOMES_DIR}/generator.c
  ${CUBIOMES_DIR}/finders.c
  ${CUBIOMES_DIR}/util.c
  ${CUBIOMES_DIR}/quadbase.c
)
target_include_directories(cubiomes SYSTEM PUBLIC ${CUBIOMES_DIR})
target_compile_options(cubiomes PRIVATE -Wall -Wextra -fwrapv)
target_link_libraries(cubiomes PUBLIC m)

find_package(Threads REQUIRED)
add_library(dreamseed_engine STATIC engine/src/engine.cpp)
target_include_directories(dreamseed_engine PUBLIC engine/include)
dreamseed_set_warnings(dreamseed_engine)
target_link_libraries(dreamseed_engine PUBLIC cubiomes nlohmann_json::nlohmann_json Threads::Threads)

add_executable(dreamseed cli/main.cpp)
target_link_libraries(dreamseed PRIVATE dreamseed_engine)
dreamseed_set_warnings(dreamseed)

include(CTest)
if(BUILD_TESTING)
  add_executable(engine_tests engine/tests/test_engine.cpp)
  target_link_libraries(engine_tests PRIVATE dreamseed_engine)
  dreamseed_set_warnings(engine_tests)
  add_test(NAME engine_tests COMMAND engine_tests)
endif()

install(TARGETS dreamseed RUNTIME DESTINATION bin)
