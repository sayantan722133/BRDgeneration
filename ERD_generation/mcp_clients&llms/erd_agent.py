"""Generate traceable database schema and ERD outputs from Jira context."""

import asyncio
import json
import os
import re
from collections.abc import Mapping
from typing import Any, Literal

from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator, model_validator

from ERD_generation.prompts import ERD_SYSTEM_PROMPT, build_erd_user_prompt

load_dotenv()

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "qwen3-4b-thinking-2507.Q4_K_M.gguf")

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMPONENT_ID = re.compile(r"^COMP-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d+$", re.IGNORECASE)
_MERMAID_RELATIONSHIP = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?:\|\||o\||\|\{|o\{|\}\||\}o)--"
    r"(?:\|\||o\||\|\{|o\{|\}\||\}o)"
    r"\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*.+"
)
_MERMAID_RELATIONSHIP_DETAIL = re.compile(
    r"(?P<source>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<source_card>\|\||o\||\|\{|o\{|\}\||\}o)--"
    r"(?P<target_card>\|\||o\||\|\{|o\{|\}\||\}o)\s+"
    r"(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<label>.+)"
)
_SECTION_NAMES = (
    "Database Architecture Summary & Scope",
    "Mermaid.js Entity Relationship Diagram",
    "Data Dictionary / Table Definitions",
    "Relationship & Cardinality Mapping",
    "Traceability Matrix",
)


class ErdAttribute(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(min_length=1, max_length=128)
    is_primary: bool = False
    is_foreign: bool = False

    @field_validator("name")
    @classmethod
    def validate_attribute_name(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Attribute names must be identifiers without spaces.")
        return value

    @field_validator("data_type")
    @classmethod
    def validate_data_type(cls, value: str) -> str:
        if "\n" in value or "|" in value or not value.strip():
            raise ValueError("data_type must be a non-empty single-line value.")
        normalized = value.strip().upper()
        aliases = {
            "STRING": "TEXT",
            "STR": "TEXT",
            "INT": "INTEGER",
            "BOOL": "BOOLEAN",
            "DECIMAL": "NUMERIC",
            "DATETIME": "TIMESTAMP",
            "UUID": "VARCHAR(36)",
        }
        normalized = aliases.get(normalized, normalized)
        if not re.fullmatch(
            r"(?:TEXT|VARCHAR(?:\(\d+\))?|CHAR(?:\(\d+\))?|"
            r"SMALLINT|INTEGER|BIGINT|NUMERIC(?:\(\d+(?:,\s*\d+)?\))?|"
            r"DECIMAL(?:\(\d+(?:,\s*\d+)?\))?|BOOLEAN|DATE|"
            r"TIMESTAMP(?:\s+WITH(?:OUT)?\s+TIME\s+ZONE)?)",
            normalized,
        ):
            raise ValueError(
                f"data_type '{value}' is not an allowed portable SQL data type."
            )
        return normalized


class ErdEntity(BaseModel):
    table_name: str = Field(min_length=1, max_length=128)
    attributes: list[ErdAttribute] = Field(min_length=1)

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Table names must be identifiers without spaces.")
        return value

    @model_validator(mode="after")
    def validate_attributes(self) -> "ErdEntity":
        names = [attribute.name.casefold() for attribute in self.attributes]
        if len(names) != len(set(names)):
            raise ValueError(f"Table {self.table_name} contains duplicate attributes.")
        if sum(attribute.is_primary for attribute in self.attributes) == 0:
            raise ValueError(f"Table {self.table_name} must define a primary key.")
        return self


class ErdGeneration(BaseModel):
    erd_markdown: str = Field(min_length=100)
    entities: list[ErdEntity] = Field(min_length=1)

    @field_validator("erd_markdown")
    @classmethod
    def validate_document_sections(cls, value: str) -> str:
        for section in _SECTION_NAMES:
            if not re.search(
                rf"^#+\s+{re.escape(section)}\s*$", value, flags=re.IGNORECASE | re.MULTILINE
            ):
                raise ValueError(f"erd_markdown is missing the '{section}' section.")
        if not re.search(r"```mermaid\s*\nerDiagram\b", value):
            raise ValueError("erd_markdown must contain an erDiagram Mermaid code block.")
        return value

    @model_validator(mode="after")
    def validate_markdown_matches_schema(self) -> "ErdGeneration":
        table_names = [entity.table_name.casefold() for entity in self.entities]
        if len(table_names) != len(set(table_names)):
            raise ValueError("entities contains duplicate table names.")

        dictionary = _parse_markdown_table(
            self.erd_markdown,
            "Data Dictionary / Table Definitions",
            ("table", "column", "data type", "constraints", "description"),
        )
        expected = {
            (entity.table_name, attribute.name): (
                attribute.data_type,
                attribute.is_primary,
                attribute.is_foreign,
            )
            for entity in self.entities
            for attribute in entity.attributes
        }
        actual: dict[tuple[str, str], tuple[str, bool, bool]] = {}
        for row in dictionary:
            table, column, data_type, constraints, description = row
            if not description.strip():
                raise ValueError(f"Data Dictionary row {table}.{column} needs a description.")
            key = (table, column)
            if key in actual:
                raise ValueError(f"Data Dictionary repeats {table}.{column}.")
            actual[key] = (
                data_type,
                bool(re.search(r"\bPK\b|primary key", constraints, re.IGNORECASE)),
                bool(re.search(r"\bFK\b|foreign key", constraints, re.IGNORECASE)),
            )
        if actual != expected:
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            mismatched = sorted(
                (key, expected[key], actual[key])
                for key in set(expected) & set(actual)
                if expected[key] != actual[key]
            )
            raise ValueError(
                "The Data Dictionary table/column/type/PK/FK inventory must exactly "
                f"match entities. Missing: {missing[:5]}; extra: {extra[:5]}; "
                f"mismatched: {mismatched[:5]}."
            )

        diagram = _parse_mermaid_entities(self.erd_markdown)
        expected_diagram = {
            entity.table_name: {
                attribute.name: (
                    attribute.data_type,
                    attribute.is_primary,
                    attribute.is_foreign,
                )
                for attribute in entity.attributes
            }
            for entity in self.entities
        }
        if diagram != expected_diagram:
            raise ValueError(
                "The Mermaid diagram table/column/PK/FK inventory must exactly match entities."
            )
        _validate_mermaid_relationships(self.erd_markdown, self.entities)

        traceability = _parse_markdown_table(
            self.erd_markdown,
            "Traceability Matrix",
            ("table name", "source component id", "source data entity"),
        )
        traced_tables = [row[0] for row in traceability]
        if len(traced_tables) != len(set(traced_tables)) or set(traced_tables) != set(
            entity.table_name for entity in self.entities
        ):
            raise ValueError("The Traceability Matrix must map every table exactly once.")
        for _, component_id, source_entity in traceability:
            if not _COMPONENT_ID.fullmatch(component_id):
                raise ValueError(f"Invalid source component ID in Traceability Matrix: {component_id}")
            if not source_entity.strip():
                raise ValueError("Every Traceability Matrix row needs a source data entity.")
        return self


def serialize_erd_context(jira_context: BaseModel | Mapping[str, Any]) -> str:
    """Serialize Pydantic or mapping-based Jira context for the generation prompt."""
    if isinstance(jira_context, BaseModel):
        payload = jira_context.model_dump(mode="json")
    elif isinstance(jira_context, Mapping):
        payload = dict(jira_context)
    else:
        raise TypeError("jira_context must be a Pydantic model or a mapping.")
    if not payload:
        raise ValueError("jira_context must contain Jira architecture or FRD data.")
    try:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise ValueError("jira_context must contain JSON-serializable data.") from error


def _normalize_section_headings(markdown: str) -> str:
    """Remove optional numbering from required ERD section headings."""
    for section in _SECTION_NAMES:
        markdown = re.sub(
            rf"^(#+\s+)(?:\d+[.)]?\s*)?({re.escape(section)})\s*$",
            rf"\1{section}",
            markdown,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    markdown = re.sub(
        r"^(#{1,6}\s+Database Architecture Summary & Scope\s*)\n"
        r"#{1,6}\s+Database Architecture Summary & Scope\s*$",
        r"\1",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return markdown


def _parse_markdown_table(
    markdown: str, section: str, expected_headers: tuple[str, ...]
) -> list[tuple[str, ...]]:
    match = re.search(
        rf"^#+\s+{re.escape(section)}\s*$([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        raise ValueError(f"Markdown section '{section}' was not found.")
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in match.group(1).splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]
    if len(rows) < 3 or tuple(cell.casefold() for cell in rows[0]) != expected_headers:
        raise ValueError(f"Markdown section '{section}' must contain the expected table headers.")
    if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        raise ValueError(f"Markdown section '{section}' has an invalid table separator.")
    parsed = []
    for row in rows[2:]:
        if len(row) != len(expected_headers):
            raise ValueError(f"Markdown section '{section}' contains a malformed table row.")
        parsed.append(tuple(row))
    return parsed


def _synchronize_schema_markdown(markdown: str, entities: list[ErdEntity]) -> str:
    """Render the data dictionary and Mermaid entity attributes from the schema."""
    dictionary_match = re.search(
        rf"^(#+\s+{re.escape('Data Dictionary / Table Definitions')}\s*$)"
        rf"([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not dictionary_match:
        raise ValueError("Markdown section 'Data Dictionary / Table Definitions' was not found.")

    descriptions: dict[tuple[str, str], str] = {}
    for line in dictionary_match.group(2).splitlines():
        if not (line.strip().startswith("|") and line.strip().endswith("|")):
            continue
        columns = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if len(columns) == 5 and columns[0].casefold() != "table":
            descriptions[(columns[0], columns[1])] = columns[4]

    dictionary_lines = [
        "",
        "| Table | Column | Data Type | Constraints | Description |",
        "|---|---|---|---|---|",
    ]
    for entity in entities:
        for attribute in entity.attributes:
            constraints = []
            if attribute.is_primary:
                constraints.append("PK")
            if attribute.is_foreign:
                constraints.append("FK")
            description = descriptions.get(
                (entity.table_name, attribute.name),
                f"{attribute.name.replace('_', ' ').capitalize()} for "
                f"{entity.table_name.replace('_', ' ')}.",
            )
            dictionary_lines.append(
                f"| {entity.table_name} | {attribute.name} | {attribute.data_type} | "
                f"{', '.join(constraints)} | {description} |"
            )
    dictionary_body = "\n".join(dictionary_lines) + "\n\n"
    markdown = (
        markdown[:dictionary_match.start(2)]
        + dictionary_body
        + markdown[dictionary_match.end(2):]
    )

    diagram_match = re.search(
        r"```mermaid\s*\n(.*?)```", markdown, flags=re.DOTALL | re.IGNORECASE
    )
    if not diagram_match:
        raise ValueError("Mermaid ERD code block was not found.")
    entity_names = {entity.table_name.casefold(): entity.table_name for entity in entities}
    relationship_labels: dict[tuple[str, str], str] = {}
    for line in diagram_match.group(1).splitlines():
        relationship = _MERMAID_RELATIONSHIP.fullmatch(line.strip())
        if not relationship:
            continue
        source, target = relationship.groups()
        if source.casefold() not in entity_names or target.casefold() not in entity_names:
            raise ValueError(f"Mermaid relationship references unknown entity: {source} -> {target}.")
        relationship_labels[(entity_names[source.casefold()], entity_names[target.casefold()])] = (
            line.strip().split(":", 1)[1].strip().strip('"')
        )

    primary_keys = {
        entity.table_name: {
            attribute.name
            for attribute in entity.attributes
            if attribute.is_primary
        }
        for entity in entities
    }
    related_tables: dict[str, set[str]] = {entity.table_name: set() for entity in entities}
    for source, target in relationship_labels:
        related_tables[source].add(target)
        related_tables[target].add(source)

    relationships = []
    for child in entities:
        for attribute in child.attributes:
            if not attribute.is_foreign:
                continue
            parents = [
                parent.table_name
                for parent in entities
                if parent.table_name != child.table_name
                and attribute.name in primary_keys[parent.table_name]
            ]
            if not parents:
                parents = sorted(related_tables[child.table_name])
            if len(parents) != 1:
                raise ValueError(
                    f"Foreign key {child.table_name}.{attribute.name} must identify exactly "
                    "one parent, either by matching a primary-key column or by an unambiguous "
                    "relationship in the Mermaid diagram."
                )
            parent_name = parents[0]
            label = (
                relationship_labels.get((parent_name, child.table_name))
                or relationship_labels.get((child.table_name, parent_name))
                or "references"
            )
            relationships.append(
                f'{parent_name} ||--o{{ {child.table_name} : "{label}"'
            )
    diagram_lines = ["erDiagram"]
    for entity in entities:
        diagram_lines.append(f"  {entity.table_name} {{")
        for attribute in entity.attributes:
            markers = []
            if attribute.is_primary:
                markers.append("PK")
            if attribute.is_foreign:
                markers.append("FK")
            marker_text = f" {', '.join(markers)}" if markers else ""
            comment = attribute.name.replace("_", " ")
            diagram_lines.append(
                f'    {attribute.data_type} {attribute.name}{marker_text} "{comment}"'
            )
        diagram_lines.append("  }")
    diagram_lines.extend(f"  {relationship}" for relationship in relationships)
    diagram = "```mermaid\n" + "\n".join(diagram_lines) + "\n```"
    markdown = markdown[:diagram_match.start()] + diagram + markdown[diagram_match.end():]
    return _synchronize_relationship_mapping(markdown, entities)


def _synchronize_relationship_mapping(
    markdown: str, entities: list[ErdEntity]
) -> str:
    """Make the prose relationship list match the FK-backed Mermaid edges."""
    section_match = re.search(
        rf"^(#+\s+{re.escape('Relationship & Cardinality Mapping')}\s*$)"
        rf"([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not section_match:
        raise ValueError("Markdown section 'Relationship & Cardinality Mapping' was not found.")

    relationship_rows = _parse_mermaid_relationships(markdown)
    if not relationship_rows:
        body = "\nNo FK-backed relationships are established by the current schema. "
        body += "Confirm any additional business relationships and cardinalities before implementation.\n\n"
        return markdown[:section_match.start(2)] + body + markdown[section_match.end(2):]

    old_bullets = [
        line.strip()
        for line in section_match.group(2).splitlines()
        if re.match(r"^\s*[-*]\s+", line)
    ]
    lines = []
    for source, source_card, target_card, target, _ in relationship_rows:
        if target_card in {"o{", "|{"}:
            parent, child = source, target
        else:
            parent, child = target, source
        rationale = ""
        for bullet in old_bullets:
            if (
                re.search(rf"\b{re.escape(source)}\b", bullet, flags=re.IGNORECASE)
                and re.search(rf"\b{re.escape(target)}\b", bullet, flags=re.IGNORECASE)
            ):
                rationale_match = re.search(r"\):\s*(.+)$", bullet)
                if rationale_match:
                    rationale = rationale_match.group(1).strip()
                    break
        if not rationale:
            rationale = (
                "Proposed: the child foreign key references the parent primary key; "
                "confirm optionality and any uniqueness rule."
            )
        else:
            rationale = re.sub(r"^\s*(?:Proposed:\s*)?", "", rationale, flags=re.IGNORECASE)
            rationale = (
                "The child foreign key references the parent primary key. "
                f"{rationale} Confirm optionality and any uniqueness rule."
            )
        lines.append(
            f"- {parent} to {child} (Proposed 1:N): {rationale} "
            "The source does not establish cardinality or optionality; confirm these rules."
        )

    unresolved_references = [
        f"{entity.table_name}.{attribute.name}"
        for entity in entities
        for attribute in entity.attributes
        if attribute.name.casefold().endswith("_id")
        and not attribute.is_primary
        and not attribute.is_foreign
    ]
    if unresolved_references:
        lines.append(
            "- Unresolved reference columns: "
            + ", ".join(f"`{reference}`" for reference in unresolved_references)
            + " are not declared foreign keys because their target entities are not established by the source. "
            "Confirm their target and key before implementation."
        )

    body = "\n" + "\n".join(lines) + "\n\n"
    return markdown[:section_match.start(2)] + body + markdown[section_match.end(2):]


def _synchronize_traceability_markdown(
    markdown: str, jira_context: Mapping[str, Any]
) -> str:
    """Canonicalize status suffixes in source entities to their exact Jira names."""
    rows = _parse_markdown_table(
        markdown,
        "Traceability Matrix",
        ("table name", "source component id", "source data entity"),
    )
    source_entities = _source_entities(jira_context)
    normalized_rows = []
    for table_name, component_id, source_entity in rows:
        component_key = component_id.strip().upper()
        available = source_entities.get(component_key)
        if available is None:
            normalized_rows.append((table_name, component_id, source_entity))
            continue
        if source_entity in available:
            normalized_rows.append((table_name, component_id, source_entity))
            continue
        base_entity = re.sub(
            r"\s+\((?:proposed|tbd)\)$", "", source_entity.strip(), flags=re.IGNORECASE
        ).casefold()
        matches = [
            entity for entity in available
            if re.sub(
                r"\s+\((?:proposed|tbd)\)$", "", entity, flags=re.IGNORECASE
            ).casefold() == base_entity
        ]
        if len(matches) == 1:
            normalized_rows.append((table_name, component_id, matches[0]))
        else:
            normalized_rows.append((table_name, component_id, source_entity))

    section_match = re.search(
        rf"^(#+\s+{re.escape('Traceability Matrix')}\s*$)"
        rf"([\s\S]*?)(?=^#+\s|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not section_match:
        raise ValueError("Markdown section 'Traceability Matrix' was not found.")
    body = [
        "",
        "| Table Name | Source Component ID | Source Data Entity |",
        "|---|---|---|",
        *[f"| {table} | {component} | {entity} |" for table, component, entity in normalized_rows],
        "",
        "",
    ]
    return markdown[:section_match.start(2)] + "\n".join(body) + markdown[section_match.end(2):]


def _parse_mermaid_entities(markdown: str) -> dict[str, dict[str, tuple[str, bool, bool]]]:
    match = re.search(r"```mermaid\s*\n(.*?)```", markdown, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Mermaid ERD code block was not found.")
    lines = [line.strip() for line in match.group(1).splitlines()]
    if not lines or lines[0] != "erDiagram":
        raise ValueError("Mermaid code block must start with erDiagram.")

    entities: dict[str, dict[str, tuple[str, bool, bool]]] = {}
    relationships: list[tuple[str, str]] = []
    current: str | None = None
    for line in lines[1:]:
        if not line:
            continue
        if line == "}":
            current = None
            continue
        if current is None:
            name_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*\{", line)
            if name_match:
                current = name_match.group(1)
                if current in entities:
                    raise ValueError(f"Mermaid diagram repeats entity {current}.")
                entities[current] = {}
                continue
            relationship = _MERMAID_RELATIONSHIP.fullmatch(line)
            if not relationship:
                raise ValueError(f"Invalid Mermaid ERD line: {line}")
            relationships.append((relationship.group(1), relationship.group(2)))
            continue

        attribute_match = re.fullmatch(
            r"([A-Za-z][A-Za-z0-9_().,-]*)\s+([A-Za-z_][A-Za-z0-9_]*)"
            r"(?:\s+((?:PK|FK|UK)(?:,\s*(?:PK|FK|UK))*)?)?(?:\s+\"[^\"]*\")?",
            line,
        )
        if not attribute_match:
            raise ValueError(f"Invalid Mermaid attribute definition: {line}")
        data_type, name, key_markers = attribute_match.groups()
        if name in entities[current]:
            raise ValueError(f"Mermaid entity {current} repeats attribute {name}.")
        markers = set(key_markers.replace(" ", "").split(",")) if key_markers else set()
        entities[current][name] = (data_type, "PK" in markers, "FK" in markers)

    if current is not None:
        raise ValueError("Mermaid entity definition is missing its closing brace.")
    for source, target in relationships:
        if source.casefold() not in {name.casefold() for name in entities} or target.casefold() not in {
            name.casefold() for name in entities
        }:
            raise ValueError(
                f"Mermaid relationship references unknown entity: {source} -> {target}."
            )
    return entities


def _parse_mermaid_relationships(
    markdown: str,
) -> list[tuple[str, str, str, str, str]]:
    match = re.search(r"```mermaid\s*\n(.*?)```", markdown, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Mermaid ERD code block was not found.")
    relationships = []
    for line in match.group(1).splitlines():
        relationship = _MERMAID_RELATIONSHIP_DETAIL.fullmatch(line.strip())
        if relationship:
            relationships.append((
                relationship.group("source"),
                relationship.group("source_card"),
                relationship.group("target_card"),
                relationship.group("target"),
                relationship.group("label"),
            ))
    return relationships


def _validate_mermaid_relationships(
    markdown: str, entities: list[ErdEntity]
) -> None:
    """Require every diagram edge to represent declared FK-backed cardinality."""
    primary_keys = {
        entity.table_name: {
            attribute.name
            for attribute in entity.attributes
            if attribute.is_primary
        }
        for entity in entities
    }
    entity_names = {entity.table_name.casefold(): entity.table_name for entity in entities}
    relationship_rows = _parse_mermaid_relationships(markdown)
    related_tables: dict[str, set[str]] = {entity.table_name: set() for entity in entities}
    for source, _, _, target, _ in relationship_rows:
        source_name = entity_names.get(source.casefold())
        target_name = entity_names.get(target.casefold())
        if not source_name or not target_name:
            raise ValueError(f"Mermaid relationship references unknown entity: {source} -> {target}.")
        related_tables[source_name].add(target_name)
        related_tables[target_name].add(source_name)

    foreign_key_pairs: set[tuple[str, str]] = set()
    for entity in entities:
        for attribute in entity.attributes:
            if not attribute.is_foreign:
                continue
            targets = [
                table_name
                for table_name, columns in primary_keys.items()
                if table_name != entity.table_name and attribute.name in columns
            ]
            if not targets:
                targets = sorted(related_tables[entity.table_name])
            if len(targets) != 1:
                raise ValueError(
                    f"Foreign key {entity.table_name}.{attribute.name} must identify exactly "
                    "one parent, either by matching a primary-key column or by an unambiguous "
                    "Mermaid relationship."
                )
            foreign_key_pairs.add((entity.table_name, targets[0]))

    relationship_pairs: set[frozenset[str]] = set()
    for source, source_card, target_card, target, _ in relationship_rows:
        source_name = entity_names.get(source.casefold())
        target_name = entity_names.get(target.casefold())
        if not source_name or not target_name:
            raise ValueError(f"Mermaid relationship references unknown entity: {source} -> {target}.")
        if not (
            (source_name, target_name) in foreign_key_pairs
            or (target_name, source_name) in foreign_key_pairs
        ):
            raise ValueError(
                f"Mermaid relationship {source_name} -> {target_name} has no corresponding foreign key."
            )
        relationship_pairs.add(frozenset((source_name, target_name)))

        if (target_name, source_name) in foreign_key_pairs:
            parent_card, child_card = source_card, target_card
        else:
            parent_card, child_card = target_card, source_card
        if parent_card not in {"||", "o|"} or child_card not in {"o{", "|{"}:
            raise ValueError(
                f"Relationship {source_name} -> {target_name} must express an FK-backed "
                "one-to-many cardinality unless a uniqueness constraint is modeled."
            )

    missing_relationships = [
        f"{child}.{parent}"
        for child, parent in foreign_key_pairs
        if frozenset((child, parent)) not in relationship_pairs
    ]
    if missing_relationships:
        raise ValueError(
            "The Mermaid ERD is missing relationships for foreign keys: "
            + ", ".join(sorted(missing_relationships))
        )


def _source_entities(jira_context: Mapping[str, Any]) -> dict[str, set[str]]:
    components = jira_context.get("architecture_components")
    if not isinstance(components, list):
        components = jira_context.get("components")
    if not isinstance(components, list):
        raise ValueError("Jira context must contain architecture_components.")

    result: dict[str, set[str]] = {}
    for component in components:
        if not isinstance(component, Mapping):
            continue
        component_id = str(component.get("component_id", "")).strip().upper()
        managed = component.get("managed_data_entities")
        if managed is None:
            managed = component.get("data_entities_handled")
        if isinstance(managed, str):
            managed_entities = [item.strip() for item in managed.split(",") if item.strip()]
        elif isinstance(managed, list):
            managed_entities = [str(item).strip() for item in managed if str(item).strip()]
        else:
            managed_entities = []
        if _COMPONENT_ID.fullmatch(component_id) and managed_entities:
            result[component_id] = set(managed_entities)
    if not result:
        raise ValueError("Jira context contains no components with valid managed data entities.")
    return result


def validate_erd_traceability(
    result: ErdGeneration, jira_context: Mapping[str, Any]
) -> ErdGeneration:
    """Ensure every generated table maps to an upstream managed data entity."""
    available = _source_entities(jira_context)
    rows = _parse_markdown_table(
        result.erd_markdown,
        "Traceability Matrix",
        ("table name", "source component id", "source data entity"),
    )
    table_names = {entity.table_name for entity in result.entities}
    for table_name, component_id, source_entity in rows:
        if table_name not in table_names:
            raise ValueError(f"Traceability references unknown generated table {table_name}.")
        component_key = component_id.strip().upper()
        if component_key not in available:
            raise ValueError(f"Traceability references unknown architecture component {component_id}.")
        entity_key = source_entity.strip()
        if entity_key not in available[component_key]:
            raise ValueError(
                f"Traceability source entity '{source_entity}' is not managed by {component_id}."
            )
    return result


async def generate_erd_package(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> ErdGeneration:
    """Generate Markdown and a validated relational database schema."""
    context_json = serialize_erd_context(jira_context)
    user_prompt = build_erd_user_prompt(context_json)

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment.")
        client = genai.Client(api_key=api_key)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name or GEMINI_MODEL_NAME,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=ERD_SYSTEM_PROMPT,
                temperature=0.15,
                response_mime_type="application/json",
                response_schema=ErdGeneration,
            ),
        )
        response_data = response.parsed
        if response_data is None:
            response_data = json.loads(response.text or "")
    elif provider == "local":
        client = AsyncOpenAI(base_url=LOCAL_LLM_URL, api_key="not-needed")
        response = await client.chat.completions.create(
            model=model_name or LOCAL_MODEL_NAME,
            messages=[
                {"role": "system", "content": ERD_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.15,
            response_format={"type": "json_object"},
        )
        response_data = json.loads(response.choices[0].message.content or "")
    else:
        raise ValueError(f"Unsupported ERD provider: {provider}")

    context_payload = (
        jira_context.model_dump(mode="json")
        if isinstance(jira_context, BaseModel)
        else jira_context
    )
    if isinstance(response_data, BaseModel):
        response_data = response_data.model_dump(mode="json")
    if isinstance(response_data, Mapping):
        response_data = dict(response_data)
        if isinstance(response_data.get("erd_markdown"), str):
            response_data["erd_markdown"] = _normalize_section_headings(
                response_data["erd_markdown"]
            )
        raw_entities = [
            ErdEntity.model_validate(entity)
            for entity in response_data.get("entities", [])
        ]
        if isinstance(response_data.get("erd_markdown"), str) and raw_entities:
            response_data["erd_markdown"] = _synchronize_schema_markdown(
                response_data["erd_markdown"], raw_entities
            )
            response_data["erd_markdown"] = _synchronize_traceability_markdown(
                response_data["erd_markdown"], context_payload
            )
    result = ErdGeneration.model_validate(response_data)
    return validate_erd_traceability(result, context_payload)


async def generate_erd(
    jira_context: BaseModel | Mapping[str, Any],
    provider: Literal["gemini", "local"] = "gemini",
    model_name: str | None = None,
) -> str:
    """Generate ERD Markdown only, retaining the concise document API."""
    result = await generate_erd_package(jira_context, provider, model_name)
    return result.erd_markdown.strip()
