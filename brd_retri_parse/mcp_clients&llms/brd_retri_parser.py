"""Pydantic schema and deterministic parser for BRD functional requirements."""

import re

from pydantic import BaseModel, ConfigDict, Field


class RequirementFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(pattern=r"^FR-\d+$")
    name: str = Field(min_length=1)
    priority: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)


class CoreModule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str = Field(pattern=r"^MOD-[A-Z0-9-]+$")
    name: str = Field(min_length=1)
    features: list[RequirementFeature] = Field(min_length=1)


class BRDRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    source_issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$")
    source_summary: str = ""
    modules: list[CoreModule] = Field(min_length=1)


_MODULE_RULES = (
    ("BENEFITS", "Benefit Payments", ("benefit", "disbursement", "payout")),
    ("ONBOARDING", "Employer & Scheme Onboarding", ("onboarding", "kyc", "enrollment")),
    ("INVESTMENTS", "Investment Management", ("investment", "fund switch", "fund performance")),
    ("MEMBER-EXPERIENCE", "Member Experience", ("self-service", "member portal")),
    ("CONTRIBUTIONS", "Contribution Management", ("contribution", "salary deduction", "billing")),
    ("MEMBER-EXPERIENCE", "Member Experience", ("member",)),
    ("COMPLIANCE", "Compliance & Audit", ("compliance", "audit", "regulatory")),
    ("SECURITY", "Security & Access", ("security", "access control", "authentication")),
    ("PLATFORM", "Core Platform", ()),
)


def _clean_cell(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "; ", value, flags=re.IGNORECASE)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", value)
    return value.replace("`", "").strip()


def _module_for(description: str, acceptance: str) -> tuple[str, str]:
    for text in (description, acceptance):
        normalized = text.casefold()
        for module_id, module_name, keywords in _MODULE_RULES[:-1]:
            if any(keyword in normalized for keyword in keywords):
                return module_id, module_name
    return _MODULE_RULES[-1][:2]


def parse_brd_requirements(
    markdown: str,
    source_issue_key: str,
    source_summary: str = "",
) -> BRDRequirements:
    """Parse functional-requirement rows from a Markdown table into Pydantic models."""
    rows: list[tuple[str, str, str, str]] = []
    header: list[str] | None = None
    for line in markdown.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [_clean_cell(cell) for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        lowered = [cell.casefold() for cell in cells]
        if any(cell in {"id", "requirement id"} for cell in lowered):
            header = lowered
            continue
        if header is None:
            continue

        indexes = {
            "id": next((index for index, cell in enumerate(header) if cell in {"id", "requirement id"}), None),
            "priority": next((index for index, cell in enumerate(header) if "priority" in cell), None),
            "description": next((index for index, cell in enumerate(header) if "description" in cell or "requirement" in cell), None),
            "acceptance": next((index for index, cell in enumerate(header) if "acceptance" in cell), None),
        }
        if any(index is None or index >= len(cells) for index in indexes.values()):
            continue
        requirement_id = re.search(r"FR-\d+", cells[indexes["id"]], flags=re.IGNORECASE)
        if requirement_id:
            rows.append((
                requirement_id.group(0).upper(),
                cells[indexes["priority"]],
                cells[indexes["description"]],
                cells[indexes["acceptance"]],
            ))

    if not rows:
        raise ValueError("No functional requirement rows were found in the BRD Markdown table.")

    feature_groups: dict[str, list[RequirementFeature]] = {}
    module_names: dict[str, str] = {}
    for requirement_id, priority, description, acceptance in rows:
        module_id, module_name = _module_for(description, acceptance)
        module_names[module_id] = module_name
        criteria = [part.strip() for part in re.split(r"\s*;\s*", acceptance) if part.strip()]
        feature_groups.setdefault(module_id, []).append(RequirementFeature(
            requirement_id=requirement_id,
            name=description,
            priority=priority or "Unspecified",
            acceptance_criteria=criteria,
        ))

    return BRDRequirements(
        source_issue_key=source_issue_key.strip().upper(),
        source_summary=source_summary.strip(),
        modules=[
            CoreModule(
                module_id=f"MOD-{module_id}",
                name=module_names[module_id],
                features=features,
            )
            for module_id, features in feature_groups.items()
        ],
    )