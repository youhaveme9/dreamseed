#include "dreamseed/engine.hpp"

#include <atomic>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>

using dreamseed::Engine;
using dreamseed::EngineError;
using dreamseed::Json;

namespace {

int failures = 0;

void check(bool condition, const std::string& name) {
    if (condition) return;
    ++failures;
    std::cerr << "FAIL: " << name << '\n';
}

template <class Function>
void rejects(Function function, const std::string& name) {
    try {
        function();
        check(false, name);
    } catch (const EngineError&) {
        check(true, name);
    }
}

Json basicRequest() {
    return {
        {"minecraft_version", "1.21.1"},
        {"reference_point", {{"x", 0}, {"z", 0}}},
        {"hard_constraints", Json::array({
            {{"id", "origin"}, {"type", "biome_at"}, {"biome", "plains"},
             {"coordinate", {{"x", 0}, {"z", 0}}}, {"y", 64}}
        })},
        {"soft_preferences", Json::array()},
        {"budget", {{"strategy", "sequential"}, {"start_seed", "0"},
                    {"max_candidates", 1}, {"max_seconds", 1}, {"workers", 1}}},
        {"max_results", 1}
    };
}

Json knownCombinedRequest() {
    auto request = basicRequest();
    request["hard_constraints"].push_back(
        {{"id", "village"}, {"type", "structure_within"}, {"structure", "village"},
         {"radius", 32}, {"count", 1}}
    );
    request["hard_constraints"].push_back(
        {{"id", "touching"}, {"type", "max_distance"}, {"from", "origin"},
         {"to", "village"}, {"max_distance", 0}}
    );
    request["soft_preferences"] = Json::array({
        {{"type", "minimize_distance"}, {"constraint_id", "village"}, {"weight", 1}}
    });
    request["budget"]["start_seed"] = "2579";
    return request;
}

}

int main() {
    check(Engine::parseSeed("0") == 0, "parse zero seed");
    check(Engine::parseSeed("-9223372036854775808") == std::numeric_limits<int64_t>::min(), "parse minimum seed");
    check(Engine::parseSeed("9223372036854775807") == std::numeric_limits<int64_t>::max(), "parse maximum seed");
    check(Engine::formatSeed(std::numeric_limits<uint64_t>::max()) == "-1", "format negative seed bits");
    rejects([] { Engine::parseSeed("9223372036854775808"); }, "reject seed overflow");
    rejects([] { Engine::parseSeed("1.0"); }, "reject noninteger seed");

    const auto capabilities = Engine::capabilities();
    check(capabilities["minecraft_versions"][0] == "1.21.1", "pinned version");
    check(capabilities["structure_filters"]["types"].size() == 10, "structure capabilities");

    const auto normalized = Engine::validateSearch(basicRequest());
    const auto renormalized = Engine::validateSearch(normalized);
    check(normalized == renormalized, "search normalization is idempotent");

    auto invalid = basicRequest();
    invalid["minecraft_version"] = "1.20.6";
    rejects([&] { Engine::validateSearch(invalid); }, "reject unsupported version");
    invalid = basicRequest();
    invalid["hard_constraints"][0]["type"] = "scenic_valley";
    rejects([&] { Engine::validateSearch(invalid); }, "reject unsupported condition");
    invalid = basicRequest();
    invalid["hard_constraints"][0]["coordinate"]["x"] = 40000000;
    rejects([&] { Engine::validateSearch(invalid); }, "reject coordinate bound");
    invalid = basicRequest();
    invalid["unexpected"] = true;
    rejects([&] { Engine::validateSearch(invalid); }, "reject unknown field");
    invalid = basicRequest();
    invalid["hard_constraints"] = Json::array({
        {{"id", "a"}, {"type", "biome_within"}, {"biome", "plains"},
         {"radius", 1024}, {"sample_step", 4}},
        {{"id", "b"}, {"type", "biome_within"}, {"biome", "forest"},
         {"radius", 1024}, {"sample_step", 4}},
        {{"id", "near"}, {"type", "max_distance"}, {"from", "a"},
         {"to", "b"}, {"max_distance", 100}}
    });
    invalid["budget"]["workers"] = 64;
    rejects([&] { Engine::validateSearch(invalid); }, "reject excessive relation grid memory");

    dreamseed::SearchControl cancelled;
    cancelled.cancelled.store(true);
    const auto cancelled_result = Engine::search(basicRequest(), &cancelled);
    check(cancelled_result["state"] == "cancelled", "search cancellation");
    check(cancelled_result["candidates_evaluated"] == 0, "cancel before evaluation");

    const auto combined = Engine::search(knownCombinedRequest());
    check(combined["state"] == "completed", "combined search completes");
    check(combined["matching_seeds_found"] == 1, "known combined fixture matches");
    check(combined["results"][0]["seed"] == "2579", "full world seed is returned");
    check(combined["results"][0]["satisfied_hard_constraints"].size() == 3, "all hard constraints satisfied");
    check(combined["results"][0]["spatial_checks"].size() == 1, "spatial check reported");
    check(combined["results"][0]["spatial_checks"][0]["measured_distance"] == 0.0,
          "spatial distance reported");
    check(combined["results"][0]["soft_preference_score"] == 100.0, "distance score");

    auto alternate_pair = basicRequest();
    alternate_pair["hard_constraints"] = Json::array({
        {{"id", "left"}, {"type", "structure_within"}, {"structure", "village"},
         {"anchor", {{"x", 0}, {"z", 0}}}, {"radius", 2000}, {"count", 1}},
        {{"id", "right"}, {"type", "structure_within"}, {"structure", "village"},
         {"anchor", {{"x", 2000}, {"z", 0}}}, {"radius", 2000}, {"count", 1}},
        {{"id", "overlap"}, {"type", "max_distance"}, {"from", "left"},
         {"to", "right"}, {"max_distance", 0}}
    });
    const auto alternate_result = Engine::search(alternate_pair);
    check(alternate_result["matching_seeds_found"] == 1, "alternate spatial pair matches");
    if (!alternate_result["results"].empty()) {
        const auto& result = alternate_result["results"][0];
        check(result["features"][0]["coordinates"] != result["features"][1]["coordinates"],
              "reported nearest features differ");
        check(result["spatial_checks"][0]["measured_distance"] == 0.0,
              "relation considers unreported viable features");
    }

    auto biome_radius = basicRequest();
    biome_radius["hard_constraints"] = Json::array({
        {{"id", "forest"}, {"type", "biome_within"}, {"biome", "forest"},
         {"radius", 32}, {"y", 64}, {"sample_step", 16}}
    });
    const auto biome_result = Engine::search(biome_radius);
    check(biome_result["matching_seeds_found"] == 1, "biome radius filter");
    check(biome_result["results"][0]["features"][0]["name"] == "forest", "biome result name");

    auto upstream_biome = basicRequest();
    upstream_biome["hard_constraints"][0]["biome"] = "mushroom_fields";
    upstream_biome["hard_constraints"][0]["y"] = 63;
    upstream_biome["budget"]["start_seed"] = "262";
    const auto upstream_result = Engine::search(upstream_biome);
    check(upstream_result["matching_seeds_found"] == 1, "upstream Cubiomes biome fixture");

    auto pyramid = basicRequest();
    pyramid["hard_constraints"] = Json::array({
        {{"id", "pyramid"}, {"type", "structure_within"}, {"structure", "desert_pyramid"},
         {"radius", 64}, {"count", 1}}
    });
    pyramid["budget"]["start_seed"] = "1436";
    const auto pyramid_result = Engine::search(pyramid);
    check(pyramid_result["matching_seeds_found"] == 1, "desert pyramid filter");
    if (!pyramid_result["results"].empty()) {
        check(!pyramid_result["results"][0]["caveats"].empty(), "desert pyramid terrain caveat");
    }

    auto outpost = basicRequest();
    outpost["hard_constraints"] = Json::array({
        {{"id", "outpost"}, {"type", "structure_within"}, {"structure", "pillager_outpost"},
         {"radius", 1000}, {"count", 1}}
    });
    outpost["budget"]["max_candidates"] = 1000;
    const auto outpost_result = Engine::search(outpost);
    check(outpost_result["matching_seeds_found"] > 0, "phase two structure filter");
    if (!outpost_result["results"].empty()) {
        check(outpost_result["results"][0]["features"][0]["name"] == "pillager_outpost",
              "phase two structure result name");
    }

    for (const auto& name_json : capabilities["structure_filters"]["types"]) {
        const auto name = name_json.get<std::string>();
        auto structure = basicRequest();
        structure["hard_constraints"] = Json::array({
            {{"id", "target"}, {"type", "structure_within"}, {"structure", name},
             {"radius", 10000}, {"count", 1}}
        });
        const auto structure_result = Engine::search(structure);
        const bool found = !structure_result["results"].empty();
        check(found, "seed zero structure fixture for " + name);
        if (found) {
            check(structure_result["results"][0]["features"][0]["name"] == name,
                  "structure fixture name for " + name);
        }
    }

    auto village_count = basicRequest();
    village_count["hard_constraints"] = Json::array({
        {{"id", "villages"}, {"type", "structure_within"}, {"structure", "village"},
         {"radius", 1000}, {"count", 3}}
    });
    village_count["budget"]["start_seed"] = "2";
    const auto count_result = Engine::search(village_count);
    check(count_result["results"][0]["features"].size() == 3, "multiple structure count");

    auto timeout = biome_radius;
    timeout["hard_constraints"][0]["biome"] = "cherry_grove";
    timeout["hard_constraints"][0]["radius"] = 1024;
    timeout["hard_constraints"][0]["sample_step"] = 4;
    timeout["budget"]["max_candidates"] = 1000000;
    timeout["budget"]["max_seconds"] = 0.05;
    const auto timeout_result = Engine::search(timeout);
    check(timeout_result["state"] == "timed_out", "search timeout");

    return failures == 0 ? 0 : 1;
}
