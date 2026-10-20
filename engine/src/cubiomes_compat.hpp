#pragma once

#include <math.h>

// Keep the Cubiomes C helper distinct from the C++20 math function.
extern "C" {
#define lerp dreamseed_cubiomes_lerp
#include "finders.h"
#include "generator.h"
#include "util.h"
#undef lerp
}
