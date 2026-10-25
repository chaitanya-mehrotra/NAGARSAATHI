import json

from app.domain.enums import IssueState, ReportState
from app.main import create_app
from app.schemas import ErrorResponse, Principal, ValidationResult
from app.settings import PROJECT_ROOT, Settings
from pydantic import TypeAdapter


def main() -> None:
    schema = create_app(
        Settings(app_mode="test", auth_provider="demo", validation_provider="fixture")
    ).openapi()
    # Include provider contracts even before submission/review endpoints exist.
    for model in (ErrorResponse, Principal, ValidationResult):
        definition = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = definition.pop("$defs", {})
        schema["components"]["schemas"].update(definitions)
        schema["components"]["schemas"][model.__name__] = definition
    for enum in (ReportState, IssueState):
        schema["components"]["schemas"][enum.__name__] = TypeAdapter(enum).json_schema()
    destination = PROJECT_ROOT / "packages/contracts/openapi.json"
    destination.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {destination}")


if __name__ == "__main__":
    main()
