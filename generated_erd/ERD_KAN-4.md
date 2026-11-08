# Database Architecture Summary & Scope
The Simple Pension Scheme Setup Platform utilizes a modular monolith architecture. The schema is designed to support core pension lifecycle management, including member onboarding, contribution processing, investment tracking, benefit disbursement, and regulatory compliance. The target database engine is Proposed (TBD). All entities are derived from the system architecture components and functional requirements. Relationships are modeled based on business logic defined in the FRD.

## Mermaid.js Entity Relationship Diagram
```mermaid
erDiagram
  Member {
    VARCHAR(36) member_id PK "member id"
    TEXT status "status"
  }
  Contribution {
    VARCHAR(36) contribution_id PK "contribution id"
    VARCHAR(36) member_id FK "member id"
    NUMERIC(18,2) amount "amount"
  }
  Investment {
    VARCHAR(36) investment_id PK "investment id"
    VARCHAR(36) member_id FK "member id"
    TEXT fund_id "fund id"
  }
  Benefit {
    VARCHAR(36) benefit_id PK "benefit id"
    VARCHAR(36) member_id FK "member id"
    NUMERIC(18,2) calculation "calculation"
  }
  AuditLog {
    VARCHAR(36) event_id PK "event id"
    TEXT event_details "event details"
  }
  Member ||--o{ Contribution : "makes"
  Member ||--o{ Investment : "holds"
  Member ||--o{ Benefit : "receives"
```

## Data Dictionary / Table Definitions
| Table | Column | Data Type | Constraints | Description |
|---|---|---|---|---|
| Member | member_id | VARCHAR(36) | PK | Unique identifier for the member |
| Member | status | TEXT |  | Current onboarding status |
| Contribution | contribution_id | VARCHAR(36) | PK | Unique identifier for the contribution |
| Contribution | member_id | VARCHAR(36) | FK | Reference to the owning member |
| Contribution | amount | NUMERIC(18,2) |  | Contribution amount value |
| Investment | investment_id | VARCHAR(36) | PK | Unique identifier for the investment |
| Investment | member_id | VARCHAR(36) | FK | Reference to the owning member |
| Investment | fund_id | TEXT |  | Identifier for the selected fund |
| Benefit | benefit_id | VARCHAR(36) | PK | Unique identifier for the benefit record |
| Benefit | member_id | VARCHAR(36) | FK | Reference to the owning member |
| Benefit | calculation | NUMERIC(18,2) |  | Calculated benefit payment amount |
| AuditLog | event_id | VARCHAR(36) | PK | Unique identifier for the audit event |
| AuditLog | event_details | TEXT |  | Immutable description of the system event |

## Relationship & Cardinality Mapping
- Member to Contribution (Proposed 1:N): The child foreign key references the parent primary key. A member can have multiple contribution records over time. Implemented via `member_id` FK in Contribution. Confirm optionality and any uniqueness rule. The source does not establish cardinality or optionality; confirm these rules.
- Member to Investment (Proposed 1:N): The child foreign key references the parent primary key. A member can hold multiple investment allocations. Implemented via `member_id` FK in Investment. Confirm optionality and any uniqueness rule. The source does not establish cardinality or optionality; confirm these rules.
- Member to Benefit (Proposed 1:N): The child foreign key references the parent primary key. A member can receive multiple benefit payments. Implemented via `member_id` FK in Benefit. Confirm optionality and any uniqueness rule. The source does not establish cardinality or optionality; confirm these rules.
- Unresolved reference columns: `Investment.fund_id` are not declared foreign keys because their target entities are not established by the source. Confirm their target and key before implementation.

## Traceability Matrix
| Table Name | Source Component ID | Source Data Entity |
|---|---|---|
| Member | COMP-ONBOARDING-1 | Member |
| Contribution | COMP-CONTRIBUTIONS-1 | Contribution |
| Investment | COMP-INVESTMENTS-1 | Investment |
| Benefit | COMP-BENEFITS-1 | Benefit |
| AuditLog | COMP-COMPLIANCE-1 | AuditLog |
