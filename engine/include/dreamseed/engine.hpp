#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <stdexcept>
#include <string>

#include <nlohmann/json.hpp>

namespace dreamseed {

using Json = nlohmann::json;

class EngineError : public std::runtime_error {
public:
    EngineError(std::string code, std::string path, std::string message);
    Json json() const;

private:
    std::string code_;
    std::string path_;
};

struct SearchControl {
    std::atomic_bool cancelled{false};
    std::function<void(const Json&)> event_callback;
};

class Engine {
public:
    static Json capabilities();
    static Json validateSearch(const Json& request);
    static Json search(const Json& request, SearchControl* control = nullptr);
    static Json inspect(const Json& request);
    static Json compare(const Json& request);
    static int64_t parseSeed(const std::string& value);
    static std::string formatSeed(uint64_t value);
};

}
