"""Public benchmark options and their validation."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

WEIGHTS = {
    "text_accuracy": 20, "layout_preservation": 20, "tables_formatting": 15,
    "images_graphics": 10, "ocr_performance": 10, "docx_compatibility": 10,
    "performance": 5, "reliability": 4, "security": 4, "language_support": 2,
}
THRESHOLDS = {
    "text_accuracy": .99, "ocr_accuracy": .97, "page_completeness": 1.,
    "tables_score": .95, "images_score": .98, "layout_similarity": .95,
    "docx_valid": 1., "conversion_success": .99, "cleanup_rate": 1., "target_seconds": 30.,
}
TERMINAL = {"completed", "failed"}
QUEUE = "pdfpro.benchmark"
MAX_DATASET_CASES = 150
ASSET_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json",
               ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class BenchmarkOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field("Benchmark run", min_length=1, max_length=100)
    dataset_id: str = Field(min_length=36, max_length=36)
    case_ids: list[str] | None = Field(None, max_length=MAX_DATASET_CASES)
    category: str | None = Field(None, max_length=60)
    settings: dict = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    max_visual_pages: int = Field(8, ge=1, le=20)
    timeout_seconds: int = Field(120, ge=15, le=240)

    @model_validator(mode="after")
    def validate_options(self):
        if self.weights.keys() - WEIGHTS.keys():
            raise ValueError("Unknown scoring category.")
        weights = {**WEIGHTS, **self.weights}
        if any(not 0 <= value <= 100 for value in weights.values()) or abs(sum(weights.values()) - 100) > 1e-6:
            raise ValueError("Benchmark category weights must sum to 100.")
        if self.thresholds.keys() - THRESHOLDS.keys():
            raise ValueError("Unknown benchmark threshold.")
        for key, value in self.thresholds.items():
            valid = 0 < value <= 3600 if key == "target_seconds" else 0 <= value <= 1
            if not valid:
                raise ValueError(f"Invalid threshold for {key}.")
        self.weights = weights
        self.thresholds = {**THRESHOLDS, **self.thresholds}
        self.settings = conversion_options(self.settings)
        return self


def conversion_options(settings: dict) -> dict:
    from app.schemas import ToolSettings

    options = ToolSettings.model_validate(settings)
    supplied = options.model_dump(exclude_unset=True, exclude_none=True)
    prohibited = {"password", "rotation", "compression", "text", "dpi", "split_mode", "start_number"}
    if supplied.keys() & prohibited:
        raise ValueError("Use PDF-to-Word options. Benchmark settings cannot store a password.")
    supplied.pop("validate_render", None)
    return supplied
