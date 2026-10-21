#include "dreamseed/engine.hpp"

#include <csignal>
#include <fstream>
#include <iostream>
#include <string>

namespace {

dreamseed::SearchControl* active_control = nullptr;

void stopSearch(int) {
    if (active_control) active_control->cancelled.store(true);
}

dreamseed::Json readJson(const std::string& path) {
    if (path == "-") return dreamseed::Json::parse(std::cin);
    std::ifstream input(path);
    if (!input) throw dreamseed::EngineError("file_error", "/config", "could not open configuration file");
    return dreamseed::Json::parse(input);
}

void usage() {
    std::cerr << "Usage: dreamseed capabilities\n"
              << "       dreamseed validate --config FILE\n"
              << "       dreamseed search --config FILE [--events]\n"
              << "       dreamseed inspect --config FILE\n"
              << "       dreamseed compare --config FILE\n"
              << "       dreamseed filter --config FILE\n";
}

}

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            usage();
            return 2;
        }
        const std::string command = argv[1];
        if (command == "capabilities") {
            std::cout << dreamseed::Engine::capabilities().dump(2) << '\n';
            return 0;
        }
        std::string config;
        bool events = false;
        for (int i = 2; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--config" && i + 1 < argc) config = argv[++i];
            else if (arg == "--events") events = true;
            else throw dreamseed::EngineError("invalid_argument", "/arguments", "unknown or incomplete command argument");
        }
        if (config.empty()) throw dreamseed::EngineError("missing_argument", "/arguments/config", "--config is required");
        const auto request = readJson(config);
        dreamseed::Json result;
        if (command == "validate") {
            result = {{"valid", true}, {"normalized_request", dreamseed::Engine::validateSearch(request)}};
        } else if (command == "inspect") {
            result = dreamseed::Engine::inspect(request);
        } else if (command == "compare") {
            result = dreamseed::Engine::compare(request);
        } else if (command == "search" || command == "filter") {
            dreamseed::SearchControl control;
            active_control = &control;
            std::signal(SIGINT, stopSearch);
            std::signal(SIGTERM, stopSearch);
            if (events) {
                control.event_callback = [](const dreamseed::Json& event) {
                    std::cout << event.dump() << '\n' << std::flush;
                };
            }
            result = command == "filter" ? dreamseed::Engine::filterPlacements(request, &control) : dreamseed::Engine::search(request, &control);
            active_control = nullptr;
            if (events && command == "search") return result["state"] == "cancelled" ? 130 : 0;
        } else {
            usage();
            return 2;
        }
        std::cout << result.dump(2) << '\n';
        return 0;
    } catch (const dreamseed::EngineError& error) {
        std::cout << error.json().dump() << '\n';
        return 2;
    } catch (const nlohmann::json::exception& error) {
        dreamseed::Json response = {{"error", {{"code", "invalid_json"}, {"path", "/"}, {"message", error.what()}}}};
        std::cout << response.dump() << '\n';
        return 2;
    } catch (const std::exception& error) {
        dreamseed::Json response = {{"error", {{"code", "internal_error"}, {"path", "/"}, {"message", error.what()}}}};
        std::cout << response.dump() << '\n';
        return 1;
    }
}
