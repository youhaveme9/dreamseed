#include "dreamseed/engine.hpp"

#include <algorithm>
#include <array>
#include <bit>
#include <charconv>
#include <chrono>
#include <cmath>
#include <limits>
#include <map>
#include <mutex>
#include <set>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <vector>

extern "C" {
#include "finders.h"
#include "generator.h"
#include "util.h"
}

namespace dreamseed {
namespace {

struct VersionSpec {
    const char* name;
    int cubiomes_id;
};

constexpr VersionSpec kTargetVersion{"1.21.1", MC_1_21_1};
constexpr int kCoordinateLimit = 30000000;
constexpr uint64_t kMaxRelationGridPointsAcrossWorkers = 4000000;

struct Point {
    int x;
    int z;
};

struct Feature {
    std::string constraint_id;
    std::string kind;
    std::string name;
    int x;
    int y;
    int z;
    double distance;
    std::string status;
};

struct SpatialMatch {
    bool matched = false;
    double distance = std::numeric_limits<double>::infinity();
    Pos from{};
    Pos to{};
};

struct StructureSpec {
    const char* name;
    int cubiomes_id;
    bool terrain_limited;
};

constexpr std::array<StructureSpec, 10> kStructures{{
    {"village", Village, false},
    {"desert_pyramid", Desert_Pyramid, true},
    {"jungle_temple", Jungle_Temple, true},
    {"swamp_hut", Swamp_Hut, false},
    {"igloo", Igloo, false},
    {"ocean_ruin", Ocean_Ruin, false},
    {"shipwreck", Shipwreck, false},
    {"ocean_monument", Monument, false},
    {"woodland_mansion", Mansion, true},
    {"pillager_outpost", Outpost, false},
}};

void rejectUnknown(const Json& object, std::initializer_list<std::string_view> allowed,
                   const std::string& path) {
    if (!object.is_object()) return;
    for (auto it = object.begin(); it != object.end(); ++it) {
        const bool known = std::any_of(allowed.begin(), allowed.end(), [&](std::string_view key) {
            return key == it.key();
        });
        if (!known) throw EngineError("unknown_field", path + "/" + it.key(), "field is not allowed");
    }
}

int integer(const Json& object, const char* key, int low, int high,
            const std::string& path, int fallback, bool required = false) {
    if (!object.contains(key)) {
        if (required) {
            throw EngineError("missing_field", path + "/" + key, "field is required");
        }
        return fallback;
    }
    if (!object.at(key).is_number_integer()) {
        throw EngineError("invalid_type", path + "/" + key, "expected an integer");
    }
    const auto value = object.at(key).get<int64_t>();
    if (value < low || value > high) {
        throw EngineError("out_of_range", path + "/" + key, "integer is outside the supported range");
    }
    return static_cast<int>(value);
}

double number(const Json& object, const char* key, double low, double high,
              const std::string& path, double fallback, bool required = false) {
    if (!object.contains(key)) {
        if (required) {
            throw EngineError("missing_field", path + "/" + key, "field is required");
        }
        return fallback;
    }
    if (!object.at(key).is_number()) {
        throw EngineError("invalid_type", path + "/" + key, "expected a number");
    }
    const double value = object.at(key).get<double>();
    if (!std::isfinite(value) || value < low || value > high) {
        throw EngineError("out_of_range", path + "/" + key, "number is outside the supported range");
    }
    return value;
}

std::string textField(const Json& object, const char* key, const std::string& path,
                      bool required = true, const std::string& fallback = {}) {
    if (!object.contains(key)) {
        if (required) {
            throw EngineError("missing_field", path + "/" + key, "field is required");
        }
        return fallback;
    }
    if (!object.at(key).is_string()) {
        throw EngineError("invalid_type", path + "/" + key, "expected a string");
    }
    const auto value = object.at(key).get<std::string>();
    if (value.empty() || value.size() > 80) {
        throw EngineError("invalid_value", path + "/" + key, "string length must be between 1 and 80");
    }
    return value;
}

Point point(const Json& object, const std::string& path, Point fallback, bool required = false) {
    if (object.is_null()) {
        if (required) {
            throw EngineError("missing_field", path, "coordinate is required");
        }
        return fallback;
    }
    if (!object.is_object()) {
        throw EngineError("invalid_type", path, "expected an object with x and z");
    }
    rejectUnknown(object, {"x", "z"}, path);
    return {
        integer(object, "x", -kCoordinateLimit, kCoordinateLimit, path, fallback.x, required),
        integer(object, "z", -kCoordinateLimit, kCoordinateLimit, path, fallback.z, required)
    };
}

int biomeId(const std::string& name) {
    static const std::unordered_map<std::string, int> ids = {
        {"ocean", ocean}, {"plains", plains}, {"desert", desert},
        {"windswept_hills", mountains}, {"forest", forest}, {"taiga", taiga},
        {"swamp", swamp}, {"river", river}, {"snowy_plains", snowy_tundra},
        {"mushroom_fields", mushroom_fields}, {"jungle", jungle},
        {"savanna", savanna}, {"badlands", badlands}, {"meadow", meadow},
        {"grove", grove}, {"snowy_slopes", snowy_slopes},
        {"jagged_peaks", jagged_peaks}, {"frozen_peaks", frozen_peaks},
        {"stony_peaks", stony_peaks}, {"mangrove_swamp", mangrove_swamp},
        {"cherry_grove", cherry_grove}
    };
    const auto it = ids.find(name);
    return it == ids.end() ? none : it->second;
}

const std::vector<std::string>& biomeNames() {
    static const std::vector<std::string> names = {
        "ocean", "plains", "desert", "windswept_hills", "forest", "taiga",
        "swamp", "river", "snowy_plains", "mushroom_fields", "jungle",
        "savanna", "badlands", "meadow", "grove", "snowy_slopes",
        "jagged_peaks", "frozen_peaks", "stony_peaks", "mangrove_swamp",
        "cherry_grove"
    };
    return names;
}

const StructureSpec* structureSpec(const std::string& name) {
    const auto it = std::find_if(kStructures.begin(), kStructures.end(), [&](const auto& spec) {
        return name == spec.name;
    });
    return it == kStructures.end() ? nullptr : &*it;
}

int structureId(const std::string& name) {
    const auto* spec = structureSpec(name);
    return spec ? spec->cubiomes_id : -1;
}

Json structureNames() {
    Json names = Json::array();
    for (const auto& spec : kStructures) names.push_back(spec.name);
    return names;
}

std::string structureStatus(const StructureSpec& spec) {
    return spec.terrain_limited
        ? "placement_biome_and_terrain_heuristic_confirmed_exact_terrain_unconfirmed"
        : "placement_and_cubiomes_viability_confirmed";
}

int floorDiv(int value, int divisor) {
    int quotient = value / divisor;
    int remainder = value % divisor;
    if (remainder < 0) --quotient;
    return quotient;
}

double distance(int x1, int z1, int x2, int z2) {
    return std::hypot(static_cast<double>(x1) - x2, static_cast<double>(z1) - z2);
}

uint64_t pointKey(int x, int z) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(x)) << 32) |
           static_cast<uint32_t>(z);
}

SpatialMatch nearestWithin(const std::vector<Pos>& from, const std::vector<Pos>& to,
                           double maximum) {
    const int cell_size = std::max(1, static_cast<int>(std::ceil(maximum)));
    std::unordered_map<uint64_t, std::vector<Pos>> cells;
    for (const auto& pos : to) {
        cells[pointKey(floorDiv(pos.x, cell_size), floorDiv(pos.z, cell_size))].push_back(pos);
    }
    SpatialMatch best;
    for (const auto& left : from) {
        const int cell_x = floorDiv(left.x, cell_size);
        const int cell_z = floorDiv(left.z, cell_size);
        for (int dz = -1; dz <= 1; ++dz) {
            for (int dx = -1; dx <= 1; ++dx) {
                const auto it = cells.find(pointKey(cell_x + dx, cell_z + dz));
                if (it == cells.end()) continue;
                for (const auto& right : it->second) {
                    const double measured = distance(left.x, left.z, right.x, right.z);
                    if (measured <= maximum && measured < best.distance) {
                        best = {true, measured, left, right};
                    }
                }
            }
        }
    }
    return best;
}

Json coordinate(int x, int z, int y = std::numeric_limits<int>::min()) {
    Json out = {{"x", x}, {"z", z}};
    if (y != std::numeric_limits<int>::min()) out["y"] = y;
    return out;
}

std::vector<Pos> structureAttempts(uint64_t seed, int type, Point anchor, int radius) {
    StructureConfig config{};
    if (!getStructureConfig(type, kTargetVersion.cubiomes_id, &config)) return {};
    const int span = config.regionSize * 16;
    const int min_rx = floorDiv(anchor.x - radius, span) - 1;
    const int max_rx = floorDiv(anchor.x + radius, span) + 1;
    const int min_rz = floorDiv(anchor.z - radius, span) - 1;
    const int max_rz = floorDiv(anchor.z + radius, span) + 1;
    std::vector<Pos> positions;
    for (int rz = min_rz; rz <= max_rz; ++rz) {
        for (int rx = min_rx; rx <= max_rx; ++rx) {
            Pos pos{};
            if (!getStructurePos(type, kTargetVersion.cubiomes_id, seed, rx, rz, &pos)) continue;
            if (distance(pos.x, pos.z, anchor.x, anchor.z) <= radius) positions.push_back(pos);
        }
    }
    std::sort(positions.begin(), positions.end(), [&](const Pos& left, const Pos& right) {
        const double ld = distance(left.x, left.z, anchor.x, anchor.z);
        const double rd = distance(right.x, right.z, anchor.x, anchor.z);
        if (ld != rd) return ld < rd;
        if (left.x != right.x) return left.x < right.x;
        return left.z < right.z;
    });
    return positions;
}

Json normalizeSearch(const Json& input) {
    if (!input.is_object()) {
        throw EngineError("invalid_type", "/", "search request must be an object");
    }
    rejectUnknown(input, {"minecraft_version", "reference_point", "hard_constraints",
                          "soft_preferences", "budget", "max_results"}, "");
    Json out;
    const auto version = textField(input, "minecraft_version", "/");
    if (version != kTargetVersion.name) {
        throw EngineError("unsupported_version", "/minecraft_version", "only Minecraft Java 1.21.1 is supported");
    }
    out["minecraft_version"] = version;
    const Point reference = point(input.value("reference_point", Json(nullptr)),
                                  "/reference_point", {0, 0});
    out["reference_point"] = coordinate(reference.x, reference.z);

    if (!input.contains("hard_constraints") || !input.at("hard_constraints").is_array()) {
        throw EngineError("missing_field", "/hard_constraints", "hard_constraints must be an array");
    }
    if (input.at("hard_constraints").empty() || input.at("hard_constraints").size() > 16) {
        throw EngineError("out_of_range", "/hard_constraints", "provide between 1 and 16 hard constraints");
    }

    Json hard = Json::array();
    std::unordered_set<std::string> ids;
    std::unordered_map<std::string, std::string> kinds;
    size_t index = 0;
    for (const auto& raw : input.at("hard_constraints")) {
        const std::string path = "/hard_constraints/" + std::to_string(index++);
        if (!raw.is_object()) throw EngineError("invalid_type", path, "constraint must be an object");
        const auto id = textField(raw, "id", path);
        if (!ids.insert(id).second) throw EngineError("duplicate_id", path + "/id", "constraint id must be unique");
        const auto type = textField(raw, "type", path);
        Json item = {{"id", id}, {"type", type}};
        if (type == "biome_at") {
            rejectUnknown(raw, {"id", "type", "biome", "coordinate", "y"}, path);
            const auto biome = textField(raw, "biome", path);
            if (biomeId(biome) == none) throw EngineError("unsupported_biome", path + "/biome", "biome is not supported");
            const Point at = point(raw.value("coordinate", Json(nullptr)), path + "/coordinate", reference);
            item["biome"] = biome;
            item["coordinate"] = coordinate(at.x, at.z);
            item["y"] = integer(raw, "y", -64, 320, path, 64);
            kinds[id] = "feature";
        } else if (type == "biome_within") {
            rejectUnknown(raw, {"id", "type", "biome", "radius", "anchor", "y", "sample_step"}, path);
            const auto biome = textField(raw, "biome", path);
            if (biomeId(biome) == none) throw EngineError("unsupported_biome", path + "/biome", "biome is not supported");
            const Point anchor = point(raw.value("anchor", Json(nullptr)), path + "/anchor", reference);
            const int step = integer(raw, "sample_step", 4, 64, path, 16);
            if (step % 4 != 0) throw EngineError("invalid_value", path + "/sample_step", "sample_step must be a multiple of 4");
            item["biome"] = biome;
            item["anchor"] = coordinate(anchor.x, anchor.z);
            item["radius"] = integer(raw, "radius", 0, 1024, path, 0, true);
            item["y"] = integer(raw, "y", -64, 320, path, 64);
            item["sample_step"] = step;
            kinds[id] = "feature";
        } else if (type == "structure_within") {
            rejectUnknown(raw, {"id", "type", "structure", "radius", "count", "anchor"}, path);
            const auto structure = textField(raw, "structure", path);
            if (structureId(structure) < 0) throw EngineError("unsupported_structure", path + "/structure", "structure is not supported");
            const Point anchor = point(raw.value("anchor", Json(nullptr)), path + "/anchor", reference);
            item["structure"] = structure;
            item["anchor"] = coordinate(anchor.x, anchor.z);
            item["radius"] = integer(raw, "radius", 0, 10000, path, 0, true);
            item["count"] = integer(raw, "count", 1, 16, path, 1);
            kinds[id] = "feature";
        } else if (type == "max_distance") {
            rejectUnknown(raw, {"id", "type", "from", "to", "max_distance"}, path);
            item["from"] = textField(raw, "from", path);
            item["to"] = textField(raw, "to", path);
            item["max_distance"] = number(raw, "max_distance", 0, 20000, path, 0, true);
            kinds[id] = "relation";
        } else {
            throw EngineError("unsupported_condition", path + "/type", "constraint type is not supported");
        }
        hard.push_back(std::move(item));
    }
    for (size_t i = 0; i < hard.size(); ++i) {
        if (hard[i]["type"] != "max_distance") continue;
        const auto from = hard[i]["from"].get<std::string>();
        const auto to = hard[i]["to"].get<std::string>();
        if (!kinds.contains(from) || !kinds.contains(to) || kinds[from] != "feature" || kinds[to] != "feature") {
            throw EngineError("invalid_reference", "/hard_constraints/" + std::to_string(i), "distance references must name feature constraints");
        }
        if (from == to) throw EngineError("invalid_reference", "/hard_constraints/" + std::to_string(i), "distance references must be different");
    }
    out["hard_constraints"] = std::move(hard);

    Json soft = Json::array();
    const Json raw_soft = input.value("soft_preferences", Json::array());
    if (!raw_soft.is_array() || raw_soft.size() > 16) {
        throw EngineError("out_of_range", "/soft_preferences", "soft_preferences must contain at most 16 items");
    }
    for (size_t i = 0; i < raw_soft.size(); ++i) {
        const auto& raw = raw_soft[i];
        const std::string path = "/soft_preferences/" + std::to_string(i);
        if (!raw.is_object()) throw EngineError("invalid_type", path, "preference must be an object");
        rejectUnknown(raw, {"type", "constraint_id", "weight"}, path);
        const auto type = textField(raw, "type", path);
        if (type != "minimize_distance") {
            throw EngineError("unsupported_condition", path + "/type", "preference type is not supported");
        }
        const auto target = textField(raw, "constraint_id", path);
        if (!kinds.contains(target) || kinds[target] != "feature") {
            throw EngineError("invalid_reference", path + "/constraint_id", "preference must reference a feature constraint");
        }
        soft.push_back({{"type", type}, {"constraint_id", target},
                        {"weight", number(raw, "weight", 0.01, 100.0, path, 1.0)}});
    }
    out["soft_preferences"] = std::move(soft);

    const Json raw_budget = input.value("budget", Json::object());
    if (!raw_budget.is_object()) throw EngineError("invalid_type", "/budget", "budget must be an object");
    rejectUnknown(raw_budget, {"strategy", "max_candidates", "max_seconds", "workers",
                               "start_seed", "sample_seed"}, "/budget");
    const auto strategy = textField(raw_budget, "strategy", "/budget", false, "sampled");
    if (strategy != "sampled" && strategy != "sequential") {
        throw EngineError("unsupported_strategy", "/budget/strategy", "strategy must be sampled or sequential");
    }
    const unsigned hardware = std::max(1u, std::thread::hardware_concurrency());
    Json budget = {
        {"strategy", strategy},
        {"max_candidates", integer(raw_budget, "max_candidates", 1, 10000000, "/budget", 100000)},
        {"max_seconds", number(raw_budget, "max_seconds", 0.05, 300.0, "/budget", 10.0)},
        {"workers", integer(raw_budget, "workers", 1, 64, "/budget", static_cast<int>(std::min(4u, hardware)))}
    };
    const auto seed_key = strategy == "sampled" ? "sample_seed" : "start_seed";
    std::string seed_text = "0";
    if (raw_budget.contains(seed_key)) {
        if (!raw_budget.at(seed_key).is_string()) {
            throw EngineError("invalid_type", std::string("/budget/") + seed_key, "seed must be a decimal string");
        }
        seed_text = raw_budget.at(seed_key).get<std::string>();
        Engine::parseSeed(seed_text);
    }
    budget[seed_key] = seed_text;
    out["budget"] = std::move(budget);
    out["max_results"] = integer(input, "max_results", 1, 100, "/", 10);

    std::unordered_set<std::string> relation_ids;
    for (const auto& constraint : out["hard_constraints"]) {
        if (constraint["type"] != "max_distance") continue;
        relation_ids.insert(constraint["from"].get<std::string>());
        relation_ids.insert(constraint["to"].get<std::string>());
    }
    uint64_t relation_grid_bound = 0;
    for (const auto& constraint : out["hard_constraints"]) {
        if (constraint["type"] != "biome_within" ||
            !relation_ids.contains(constraint["id"].get<std::string>())) continue;
        const uint64_t radius = constraint["radius"];
        const uint64_t step = constraint["sample_step"];
        const uint64_t side = (2 * radius) / step + 1;
        relation_grid_bound += side * side + 1;
    }
    const uint64_t workers = out["budget"]["workers"];
    if (relation_grid_bound * workers > kMaxRelationGridPointsAcrossWorkers) {
        throw EngineError("resource_limit", "/hard_constraints",
                          "biome distance relations exceed the grid memory limit; reduce workers or radius, or increase sample_step");
    }
    return out;
}

std::vector<Feature> findBiomeWithin(const Json& constraint, Generator& generator,
                                     const std::atomic_bool* cancelled,
                                     std::chrono::steady_clock::time_point deadline,
                                     std::vector<Pos>* matching_positions,
                                     bool* interrupted) {
    const Point anchor{constraint["anchor"]["x"], constraint["anchor"]["z"]};
    const int radius = constraint["radius"];
    const int step = constraint["sample_step"];
    const int y = constraint["y"];
    const int target = biomeId(constraint["biome"]);
    Feature best{};
    bool found = false;
    for (int dz = -radius; dz <= radius; dz += step) {
        if (cancelled && cancelled->load(std::memory_order_relaxed)) {
            *interrupted = true;
            return {};
        }
        if (std::chrono::steady_clock::now() >= deadline) {
            *interrupted = true;
            return {};
        }
        for (int dx = -radius; dx <= radius; dx += step) {
            const double d = std::hypot(static_cast<double>(dx), static_cast<double>(dz));
            if (d > radius) continue;
            const int x = anchor.x + dx;
            const int z = anchor.z + dz;
            if (getBiomeAt(&generator, 1, x, y, z) != target) continue;
            if (matching_positions) matching_positions->push_back({x, z});
            if (!found || d < best.distance) {
                best = {constraint["id"], "biome", constraint["biome"], x, y, z, d,
                        "confirmed_at_sample_coordinate"};
                found = true;
            }
        }
    }
    if (radius % step != 0 && getBiomeAt(&generator, 1, anchor.x, y, anchor.z) == target) {
        if (matching_positions) matching_positions->push_back({anchor.x, anchor.z});
        best = {constraint["id"], "biome", constraint["biome"], anchor.x, y, anchor.z, 0,
                "confirmed_at_sample_coordinate"};
        found = true;
    }
    return found ? std::vector<Feature>{best} : std::vector<Feature>{};
}

Json featureJson(const Feature& feature) {
    return {
        {"constraint_id", feature.constraint_id},
        {"kind", feature.kind},
        {"name", feature.name},
        {"coordinates", coordinate(feature.x, feature.z,
            feature.y == std::numeric_limits<int>::min() ? std::numeric_limits<int>::min() : feature.y)},
        {"distance_from_anchor", feature.distance},
        {"distance_metric", "horizontal_euclidean_blocks"},
        {"placement_status", feature.status}
    };
}

uint64_t splitmix64(uint64_t value) {
    value += 0x9e3779b97f4a7c15ULL;
    value = (value ^ (value >> 30)) * 0xbf58476d1ce4e5b9ULL;
    value = (value ^ (value >> 27)) * 0x94d049bb133111ebULL;
    return value ^ (value >> 31);
}

Json evaluateSeed(const Json& request, uint64_t seed, const std::atomic_bool* cancelled,
                  std::chrono::steady_clock::time_point deadline) {
    std::unordered_set<std::string> relation_features;
    for (const auto& constraint : request["hard_constraints"]) {
        if (constraint["type"] != "max_distance") continue;
        relation_features.insert(constraint["from"].get<std::string>());
        relation_features.insert(constraint["to"].get<std::string>());
    }
    std::unordered_map<std::string, std::vector<Pos>> attempts;
    for (const auto& constraint : request["hard_constraints"]) {
        if (constraint["type"] != "structure_within") continue;
        const Point anchor{constraint["anchor"]["x"], constraint["anchor"]["z"]};
        auto positions = structureAttempts(seed, structureId(constraint["structure"]), anchor,
                                           constraint["radius"]);
        if (positions.size() < constraint["count"].get<size_t>()) return {{"matched", false}};
        attempts[constraint["id"]] = std::move(positions);
    }

    Generator generator{};
    setupGenerator(&generator, kTargetVersion.cubiomes_id, 0);
    applySeed(&generator, DIM_OVERWORLD, seed);
    std::unordered_map<std::string, std::vector<Feature>> features;
    std::unordered_map<std::string, std::vector<Pos>> relation_points;
    std::unordered_set<std::string> satisfied;
    std::set<std::string> terrain_limited_structures;
    bool sampled_biome = false;

    for (const auto& constraint : request["hard_constraints"]) {
        if (cancelled && cancelled->load(std::memory_order_relaxed)) return {{"matched", false}, {"interrupted", true}};
        if (std::chrono::steady_clock::now() >= deadline) return {{"matched", false}, {"interrupted", true}};
        const auto type = constraint["type"].get<std::string>();
        const auto id = constraint["id"].get<std::string>();
        if (type == "biome_at") {
            const int x = constraint["coordinate"]["x"];
            const int z = constraint["coordinate"]["z"];
            const int y = constraint["y"];
            if (getBiomeAt(&generator, 1, x, y, z) != biomeId(constraint["biome"])) return {{"matched", false}};
            features[id].push_back({id, "biome", constraint["biome"], x, y, z, 0,
                                    "confirmed_at_exact_coordinate"});
            if (relation_features.contains(id)) relation_points[id].push_back({x, z});
            satisfied.insert(id);
        } else if (type == "structure_within") {
            const int target_count = constraint["count"];
            const int stype = structureId(constraint["structure"]);
            const auto* spec = structureSpec(constraint["structure"]);
            const Point anchor{constraint["anchor"]["x"], constraint["anchor"]["z"]};
            size_t viable_count = 0;
            for (const auto& pos : attempts[id]) {
                if (!isViableStructurePos(stype, &generator, pos.x, pos.z, 0)) continue;
                if (spec->terrain_limited && !isViableStructureTerrain(stype, &generator, pos.x, pos.z)) continue;
                ++viable_count;
                if (relation_features.contains(id)) relation_points[id].push_back(pos);
                const bool terrain_unknown = spec->terrain_limited;
                if (features[id].size() < static_cast<size_t>(target_count)) {
                    features[id].push_back({id, "structure", constraint["structure"], pos.x,
                        std::numeric_limits<int>::min(), pos.z,
                        distance(pos.x, pos.z, anchor.x, anchor.z),
                        structureStatus(*spec)});
                }
                if (terrain_unknown) terrain_limited_structures.insert(spec->name);
                if (viable_count >= static_cast<size_t>(target_count) &&
                    !relation_features.contains(id)) break;
            }
            if (viable_count < static_cast<size_t>(target_count)) return {{"matched", false}};
            satisfied.insert(id);
        } else if (type == "biome_within") {
            bool interrupted = false;
            auto* points = relation_features.contains(id) ? &relation_points[id] : nullptr;
            auto found = findBiomeWithin(constraint, generator, cancelled, deadline, points, &interrupted);
            if (interrupted) return {{"matched", false}, {"interrupted", true}};
            if (found.empty()) return {{"matched", false}};
            features[id] = std::move(found);
            sampled_biome = true;
            satisfied.insert(id);
        }
    }

    Json spatial_checks = Json::array();
    for (const auto& constraint : request["hard_constraints"]) {
        if (constraint["type"] != "max_distance") continue;
        const auto id = constraint["id"].get<std::string>();
        const auto from = constraint["from"].get<std::string>();
        const auto to = constraint["to"].get<std::string>();
        const double maximum = constraint["max_distance"];
        const auto nearest = nearestWithin(relation_points[from], relation_points[to], maximum);
        if (!nearest.matched) return {{"matched", false}};
        spatial_checks.push_back({
            {"constraint_id", id},
            {"operation", "max_distance"},
            {"from_constraint", from},
            {"to_constraint", to},
            {"maximum_distance", maximum},
            {"measured_distance", nearest.distance},
            {"from_coordinates", coordinate(nearest.from.x, nearest.from.z)},
            {"to_coordinates", coordinate(nearest.to.x, nearest.to.z)},
            {"distance_metric", "horizontal_euclidean_blocks"}
        });
        satisfied.insert(id);
    }

    double weighted_score = 0;
    double total_weight = 0;
    Json breakdown = Json::array();
    for (const auto& preference : request["soft_preferences"]) {
        const auto id = preference["constraint_id"].get<std::string>();
        double nearest = std::numeric_limits<double>::infinity();
        for (const auto& feature : features[id]) nearest = std::min(nearest, feature.distance);
        double radius = 1;
        for (const auto& constraint : request["hard_constraints"]) {
            if (constraint["id"] != id) continue;
            if (constraint.contains("radius")) radius = std::max(1.0, constraint["radius"].get<double>());
        }
        const double closeness = std::clamp(1.0 - nearest / radius, 0.0, 1.0);
        const double weight = preference["weight"];
        weighted_score += closeness * weight;
        total_weight += weight;
        breakdown.push_back({{"type", "minimize_distance"}, {"constraint_id", id},
                             {"measured_distance", nearest}, {"weight", weight},
                             {"normalized_value", closeness}});
    }
    const double score = total_weight == 0 ? 0 : 100.0 * weighted_score / total_weight;

    Json feature_list = Json::array();
    std::set<std::string> names;
    for (const auto& constraint : request["hard_constraints"]) {
        const auto id = constraint["id"].get<std::string>();
        if (!features.contains(id)) continue;
        for (const auto& feature : features[id]) {
            feature_list.push_back(featureJson(feature));
            names.insert(feature.name);
        }
    }
    Json caveats = Json::array();
    for (const auto& name : terrain_limited_structures) {
        caveats.push_back("Exact terrain generation is not confirmed for " + name +
                          "; Cubiomes placement, biome viability, and the terrain heuristic passed.");
    }
    if (sampled_biome) {
        caveats.push_back("Biome radius constraints inspect a deterministic grid. A match is exact at its reported coordinate, but the grid can miss biomes between samples.");
    }
    Json satisfied_list = Json::array();
    for (const auto& constraint : request["hard_constraints"]) {
        const auto id = constraint["id"].get<std::string>();
        if (satisfied.contains(id)) satisfied_list.push_back(id);
    }
    return {
        {"matched", true},
        {"result", {
            {"seed", Engine::formatSeed(seed)},
            {"minecraft_version", kTargetVersion.name},
            {"edition", "Java"},
            {"reference_point", request["reference_point"]},
            {"matching_feature_names", std::vector<std::string>(names.begin(), names.end())},
            {"features", std::move(feature_list)},
            {"satisfied_hard_constraints", std::move(satisfied_list)},
            {"spatial_checks", std::move(spatial_checks)},
            {"soft_preference_score", score},
            {"score_breakdown", std::move(breakdown)},
            {"validation_status", terrain_limited_structures.empty() ? "verified_by_supported_cubiomes_checks" : "verified_with_documented_terrain_caveat"},
            {"caveats", std::move(caveats)}
        }}
    };
}

bool betterResult(const Json& left, const Json& right) {
    const double ls = left["soft_preference_score"];
    const double rs = right["soft_preference_score"];
    if (ls != rs) return ls > rs;
    return Engine::parseSeed(left["seed"]) < Engine::parseSeed(right["seed"]);
}

Json normalizeInspect(const Json& input) {
    if (!input.is_object()) throw EngineError("invalid_type", "/", "inspect request must be an object");
    rejectUnknown(input, {"minecraft_version", "seed", "area", "structures"}, "");
    const auto version = textField(input, "minecraft_version", "/");
    if (version != kTargetVersion.name) throw EngineError("unsupported_version", "/minecraft_version", "only Minecraft Java 1.21.1 is supported");
    if (!input.contains("seed") || !input["seed"].is_string()) {
        throw EngineError("invalid_type", "/seed", "seed must be a signed 64 bit decimal string");
    }
    Engine::parseSeed(input["seed"]);
    const Json raw_area = input.value("area", Json::object());
    if (!raw_area.is_object()) throw EngineError("invalid_type", "/area", "area must be an object");
    rejectUnknown(raw_area, {"center", "radius", "sample_step", "y"}, "/area");
    const Point center = point(raw_area.value("center", Json(nullptr)), "/area/center", {0, 0});
    const int radius = integer(raw_area, "radius", 0, 2048, "/area", 512);
    const int step = integer(raw_area, "sample_step", 4, 128, "/area", 16);
    if (step % 4 != 0) throw EngineError("invalid_value", "/area/sample_step", "sample_step must be a multiple of 4");
    const int width = radius * 2 / step + 1;
    if (static_cast<int64_t>(width) * width > 200000) {
        throw EngineError("resource_limit", "/area", "area sampling would exceed 200000 points");
    }
    Json structures = input.value("structures", Json::array({"village", "desert_pyramid"}));
    if (!structures.is_array() || structures.size() > 2) {
        throw EngineError("invalid_type", "/structures", "structures must be an array of supported names");
    }
    for (size_t i = 0; i < structures.size(); ++i) {
        if (!structures[i].is_string() || structureId(structures[i]) < 0) {
            throw EngineError("unsupported_structure", "/structures/" + std::to_string(i), "structure is not supported");
        }
    }
    return {{"minecraft_version", version}, {"seed", input["seed"]},
            {"area", {{"center", coordinate(center.x, center.z)}, {"radius", radius},
                      {"sample_step", step}, {"y", integer(raw_area, "y", -64, 320, "/area", 64)}}},
            {"structures", structures}};
}

}

EngineError::EngineError(std::string code, std::string path, std::string message)
    : std::runtime_error(std::move(message)), code_(std::move(code)), path_(std::move(path)) {}

Json EngineError::json() const {
    return {{"error", {{"code", code_}, {"path", path_}, {"message", what()}}}};
}

int64_t Engine::parseSeed(const std::string& value) {
    if (value.empty() || value.size() > 20 || value.front() == '+') {
        throw EngineError("invalid_seed", "/seed", "seed must be a signed 64 bit decimal string");
    }
    int64_t parsed = 0;
    const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
    if (result.ec != std::errc{} || result.ptr != value.data() + value.size()) {
        throw EngineError("invalid_seed", "/seed", "seed must be a signed 64 bit decimal string");
    }
    return parsed;
}

std::string Engine::formatSeed(uint64_t value) {
    return std::to_string(std::bit_cast<int64_t>(value));
}

Json Engine::capabilities() {
    return {
        {"engine", "DreamSeed"},
        {"engine_version", "0.1.0"},
        {"editions", Json::array({"Java"})},
        {"minecraft_versions", Json::array({kTargetVersion.name})},
        {"seed_encoding", "signed_64_bit_decimal_string"},
        {"structure_seed_semantics", "Placement filtering uses the lower 48 bits, then the complete 64 bit world seed is verified and returned."},
        {"biome_filters", {
            {"types", Json::array({"biome_at", "biome_within"})},
            {"biomes", biomeNames()},
            {"within_semantics", "deterministic horizontal sample grid at an explicit y coordinate"}
        }},
        {"structure_filters", {
            {"types", structureNames()},
            {"operations", Json::array({"within_radius", "minimum_count"})}
        }},
        {"spatial_operations", Json::array({"distance_from_explicit_anchor", "maximum_distance_between_features"})},
        {"distance_metric", "horizontal_euclidean_blocks"},
        {"search_strategies", Json::array({"sequential", "sampled"})},
        {"search_limits", {
            {"max_candidates", 10000000}, {"max_seconds", 300}, {"max_workers", 64},
            {"max_results", 100}, {"max_biome_radius", 1024}, {"max_structure_radius", 10000},
            {"max_coordinate_absolute", kCoordinateLimit},
            {"max_relation_grid_points_across_workers", kMaxRelationGridPointsAcrossWorkers}
        }},
        {"validation", {
            {"village", "structure placement and biome viability"},
            {"desert_pyramid", "placement, biome viability, and terrain heuristic; exact terrain unconfirmed"},
            {"jungle_temple", "placement, biome viability, and terrain heuristic; exact terrain unconfirmed"},
            {"swamp_hut", "structure placement and biome viability"},
            {"igloo", "structure placement and biome viability"},
            {"ocean_ruin", "structure placement and biome viability"},
            {"shipwreck", "structure placement and biome viability"},
            {"ocean_monument", "structure placement and monument biome viability"},
            {"woodland_mansion", "placement, biome viability, and terrain heuristic; exact terrain unconfirmed"},
            {"pillager_outpost", "structure placement, biome viability, and village exclusion"},
            {"biome_at", "exact Cubiomes lookup at the reported block coordinate"},
            {"biome_within", "exact lookups at deterministic sampled coordinates"}
        }},
        {"unsupported", Json::array({
            "actual world spawn constraints",
            "terrain shape and scenic quality",
            "block level structure confirmation",
            "Bedrock Edition",
            "versions other than Java 1.21.1"
        })},
        {"experimental", Json::array()},
        {"cubiomes_commit", "e61f90580cbdd883214a8054670dacae655e59c0"}
    };
}

Json Engine::validateSearch(const Json& request) {
    return normalizeSearch(request);
}

Json Engine::search(const Json& raw_request, SearchControl* supplied_control) {
    const Json request = normalizeSearch(raw_request);
    SearchControl local_control;
    SearchControl& control = supplied_control ? *supplied_control : local_control;
    const auto started = std::chrono::steady_clock::now();
    const auto deadline = started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(
        std::chrono::duration<double>(request["budget"]["max_seconds"].get<double>()));
    const uint64_t base = static_cast<uint64_t>(parseSeed(
        request["budget"].value("sample_seed", request["budget"].value("start_seed", "0"))));
    const uint64_t maximum = request["budget"]["max_candidates"];
    const int workers = request["budget"]["workers"];
    const int max_results = request["max_results"];
    const bool sampled = request["budget"]["strategy"] == "sampled";
    std::atomic<uint64_t> next{0};
    std::atomic<uint64_t> evaluated{0};
    std::atomic<uint64_t> matched{0};
    std::mutex result_mutex;
    std::mutex event_mutex;
    std::mutex progress_mutex;
    auto last_progress = started;
    std::vector<Json> results;

    auto emit = [&](const Json& event) {
        if (!control.event_callback) return;
        std::lock_guard lock(event_mutex);
        control.event_callback(event);
    };

    auto worker = [&]() {
        while (!control.cancelled.load(std::memory_order_relaxed)) {
            if (std::chrono::steady_clock::now() >= deadline) break;
            const uint64_t index = next.fetch_add(1, std::memory_order_relaxed);
            if (index >= maximum) break;
            const uint64_t seed = sampled ? splitmix64(base + index) : base + index;
            Json evaluation = evaluateSeed(request, seed, &control.cancelled, deadline);
            if (evaluation.value("interrupted", false)) break;
            const uint64_t done = evaluated.fetch_add(1, std::memory_order_relaxed) + 1;
            if (evaluation.value("matched", false)) {
                const uint64_t count = matched.fetch_add(1, std::memory_order_relaxed) + 1;
                Json result = std::move(evaluation["result"]);
                bool retained = false;
                {
                    std::lock_guard lock(result_mutex);
                    results.push_back(result);
                    std::sort(results.begin(), results.end(), betterResult);
                    if (results.size() > static_cast<size_t>(max_results)) results.resize(max_results);
                    retained = std::any_of(results.begin(), results.end(), [&](const Json& item) {
                        return item["seed"] == result["seed"];
                    });
                }
                if (retained) emit({{"event", "match"}, {"matches_found", count}, {"result", result}});
            }
            bool report = done == maximum;
            {
                std::lock_guard lock(progress_mutex);
                const auto now = std::chrono::steady_clock::now();
                if (now - last_progress >= std::chrono::milliseconds(250)) {
                    last_progress = now;
                    report = true;
                }
            }
            if (report) emit({{"event", "progress"}, {"candidates_evaluated", done},
                              {"matches_found", matched.load(std::memory_order_relaxed)}});
        }
    };

    std::vector<std::thread> threads;
    threads.reserve(workers);
    for (int i = 0; i < workers; ++i) threads.emplace_back(worker);
    for (auto& thread : threads) thread.join();
    const auto finished = std::chrono::steady_clock::now();
    const bool cancelled = control.cancelled.load(std::memory_order_relaxed);
    const bool timed_out = !cancelled && finished >= deadline && evaluated.load() < maximum;
    const bool completed = !cancelled && !timed_out && evaluated.load() == maximum;
    const std::string state = cancelled ? "cancelled" : timed_out ? "timed_out" : "completed";
    const std::string coverage = sampled ? "sampled_candidates" : completed ? "exhaustive_requested_range" : "partial_sequential_range";
    Json response = {
        {"state", state},
        {"minecraft_version", kTargetVersion.name},
        {"search_strategy", request["budget"]["strategy"]},
        {"coverage", coverage},
        {"candidates_evaluated", evaluated.load()},
        {"matching_seeds_found", matched.load()},
        {"elapsed_seconds", std::chrono::duration<double>(finished - started).count()},
        {"results", results},
        {"result_limit", max_results},
        {"limitations", Json::array()}
    };
    if (sampled) response["limitations"].push_back("Candidates were sampled deterministically and do not cover the global seed space.");
    if (timed_out) response["limitations"].push_back("The time budget ended before the candidate budget was exhausted.");
    if (timed_out && workers > 1) {
        response["limitations"].push_back("A time limited parallel search can evaluate a slightly different candidate prefix across runs. Use one worker or complete the candidate budget for exact result reproducibility.");
    }
    if (matched.load() == 0) response["limitations"].push_back("No match in this bounded search does not prove that no matching Minecraft seed exists.");
    emit({{"event", "complete"}, {"summary", response}});
    return response;
}

Json Engine::inspect(const Json& raw_request) {
    const Json request = normalizeInspect(raw_request);
    const uint64_t seed = static_cast<uint64_t>(parseSeed(request["seed"]));
    Generator generator{};
    setupGenerator(&generator, kTargetVersion.cubiomes_id, 0);
    applySeed(&generator, DIM_OVERWORLD, seed);
    const Point center{request["area"]["center"]["x"], request["area"]["center"]["z"]};
    const int radius = request["area"]["radius"];
    const int step = request["area"]["sample_step"];
    const int y = request["area"]["y"];
    std::map<std::string, std::pair<int, Pos>> summary;
    int samples = 0;
    for (int dz = -radius; dz <= radius; dz += step) {
        for (int dx = -radius; dx <= radius; dx += step) {
            if (std::hypot(static_cast<double>(dx), static_cast<double>(dz)) > radius) continue;
            const int x = center.x + dx;
            const int z = center.z + dz;
            const int id = getBiomeAt(&generator, 1, x, y, z);
            const char* raw_name = biome2str(kTargetVersion.cubiomes_id, id);
            const std::string name = raw_name ? raw_name : "unknown";
            auto& entry = summary[name];
            if (entry.first == 0 || distance(x, z, center.x, center.z) <
                distance(entry.second.x, entry.second.z, center.x, center.z)) entry.second = {x, z};
            ++entry.first;
            ++samples;
        }
    }
    Json biomes = Json::array();
    for (const auto& [name, data] : summary) {
        biomes.push_back({{"biome", name}, {"sample_count", data.first},
                          {"nearest_sample", coordinate(data.second.x, data.second.z, y)},
                          {"nearest_distance", distance(data.second.x, data.second.z, center.x, center.z)}});
    }
    Json structures = Json::array();
    Json caveats = Json::array();
    std::set<std::string> terrain_limited_structures;
    for (const auto& name_json : request["structures"]) {
        const auto name = name_json.get<std::string>();
        const int type = structureId(name);
        const auto* spec = structureSpec(name);
        for (const auto& pos : structureAttempts(seed, type, center, radius)) {
            if (!isViableStructurePos(type, &generator, pos.x, pos.z, 0)) continue;
            if (spec->terrain_limited && !isViableStructureTerrain(type, &generator, pos.x, pos.z)) continue;
            structures.push_back({{"name", name}, {"coordinates", coordinate(pos.x, pos.z)},
                                  {"distance_from_center", distance(pos.x, pos.z, center.x, center.z)},
                                  {"placement_status", structureStatus(*spec)}});
            if (spec->terrain_limited) terrain_limited_structures.insert(name);
        }
    }
    for (const auto& name : terrain_limited_structures) {
        caveats.push_back("Exact terrain generation is not confirmed for " + name +
                          "; Cubiomes placement, biome viability, and the terrain heuristic passed.");
    }
    const int center_id = getBiomeAt(&generator, 1, center.x, y, center.z);
    return {
        {"seed", formatSeed(seed)}, {"minecraft_version", kTargetVersion.name}, {"edition", "Java"},
        {"area", request["area"]}, {"center_biome", biome2str(kTargetVersion.cubiomes_id, center_id)},
        {"biome_sampling", {{"sample_count", samples}, {"sample_step", step}, {"y", y},
                            {"semantics", "exact Cubiomes lookups on a deterministic horizontal grid"}}},
        {"biome_summary", biomes}, {"structures", structures}, {"caveats", caveats}
    };
}

Json Engine::compare(const Json& input) {
    if (!input.is_object()) throw EngineError("invalid_type", "/", "compare request must be an object");
    if (!input.contains("seeds") || !input["seeds"].is_array() || input["seeds"].empty() || input["seeds"].size() > 64) {
        throw EngineError("out_of_range", "/seeds", "provide between 1 and 64 seed strings");
    }
    Json criteria = input;
    criteria.erase("seeds");
    criteria["budget"] = {{"strategy", "sequential"}, {"max_candidates", 1},
                           {"max_seconds", 300}, {"workers", 1}, {"start_seed", "0"}};
    criteria["max_results"] = 1;
    criteria = normalizeSearch(criteria);
    Json comparisons = Json::array();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(300);
    for (size_t i = 0; i < input["seeds"].size(); ++i) {
        if (!input["seeds"][i].is_string()) {
            throw EngineError("invalid_type", "/seeds/" + std::to_string(i), "seed must be a decimal string");
        }
        const uint64_t seed = static_cast<uint64_t>(parseSeed(input["seeds"][i]));
        Json evaluated = evaluateSeed(criteria, seed, nullptr, deadline);
        if (evaluated.value("matched", false)) {
            Json result = std::move(evaluated["result"]);
            result["meets_all_hard_constraints"] = true;
            comparisons.push_back(std::move(result));
        } else {
            comparisons.push_back({{"seed", formatSeed(seed)}, {"minecraft_version", kTargetVersion.name},
                                   {"meets_all_hard_constraints", false}, {"soft_preference_score", 0},
                                   {"validation_status", "rejected_by_supported_checks"}});
        }
    }
    std::sort(comparisons.begin(), comparisons.end(), [](const Json& left, const Json& right) {
        const bool lm = left["meets_all_hard_constraints"];
        const bool rm = right["meets_all_hard_constraints"];
        if (lm != rm) return lm > rm;
        return betterResult(left, right);
    });
    for (size_t i = 0; i < comparisons.size(); ++i) comparisons[i]["rank"] = i + 1;
    return {{"minecraft_version", kTargetVersion.name}, {"comparison_count", comparisons.size()},
            {"results", comparisons}};
}

}
