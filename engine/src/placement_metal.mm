#include "dreamseed/placement.hpp"
#include "metal_source.hpp"

#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include <cstring>
#include <algorithm>
#include <stdexcept>

namespace dreamseed {
namespace {

struct MetalState {
    id<MTLDevice> device;
    id<MTLComputePipelineState> pipeline;
    std::string error;

    MetalState() {
        @autoreleasepool {
            device = MTLCreateSystemDefaultDevice();
            if (!device) { error = "No Metal compute device is available"; return; }
            NSError* failure = nil;
            auto library = [device newLibraryWithSource:[NSString stringWithUTF8String:kMetalSource] options:nil error:&failure];
            if (library) pipeline = [device newComputePipelineStateWithFunction:[library newFunctionWithName:@"placement_filter"] error:&failure];
            if (!pipeline) error = failure ? failure.localizedDescription.UTF8String : "Metal pipeline creation failed";
        }
    }
};

MetalState& state() { static MetalState instance; return instance; }

}

std::string metalDevice() {
    @autoreleasepool {
        const auto& gpu = state();
        return gpu.pipeline ? gpu.device.name.UTF8String : std::string();
    }
}

std::vector<uint8_t> metalPlacementFilter(const std::vector<uint64_t>& seeds,
    const std::vector<PlacementRegion>& regions, const std::vector<PlacementRule>& rules) {
    static_assert(sizeof(PlacementRegion) == 32 && sizeof(PlacementRule) == 24);
    if (seeds.empty()) return {};
    @autoreleasepool {
        auto& gpu = state();
        if (!gpu.pipeline) throw std::runtime_error(gpu.error);
        auto seed_buffer = [gpu.device newBufferWithBytes:seeds.data() length:seeds.size() * sizeof(uint64_t) options:MTLResourceStorageModeShared];
        auto region_buffer = [gpu.device newBufferWithBytes:regions.data() length:regions.size() * sizeof(PlacementRegion) options:MTLResourceStorageModeShared];
        auto rule_buffer = [gpu.device newBufferWithBytes:rules.data() length:rules.size() * sizeof(PlacementRule) options:MTLResourceStorageModeShared];
        auto result_buffer = [gpu.device newBufferWithLength:seeds.size() options:MTLResourceStorageModeShared];
        if (!seed_buffer || !region_buffer || !rule_buffer || !result_buffer) throw std::runtime_error("Metal buffer allocation failed");
        auto queue = [gpu.device newCommandQueue];
        auto command = [queue commandBuffer];
        auto encoder = [command computeCommandEncoder];
        if (!encoder) throw std::runtime_error("Metal command encoder creation failed");
        [encoder setComputePipelineState:gpu.pipeline];
        [encoder setBuffer:seed_buffer offset:0 atIndex:0];
        [encoder setBuffer:region_buffer offset:0 atIndex:1];
        [encoder setBuffer:rule_buffer offset:0 atIndex:2];
        [encoder setBuffer:result_buffer offset:0 atIndex:3];
        const uint32_t count = static_cast<uint32_t>(seeds.size()), rule_count = static_cast<uint32_t>(rules.size());
        [encoder setBytes:&count length:sizeof(count) atIndex:4];
        [encoder setBytes:&rule_count length:sizeof(rule_count) atIndex:5];
        const NSUInteger group_size = std::min<NSUInteger>(256, gpu.pipeline.maxTotalThreadsPerThreadgroup);
        [encoder dispatchThreads:MTLSizeMake(count, 1, 1) threadsPerThreadgroup:MTLSizeMake(group_size, 1, 1)];
        [encoder endEncoding];
        [command commit];
        [command waitUntilCompleted];
        if (command.status != MTLCommandBufferStatusCompleted) throw std::runtime_error("Metal placement command failed");
        std::vector<uint8_t> results(seeds.size());
        std::memcpy(results.data(), result_buffer.contents, results.size());
        return results;
    }
}

}
