#include "dreamseed/placement.hpp"

#include <stdexcept>

namespace dreamseed {

std::string metalDevice() { return {}; }

std::vector<uint8_t> metalPlacementFilter(const std::vector<uint64_t>&,
    const std::vector<PlacementRegion>&, const std::vector<PlacementRule>&) {
    throw std::runtime_error("Metal placement filtering is unavailable on this platform");
}

}
