from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .versions import MinecraftVersionName


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
    strategy: Literal["sequential", "sampled", "structure48"] = "sampled"
    max_candidates: int = Field(default=100_000, ge=1, le=10_000_000)
    max_seconds: float = Field(default=10, ge=0.05, le=300)
    workers: int = Field(default=4, ge=1, le=64)
    start_seed: str | None = None
    sample_seed: str | None = None
    upper_bits_per_structure_seed: int | None = Field(default=None, ge=1, le=65536)
    placement_cache: bool | None = Field(default=None, strict=True)

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
            raise ValueError("sample_seed requires a sampled strategy")
        if self.strategy != "sequential" and self.start_seed is not None:
            raise ValueError("start_seed is only valid with sequential strategy")
        if self.strategy != "structure48" and (
            self.upper_bits_per_structure_seed is not None or self.placement_cache is not None
        ):
            raise ValueError("batch settings require structure48 strategy")
        return self


class SearchCriteria(StrictModel):
    minecraft_version: MinecraftVersionName
    reference_point: Coordinate = Coordinate(x=0, z=0)
    hard_constraints: list[HardConstraint] = Field(min_length=1, max_length=16)
    soft_preferences: list[MinimizeDistance] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_references(self) -> SearchCriteria:
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
        for item in self.hard_constraints:
            if isinstance(item, (BiomeWithin, StructureWithin)):
                anchor = item.anchor or self.reference_point
                if abs(anchor.x) + item.radius > 30_000_000 or abs(anchor.z) + item.radius > 30_000_000:
                    raise ValueError("constraint area extends beyond the supported coordinate range")
        relation_ids: set[str] = set()
        for item in self.hard_constraints:
            if isinstance(item, MaximumDistance):
                relation_ids.update((item.from_, item.to))
        relation_grid_bound = 0
        for item in self.hard_constraints:
            if isinstance(item, BiomeWithin) and item.id in relation_ids:
                side = (2 * item.radius) // item.sample_step + 1
                relation_grid_bound += side * side + 1
        workers = getattr(getattr(self, "budget", None), "workers", 1)
        if relation_grid_bound * workers > 4_000_000:
            raise ValueError(
                "biome distance relations exceed the grid memory limit; reduce workers or radius, or increase sample_step"
            )
        return self


class SearchRequest(SearchCriteria):
    budget: SearchBudget = SearchBudget()
    max_results: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def validate_batched_strategy(self) -> SearchRequest:
        if self.budget.strategy == "structure48" and not any(
            isinstance(item, StructureWithin) for item in self.hard_constraints
        ):
            raise ValueError("structure48 requires a structure constraint")
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
    minecraft_version: MinecraftVersionName
    seed: str
    area: InspectArea = InspectArea()
    structures: list[StructureName] = Field(
        default_factory=lambda: ["village", "desert_pyramid"], max_length=10
    )
    include_biome_map: bool = False

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        parse_seed(value)
        return value

    @model_validator(mode="after")
    def validate_map_size(self) -> InspectRequest:
        if (
            abs(self.area.center.x) + self.area.radius > 30_000_000
            or abs(self.area.center.z) + self.area.radius > 30_000_000
        ):
            raise ValueError("inspection area extends beyond the supported coordinate range")
        width = self.area.radius * 2 // self.area.sample_step + 1
        if self.include_biome_map and width * width > 100_000:
            raise ValueError("biome map output would exceed 100000 points")
        return self


class CompareRequest(SearchCriteria):
    seeds: list[str] = Field(min_length=1, max_length=64)

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, values: list[str]) -> list[str]:
        for value in values:
            parse_seed(value)
        return values


class CandidateVerificationRequest(SearchCriteria):
    seed: str
    probe_surfaces: bool = Field(default=True, strict=True)
    max_seconds: int = Field(default=180, ge=30, le=300)

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        parse_seed(value)
        return value


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


class InspectionCapabilities(StrictModel):
    max_radius: int
    max_summary_sample_points: int
    max_biome_map_points: int
    biome_map_encoding: str


class JobStorageCapabilities(StrictModel):
    persistent: bool
    format: str
    retained_job_limit: int
    completed_job_recovery: bool
    active_job_restart_behavior: str


class StructureStartCapabilities(StrictModel):
    supported: bool
    enabled_by_default: bool
    requires_full_start_chunk: bool
    requires_serialized_pieces: bool
    max_decompressed_chunk_bytes: int
    all_structure_blocks_checked: bool


class StructureBlockCapabilities(StrictModel):
    supported_structures: list[str]
    scope: str
    max_blocks: int
    max_chunks: int
    block_entities_checked: Literal[False]
    all_structure_types_supported: Literal[False]


class CandidateVerificationCapabilities(StrictModel):
    supported: bool
    tool: Literal["verify_seed_candidate"]
    max_structure_targets: int
    max_biome_targets: int
    structure_counts: bool
    spatial_relations: bool
    exact_biome_checks: bool
    scope: Literal["selected_candidate_witnesses"]


class VersionVerificationAvailability(StrictModel):
    available: bool
    detail: str


class AuthoritativeVerificationCapabilities(StrictModel):
    available: bool
    source: str
    minecraft_version: str
    minecraft_versions: list[str]
    version_availability: dict[str, VersionVerificationAvailability]
    structure_targets: list[str]
    biome_targets: list[str]
    statuses: list[str]
    surface_probe: bool
    structure_start_inspection: StructureStartCapabilities
    structure_block_validation: StructureBlockCapabilities
    candidate_verification: CandidateVerificationCapabilities
    max_concurrent_per_server: int
    min_seconds: int
    max_seconds: int
    java_memory_mb: int
    setup_command: str
    detail: str


class TerrainCapabilities(StrictModel):
    supported: bool
    available: bool
    source: Literal["official_minecraft_java_server"]
    tool: Literal["analyze_seed_terrain"]
    max_samples: int
    max_chunks: int
    max_radius: int
    min_sample_step: int
    heightmap: str
    classifications: list[str]
    classification_semantics: str
    scoring_metrics: list[str]
    previews: list[str]


class PlacementPrefilterCapabilities(StrictModel):
    backends: dict[str, bool]
    metal_device: str
    cli_command: Literal["filter"]
    max_input_seeds: int
    validation_scope: Literal["structure_placement_only"]
    integrated_search_backend: Literal[False]


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
    terrain_analysis: TerrainCapabilities | None = None
    placement_prefilter: PlacementPrefilterCapabilities
    search_limits: SearchLimits
    inspection: InspectionCapabilities
    job_storage: JobStorageCapabilities
    authoritative_verification: AuthoritativeVerificationCapabilities
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


class PlacementFilterMetrics(StrictModel):
    placement_computations: int
    cache_reuses: int
    candidates_rejected_before_biomes: int
    full_seed_evaluations_started: int


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
    placement_filter: PlacementFilterMetrics | None = None
    persisted: bool | None = None
    recovered: bool | None = None
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
    placement_filter: PlacementFilterMetrics | None = None
    limitations: list[str] = Field(default_factory=list)
    persisted: bool | None = None
    recovered: bool | None = None
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


class BiomeMap(StrictModel):
    encoding: Literal["palette_indices"]
    origin: Coordinate
    width: int
    height: int
    sample_step: int
    y: int
    palette: list[str]
    rows: list[list[int]]
    semantics: str


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
    biome_map: BiomeMap | None = None
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


class RenderedSeedMap(StrictModel):
    seed: str
    minecraft_version: MinecraftVersionName
    format: Literal["svg"]
    width: int
    height: int
    palette: list[str]
    marker_count: int
    svg: str
    semantics: str
    caveats: list[str]


VerificationStructureName = StructureName


class VerificationReference(StrictModel):
    x: int = Field(default=0, ge=-30_000_000, le=30_000_000)
    y: int = Field(default=64, ge=-64, le=320)
    z: int = Field(default=0, ge=-30_000_000, le=30_000_000)


class MinecraftVerificationRequest(StrictModel):
    minecraft_version: MinecraftVersionName
    seed: str
    reference_point: VerificationReference = VerificationReference()
    structures: list[VerificationStructureName] = Field(default_factory=list, max_length=10)
    biomes: list[BiomeName] = Field(default_factory=list, max_length=8)
    probe_surfaces: bool = True
    confirm_structure_starts: bool = Field(default=True, strict=True)
    confirm_template_blocks: bool = Field(default=False, strict=True)
    include_biome_map: bool = False
    map_area: InspectArea | None = None
    max_seconds: int = Field(default=180, ge=30, le=300)

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        parse_seed(value)
        return value

    @model_validator(mode="after")
    def validate_targets(self) -> MinecraftVerificationRequest:
        if self.confirm_template_blocks and (self.structures != ["igloo"] or not self.confirm_structure_starts):
            raise ValueError("template block validation currently requires only igloo and confirm_structure_starts")
        if not self.structures and not self.biomes:
            raise ValueError("at least one structure or biome target is required")
        if len(self.structures) != len(set(self.structures)):
            raise ValueError("structure targets must be unique")
        if len(self.biomes) != len(set(self.biomes)):
            raise ValueError("biome targets must be unique")
        if self.map_area is not None and not self.include_biome_map:
            raise ValueError("map_area requires include_biome_map")
        if self.map_area is not None:
            if (
                abs(self.map_area.center.x) + self.map_area.radius > 30_000_000
                or abs(self.map_area.center.z) + self.map_area.radius > 30_000_000
            ):
                raise ValueError("verification map area extends beyond the supported coordinate range")
            width = self.map_area.radius * 2 // self.map_area.sample_step + 1
            if width * width > 4_225:
                raise ValueError("verification map output would exceed 4225 cells")
        return self


class SurfaceProbe(StrictModel):
    status: Literal["surface_probed", "surface_probe_failed"]
    coordinates: FeatureCoordinate | None = None
    is_water: bool | None = None
    is_lava: bool | None = None
    safe_teleport: bool
    detail: str


class StructureBoundingBox(StrictModel):
    min_x: int
    min_y: int
    min_z: int
    max_x: int
    max_y: int
    max_z: int


class StructureStartEvidence(StrictModel):
    status: Literal["confirmed", "unconfirmed"]
    chunk: Coordinate = Field(description="Start chunk X and Z coordinates, not block positions")
    piece_count: int = Field(ge=0)
    structure_id: str | None = None
    data_version: int | None = None
    chunk_status: str | None = None
    chunk_sha256: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    piece_ids: list[str] | None = None
    bounding_box: StructureBoundingBox | None = None
    code: str | None = None
    detail: str


class MinecraftLocatedFeature(StrictModel):
    kind: Literal["structure", "biome"]
    name: str
    located_id: str
    coordinates: FeatureCoordinate
    horizontal_distance: float
    reported_distance: float | None = None
    verification_status: Literal["minecraft_located", "generated_chunks_confirmed", "template_blocks_confirmed"]
    surface: SurfaceProbe | None = None
    structure_start: StructureStartEvidence | None = None
    block_verification: TemplateBlockEvidence | None = None


class VerificationFailure(StrictModel):
    kind: Literal["structure", "biome"]
    name: str
    code: str
    message: str
    stage: Literal["locate", "structure_start", "biome_check", "template_blocks"] = "locate"
    target_id: str | None = None


class MinecraftVerification(StrictModel):
    seed: str
    minecraft_version: MinecraftVersionName
    edition: Literal["Java"]
    source: Literal["official_minecraft_java_server"]
    status: Literal["minecraft_located", "generated_chunks_confirmed", "template_blocks_confirmed", "partially_verified", "partially_located", "not_located"]
    reference_point: VerificationReference
    locations: list[MinecraftLocatedFeature]
    failures: list[VerificationFailure]
    elapsed_seconds: float
    caveats: list[str]
    rendering: RenderedSeedMap | None = None


class MinecraftVerificationResponse(StrictModel):
    ok: bool
    verification: MinecraftVerification | None = None
    error: ErrorInfo | None = None


class TemplateBlockState(StrictModel):
    name: str
    properties: dict[str, str]


class TemplateBlockMismatch(StrictModel):
    coordinates: FeatureCoordinate
    expected: TemplateBlockState
    observed: TemplateBlockState


class TemplateBlockEvidence(StrictModel):
    status: Literal["confirmed", "mismatched", "unconfirmed"]
    scope: Literal["all_non_marker_igloo_template_blocks"]
    checked_blocks: int
    matched_blocks: int
    expected_blocks: int | None = None
    piece_count: int | None = None
    ignored_markers: int | None = None
    rotations: list[str] | None = None
    mismatch_count: int
    mismatches: list[TemplateBlockMismatch]
    block_entities_checked: Literal[False]
    expected_sha256: str | None = None
    observed_sha256: str | None = None
    code: str | None = None
    detail: str


class CandidateFeatureEvidence(StrictModel):
    target_id: str
    constraint_ids: list[str]
    kind: Literal["structure", "biome"]
    name: str
    coordinates: FeatureCoordinate
    requested_coordinates: FeatureCoordinate
    distance_from_reference: float = Field(ge=0)
    verification_status: Literal["generated_chunks_confirmed", "minecraft_biome_checked", "biome_mismatch", "unconfirmed"]
    biome_matches: bool | None = None
    structure_start: StructureStartEvidence | None = None
    surface: SurfaceProbe | None = None


class CandidateConstraintCheck(StrictModel):
    constraint_id: str
    type: Literal["biome_at", "biome_within", "structure_within", "max_distance"]
    status: Literal["verified", "not_verified"]
    feature_ids: list[str]
    required_count: int | None = None
    verified_count: int | None = None
    measured_distance: float | None = None
    maximum_distance: float | None = None
    detail: str


class CandidateVerification(StrictModel):
    seed: str
    minecraft_version: MinecraftVersionName
    edition: Literal["Java"]
    source: Literal["official_minecraft_java_server", "cubiomes_prediction_only"]
    status: Literal["verified", "not_verified", "prediction_rejected"]
    prediction_matched: bool
    all_hard_constraints_verified: bool
    reference_point: Coordinate
    validation_scope: Literal["selected_candidate_witnesses"]
    features: list[CandidateFeatureEvidence]
    constraint_checks: list[CandidateConstraintCheck]
    spatial_checks: list[SpatialCheck]
    score_breakdown: list[ScoreItem]
    soft_preference_score: float | None
    failures: list[VerificationFailure]
    elapsed_seconds: float
    caveats: list[str]


class CandidateVerificationResponse(StrictModel):
    ok: bool
    verification: CandidateVerification | None = None
    error: ErrorInfo | None = None


class TerrainArea(StrictModel):
    center: Coordinate = Coordinate(x=0, z=0)
    radius: int = Field(default=64, ge=0, le=256, description="Half span of the square sampled area, not a circular feature distance constraint")
    sample_step: int = Field(default=16, ge=4, le=64)

    @model_validator(mode="after")
    def validate_grid(self) -> TerrainArea:
        from .terrain_data import MAX_TERRAIN_CHUNKS, MAX_TERRAIN_POINTS, terrain_grid

        if self.sample_step % 4:
            raise ValueError("sample_step must be a multiple of 4")
        if abs(self.center.x) + self.radius > 30_000_000 or abs(self.center.z) + self.radius > 30_000_000:
            raise ValueError("terrain area extends beyond the supported coordinate range")
        _, width, grouped = terrain_grid(self.model_dump())
        if width * width > MAX_TERRAIN_POINTS or len(grouped) > MAX_TERRAIN_CHUNKS:
            raise ValueError("terrain area exceeds 4225 samples or 256 sampled chunks")
        return self


class TerrainPreference(StrictModel):
    metric: Literal["relief_blocks", "mean_slope", "water_fraction", "valley_fraction", "high_ground_fraction"]
    target: float = Field(ge=0, le=384)
    tolerance: float = Field(gt=0, le=384)
    weight: float = Field(default=1, gt=0, le=100)

    @model_validator(mode="after")
    def validate_target(self) -> TerrainPreference:
        if self.metric.endswith("_fraction") and self.target > 1:
            raise ValueError("fraction targets must be between 0 and 1")
        return self


class TerrainAnalysisRequest(StrictModel):
    minecraft_version: MinecraftVersionName
    seed: str
    area: TerrainArea = TerrainArea()
    preferences: list[TerrainPreference] = Field(default_factory=list, max_length=8)
    include_preview: bool = Field(default=True, strict=True)
    include_mesh: bool = Field(default=False, strict=True)
    max_seconds: int = Field(default=180, ge=30, le=300)

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        parse_seed(value)
        return value

    @model_validator(mode="after")
    def validate_mesh(self) -> TerrainAnalysisRequest:
        if self.include_mesh and not self.include_preview:
            raise ValueError("include_mesh requires include_preview")
        return self


class TerrainSample(StrictModel):
    surface_y: int
    floor_y: int
    surface_block: str
    surface_properties: dict[str, str]
    biome: str
    is_water: bool
    is_lava: bool
    water_depth: int


class TerrainChunkObservation(StrictModel):
    x: int
    z: int
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class TerrainChunkFailure(StrictModel):
    chunk: Coordinate
    code: str
    message: str


class TerrainGrid(StrictModel):
    encoding: Literal["surface_sample_rows"]
    origin: Coordinate
    width: int
    height: int
    sample_step: int
    heightmap: Literal["MOTION_BLOCKING_NO_LEAVES"]
    height_semantics: str
    rows: list[list[TerrainSample | None]]
    sample_count: int
    observed_sample_count: int
    requested_chunk_count: int
    observed_chunks: list[TerrainChunkObservation]
    failures: list[TerrainChunkFailure]
    status: Literal["generated_terrain_confirmed", "partial_terrain", "terrain_unconfirmed"]


class TerrainCentroid(StrictModel):
    x: float
    z: float


class TerrainFeature(StrictModel):
    kind: Literal["valley_cross_section_candidate", "high_ground_component", "mountain_range_candidate", "enclosed_water_candidate", "elongated_water_candidate"]
    classification: Literal["sampled_terrain_heuristic"]
    centroid: TerrainCentroid
    bounds: dict[str, int]
    sample_count: int
    touches_boundary: bool
    metrics: dict[str, float]


class TerrainScoreItem(TerrainPreference):
    measured_value: float
    normalized_value: float


class TerrainAnalysis(StrictModel):
    metrics: dict[str, float]
    features: list[TerrainFeature]
    feature_count: int
    score: float | None
    score_breakdown: list[TerrainScoreItem]


class TerrainMesh(StrictModel):
    format: Literal["obj"]
    obj: str
    origin: Coordinate
    vertex_count: int
    triangle_count: int
    vertical_exaggeration: Literal[1]


class TerrainPreview(StrictModel):
    format: Literal["svg"]
    svg: str
    width: float
    height: float
    mesh: TerrainMesh | None = None
    semantics: str


class TerrainInspection(StrictModel):
    seed: str
    minecraft_version: MinecraftVersionName
    edition: Literal["Java"]
    source: Literal["official_minecraft_java_server"]
    grid: TerrainGrid
    analysis: TerrainAnalysis
    control_probes: list[SurfaceProbe]
    control_heights_match: bool | None
    preview: TerrainPreview | None = None
    elapsed_seconds: float
    caveats: list[str]


class TerrainAnalysisResponse(StrictModel):
    ok: bool
    terrain: TerrainInspection | None = None
    error: ErrorInfo | None = None


class MapMarker(StrictModel):
    kind: Literal["structure", "biome", "reference"]
    name: str = Field(min_length=1, max_length=80)
    coordinates: FeatureCoordinate
    validation_status: Literal["client_supplied"] = "client_supplied"


class RenderSeedMapRequest(StrictModel):
    minecraft_version: MinecraftVersionName
    seed: str
    area: InspectArea = InspectArea(radius=512, sample_step=32, y=96)
    structures: list[StructureName] = Field(default_factory=list, max_length=10)
    markers: list[MapMarker] = Field(default_factory=list, max_length=64)
    title: str | None = Field(default=None, max_length=120)

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        parse_seed(value)
        return value

    @model_validator(mode="after")
    def validate_render_area(self) -> RenderSeedMapRequest:
        if (
            abs(self.area.center.x) + self.area.radius > 30_000_000
            or abs(self.area.center.z) + self.area.radius > 30_000_000
        ):
            raise ValueError("render area extends beyond the supported coordinate range")
        width = self.area.radius * 2 // self.area.sample_step + 1
        if width * width > 4_225:
            raise ValueError("render output would exceed 4225 cells")
        return self


class RenderSeedMapResponse(StrictModel):
    ok: bool
    rendering: RenderedSeedMap | None = None
    error: ErrorInfo | None = None
