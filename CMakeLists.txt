cmake_minimum_required(VERSION 3.20)
project(DreamSeed VERSION 0.2.0 LANGUAGES C CXX)

option(DREAMSEED_WARNINGS_AS_ERRORS "Treat DreamSeed warnings as errors" OFF)
option(DREAMSEED_ENABLE_SANITIZERS "Enable address and undefined behavior sanitizers" OFF)
option(DREAMSEED_ENABLE_METAL "Enable experimental Metal placement filtering on macOS" ${APPLE})

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(DREAMSEED_VERSION_CATALOG "${CMAKE_CURRENT_SOURCE_DIR}/dreamseed_mcp/minecraft_versions.json")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${DREAMSEED_VERSION_CATALOG}")
file(READ "${DREAMSEED_VERSION_CATALOG}" DREAMSEED_VERSION_JSON)
string(JSON DREAMSEED_CATALOG_LENGTH LENGTH "${DREAMSEED_VERSION_JSON}" versions)
math(EXPR DREAMSEED_CATALOG_LAST "${DREAMSEED_CATALOG_LENGTH} - 1")
set(DREAMSEED_VERSION_COUNT 0)
set(DREAMSEED_VERSION_ROWS "")
foreach(DREAMSEED_CATALOG_INDEX RANGE ${DREAMSEED_CATALOG_LAST})
  string(JSON DREAMSEED_VERSION_ENABLED GET "${DREAMSEED_VERSION_JSON}" versions ${DREAMSEED_CATALOG_INDEX} enabled)
  if(DREAMSEED_VERSION_ENABLED)
    string(JSON DREAMSEED_VERSION_NAME GET "${DREAMSEED_VERSION_JSON}" versions ${DREAMSEED_CATALOG_INDEX} name)
    string(JSON DREAMSEED_VERSION_ENUM GET "${DREAMSEED_VERSION_JSON}" versions ${DREAMSEED_CATALOG_INDEX} cubiomes_enum)
    if(NOT DREAMSEED_VERSION_NAME MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+$" OR NOT DREAMSEED_VERSION_ENUM MATCHES "^MC_1_[0-9_]+$")
      message(FATAL_ERROR "Invalid Minecraft version catalog entry")
    endif()
    string(APPEND DREAMSEED_VERSION_ROWS "    {\"${DREAMSEED_VERSION_NAME}\", ${DREAMSEED_VERSION_ENUM}},\n")
    math(EXPR DREAMSEED_VERSION_COUNT "${DREAMSEED_VERSION_COUNT} + 1")
  endif()
endforeach()
if(DREAMSEED_VERSION_COUNT EQUAL 0)
  message(FATAL_ERROR "At least one Minecraft version must be enabled")
endif()
configure_file(engine/src/version_catalog.hpp.in generated/version_catalog.hpp @ONLY)

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
if(APPLE AND DREAMSEED_ENABLE_METAL)
  enable_language(OBJCXX)
  set_property(TARGET dreamseed_engine PROPERTY OBJCXX_STANDARD 20)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/engine/src/placement.metal")
  file(READ engine/src/placement.metal DREAMSEED_METAL_SOURCE)
  configure_file(engine/src/metal_source.hpp.in generated/metal_source.hpp @ONLY)
  target_sources(dreamseed_engine PRIVATE engine/src/placement_metal.mm)
  set_source_files_properties(engine/src/placement_metal.mm PROPERTIES COMPILE_OPTIONS "-fobjc-arc")
  target_link_libraries(dreamseed_engine PUBLIC "-framework Foundation" "-framework Metal")
else()
  target_sources(dreamseed_engine PRIVATE engine/src/placement_stub.cpp)
endif()
target_compile_definitions(dreamseed_engine PRIVATE DREAMSEED_VERSION="${PROJECT_VERSION}")
target_include_directories(dreamseed_engine PUBLIC engine/include)
target_include_directories(dreamseed_engine PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/generated")
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
