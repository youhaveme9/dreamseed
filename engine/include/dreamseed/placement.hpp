#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace dreamseed {

struct PlacementRegion {
    uint64_t addition;
    int32_t region_x, region_z, region_size, chunk_range, mode, reserved;
};

struct PlacementRule {
    int32_t begin, end, anchor_x, anchor_z, radius, count;
};

std::string metalDevice();
std::vector<uint8_t> metalPlacementFilter(const std::vector<uint64_t>& seeds,
    const std::vector<PlacementRegion>& regions, const std::vector<PlacementRule>& rules);

}
