from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Coordinate(StrictModel):
    x: int = Field(ge=-30_000_000, le=30_000_000)
    z: int = Field(ge=-30_000_000, le=30_000_000)


BiomeName = Literal[
    "ocean", "plains", "desert", "windswept_hills", "forest", "taiga",
    "swamp", "river", "snowy_plains", "mushroom_fields", "jungle",
    "savanna", "badlands", "meadow", "grove", "snowy_slopes",
    "jagged_peaks", "frozen_peaks", "stony_peaks", "mangrove_swamp",
    "cherry_grove",
]
StructureName = Literal[
    "village", "desert_pyramid", "jungle_temple", "swamp_hut", "igloo",
    "ocean_ruin", "shipwreck", "ocean_monument", "woodland_mansion",
    "pillager_outpost",
]


class BiomeAt(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["biome_at"]
    biome: BiomeName
    coordinate: Coordinate | None = None
    y: int = Field(default=64, ge=-64, le=320)


class BiomeWithin(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["biome_within"]
    biome: BiomeName
    radius: int = Field(ge=0, le=1024)
    anchor: Coordinate | None = None
    y: int = Field(default=64, ge=-64, le=320)
    sample_step: int = Field(default=16, ge=4, le=64)

    @field_validator("sample_step")
    @classmethod
    def validate_step(cls, value: int) -> int:
        if value % 4:
            raise ValueError("sample_step must be a multiple of 4")
        return value


class StructureWithin(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["structure_within"]
    structure: StructureName
    radius: int = Field(ge=0, le=10_000)
    count: int = Field(default=1, ge=1, le=16)
    anchor: Coordinate | None = None


class MaximumDistance(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    type: Literal["max_distance"]
    from_: str = Field(alias="from", min_length=1, max_length=80)
    to: str = Field(min_length=1, max_length=80)
    max_distance: float = Field(ge=0, le=20_000)


HardConstraint = Annotated[
    BiomeAt | BiomeWithin | StructureWithin | MaximumDistance,
    Field(discriminator="type"),
]


class MinimizeDistance(StrictModel):
    type: Literal["minimize_distance"]
    constraint_id: str = Field(min_length=1, max_length=80)
    weight: float = Field(default=1, gt=0, le=100)


class SearchBudget(StrictModel):
    strategy: Literal["sequential", "sampled"] = "sampled"
    max_candidates: int = Field(default=100_000, ge=1, le=10_000_000)
    max_seconds: float = Field(default=10, ge=0.05, le=300)
    workers: int = Field(default=4, ge=1, le=64)
    start_seed: str | None = None
    sample_seed: str | None = None

    @field_validator("start_seed", "sample_seed")
    @classmethod
    def validate_seed(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parse_seed(value)
        return value

    @model_validator(mode="after")
    def validate_strategy_seed(self) -> SearchBudget:
        if self.strategy == "sequential" and self.sample_seed is not None:
            raise ValueError("sample_seed is only valid with sampled strategy")
        if self.strategy == "sampled" and self.start_seed is not None:
            raise ValueError("start_seed is only valid with sequential strategy")
        return self


class SearchRequest(StrictModel):
    minecraft_version: Literal["1.21.1"]
    reference_point: Coordinate = Coordinate(x=0, z=0)
    hard_constraints: list[HardConstraint] = Field(min_length=1, max_length=16)
    soft_preferences: list[MinimizeDistance] = Field(default_factory=list, max_length=16)
    budget: SearchBudget = SearchBudget()
    max_results: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def validate_references(self) -> SearchRequest:
        ids = [item.id for item in self.hard_constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("hard constraint ids must be unique")
        feature_ids = {
            item.id for item in self.hard_constraints
            if isinstance(item, (BiomeAt, BiomeWithin, StructureWithin))
        }
        for item in self.hard_constraints:
            if isinstance(item, MaximumDistance):
                if item.from_ not in feature_ids or item.to not in feature_ids:
                    raise ValueError("distance references must name feature constraints")
                if item.from_ == item.to:
                    raise ValueError("distance references must be different")
        for preference in self.soft_preferences:
            if preference.constraint_id not in feature_ids:
                raise ValueError("preference must reference a feature constraint")
        relation_ids: set[str] = set()
        for item in self.hard_constraints:
            if isinstance(item, MaximumDistance):
                relation_ids.update((item.from_, item.to))
        relation_grid_bound = 0
        for item in self.hard_constraints:
            if isinstance(item, BiomeWithin) and item.id in relation_ids:
                side = (2 * item.radius) // item.sample_step + 1
                relation_grid_bound += side * side + 1
        if relation_grid_bound * self.budget.workers > 4_000_000:
            raise ValueError(
                "biome distance relations exceed the grid memory limit; reduce workers or radius, or increase sample_step"
            )
        return self


class InspectArea(StrictModel):
    center: Coordinate = Coordinate(x=0, z=0)
    radius: int = Field(default=512, ge=0, le=2048)
    sample_step: int = Field(default=16, ge=4, le=128)
    y: int = Field(default=64, ge=-64, le=320)

    @field_validator("sample_step")
    @classmethod
    def validate_step(cls, value: int) -> int:
        if value % 4:
            raise ValueError("sample_step must be a multiple of 4")
        return value

    @model_validator(mode="after")
    def validate_size(self) -> InspectArea:
        width = self.radius * 2 // self.sample_step + 1
        if width * width > 200_000:
            raise ValueError("area sampling would exceed 200000 points")
        return self


class InspectRequest(StrictModel):
    minecraft_version: Literal["1.21.1"]
    seed: str
    area: InspectArea = InspectArea()
    structures: list[StructureName] = Field(
        default_factory=lambda: ["village", "desert_pyramid"], max_length=10
    )

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        parse_seed(value)
        return value


class CompareRequest(StrictModel):
    minecraft_version: Literal["1.21.1"]
    seeds: list[str] = Field(min_length=1, max_length=64)
    reference_point: Coordinate = Coordinate(x=0, z=0)
    hard_constraints: list[HardConstraint] = Field(min_length=1, max_length=16)
    soft_preferences: list[MinimizeDistance] = Field(default_factory=list, max_length=16)

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, values: list[str]) -> list[str]:
        for value in values:
            parse_seed(value)
        return values


def parse_seed(value: str) -> int:
    if not isinstance(value, str) or not value or value.startswith("+"):
        raise ValueError("seed must be a signed 64 bit decimal string")
    if value.startswith("-"):
        digits = value[1:]
    else:
        digits = value
    if not digits.isascii() or not digits.isdigit():
        raise ValueError("seed must be a signed 64 bit decimal string")
    parsed = int(value)
    if parsed < -(1 << 63) or parsed > (1 << 63) - 1:
        raise ValueError("seed is outside signed 64 bit range")
    return parsed


class ErrorInfo(StrictModel):
    code: str
    message: str
    path: str | None = None
    details: Any = None


class ErrorResponse(StrictModel):
    ok: Literal[False] = False
    error: ErrorInfo


class BiomeCapabilities(StrictModel):
    types: list[str]
    biomes: list[str]
    within_semantics: str


class StructureCapabilities(StrictModel):
    types: list[str]
    operations: list[str]


class SearchLimits(StrictModel):
    max_candidates: int
    max_seconds: int
    max_workers: int
    max_results: int
    max_biome_radius: int
    max_structure_radius: int
    max_coordinate_absolute: int
    max_relation_grid_points_across_workers: int


class ValidationCapabilities(StrictModel):
    village: str
    desert_pyramid: str
    jungle_temple: str
    swamp_hut: str
    igloo: str
    ocean_ruin: str
    shipwreck: str
    ocean_monument: str
    woodland_mansion: str
    pillager_outpost: str
    biome_at: str
    biome_within: str


class Capabilities(StrictModel):
    engine: str
    engine_version: str
    editions: list[str]
    minecraft_versions: list[str]
    seed_encoding: str
    structure_seed_semantics: str
    biome_filters: BiomeCapabilities
    structure_filters: StructureCapabilities
    spatial_operations: list[str]
    distance_metric: str
    search_strategies: list[str]
    search_limits: SearchLimits
    validation: ValidationCapabilities
    unsupported: list[str]
    experimental: list[str]
    cubiomes_commit: str


class CapabilitiesResponse(StrictModel):
    ok: bool
    capabilities: Capabilities | None = None
    error: ErrorInfo | None = None


class StartResponse(StrictModel):
    ok: bool
    job_id: str | None = None
    state: str | None = None
    search_strategy: str | None = None
    error: ErrorInfo | None = None


class StatusResponse(StrictModel):
    ok: bool
    job_id: str | None = None
    state: str | None = None
    candidates_evaluated: int | None = None
    matching_seeds_found: int | None = None
    elapsed_seconds: float | None = None
    search_strategy: str | None = None
    candidate_budget: int | None = None
    progress_note: str | None = None
    coverage: str | None = None
    error: ErrorInfo | None = None


class FeatureCoordinate(StrictModel):
    x: int
    z: int
    y: int | None = None


class FeatureResult(StrictModel):
    constraint_id: str
    kind: str
    name: str
    coordinates: FeatureCoordinate
    distance_from_anchor: float
    distance_metric: str
    placement_status: str


class ScoreItem(StrictModel):
    type: str
    constraint_id: str
    measured_distance: float
    weight: float
    normalized_value: float


class SpatialCheck(StrictModel):
    constraint_id: str
    operation: Literal["max_distance"]
    from_constraint: str
    to_constraint: str
    maximum_distance: float
    measured_distance: float
    from_coordinates: FeatureCoordinate
    to_coordinates: FeatureCoordinate
    distance_metric: str


class SeedResult(StrictModel):
    seed: str
    minecraft_version: str
    edition: str
    reference_point: Coordinate
    matching_feature_names: list[str]
    features: list[FeatureResult]
    satisfied_hard_constraints: list[str]
    spatial_checks: list[SpatialCheck]
    soft_preference_score: float
    score_breakdown: list[ScoreItem]
    validation_status: str
    caveats: list[str]


class ResultsResponse(StrictModel):
    ok: bool
    job_id: str | None = None
    state: str | None = None
    candidates_evaluated: int | None = None
    matching_seeds_found: int | None = None
    results: list[SeedResult] = Field(default_factory=list)
    results_available: int | None = None
    search_complete: bool | None = None
    coverage: str | None = None
    limitations: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None


class CancelResponse(StrictModel):
    ok: bool
    job_id: str | None = None
    state: str | None = None
    already_finished: bool | None = None
    error: ErrorInfo | None = None


class BiomeSummary(StrictModel):
    biome: str
    sample_count: int
    nearest_sample: FeatureCoordinate
    nearest_distance: float


class StructureInspection(StrictModel):
    name: str
    coordinates: FeatureCoordinate
    distance_from_center: float
    placement_status: str


class BiomeSampling(StrictModel):
    sample_count: int
    sample_step: int
    semantics: str
    y: int


class NormalizedInspectArea(StrictModel):
    center: Coordinate
    radius: int
    sample_step: int
    y: int


class Inspection(StrictModel):
    seed: str
    minecraft_version: str
    edition: str
    area: NormalizedInspectArea
    center_biome: str
    biome_sampling: BiomeSampling
    biome_summary: list[BiomeSummary]
    structures: list[StructureInspection]
    caveats: list[str]


class InspectionResponse(StrictModel):
    ok: bool
    inspection: Inspection | None = None
    error: ErrorInfo | None = None


class ComparisonEntry(StrictModel):
    seed: str
    minecraft_version: str
    meets_all_hard_constraints: bool
    soft_preference_score: float
    validation_status: str
    rank: int
    edition: str | None = None
    reference_point: Coordinate | None = None
    matching_feature_names: list[str] | None = None
    features: list[FeatureResult] | None = None
    satisfied_hard_constraints: list[str] | None = None
    spatial_checks: list[SpatialCheck] | None = None
    score_breakdown: list[ScoreItem] | None = None
    caveats: list[str] | None = None


class Comparison(StrictModel):
    minecraft_version: str
    comparison_count: int
    results: list[ComparisonEntry]


class ComparisonResponse(StrictModel):
    ok: bool
    comparison: Comparison | None = None
    error: ErrorInfo | None = None
