// Placement arithmetic follows Cubiomes. See third_party/cubiomes/LICENSE.
#include <metal_stdlib>
using namespace metal;

struct Region {
    ulong addition;
    int rx, rz, size, range, mode, reserved;
};
struct Rule { int begin, end, ax, az, radius, count; };

ulong advance(ulong state) { return (state * 0x5deece66dul + 11ul) & 0xfffffffffffful; }

kernel void placement_filter(device const ulong* seeds [[buffer(0)]],
    device const Region* regions [[buffer(1)]], device const Rule* rules [[buffer(2)]],
    device uchar* output [[buffer(3)]], constant uint& count [[buffer(4)]],
    constant uint& rule_count [[buffer(5)]], uint index [[thread_position_in_grid]]) {
    if (index >= count) return;
    ulong seed = seeds[index] & 0xfffffffffffful;
    for (uint r = 0; r < rule_count; ++r) {
        Rule rule = rules[r];
        int found = 0;
        for (int i = rule.begin; i < rule.end; ++i) {
            Region region = regions[i];
            ulong state = (seed + region.addition) ^ 0x5deece66dul;
            state = advance(state);
            int x = region.mode == 1 || (region.range & (region.range - 1)) ?
                int(state >> 17) % region.range : int((ulong(region.range) * (state >> 17)) >> 31);
            state = advance(state);
            int z;
            if (region.mode == 1) {
                x = (x + int(state >> 17) % region.range) >> 1;
                state = advance(state);
                z = int(state >> 17) % region.range;
                state = advance(state);
                z = (z + int(state >> 17) % region.range) >> 1;
            } else {
                z = region.range & (region.range - 1) ? int(state >> 17) % region.range :
                    int((ulong(region.range) * (state >> 17)) >> 31);
            }
            int cx = region.rx * region.size + x, cz = region.rz * region.size + z;
            if (region.mode == 2) {
                state = ((seed ^ ulong(cx >> 4) ^ (ulong(cz >> 4) << 4)) ^ 0x5deece66dul) & 0xfffffffffffful;
                state = advance(state);
                int bits, value;
                do {
                    state = advance(state);
                    bits = int(state >> 17); value = bits % 5;
                } while (uint(bits - value) + 4u >= 0x80000000u);
                if (value != 0) continue;
            }
            int dx = cx * 16 - rule.ax, dz = cz * 16 - rule.az;
            if (dx * dx + dz * dz <= rule.radius * rule.radius) ++found;
            if (found >= rule.count) break;
        }
        if (found < rule.count) { output[index] = 0; return; }
    }
    output[index] = 1;
}
