# Database Architecture Summary & Scope
The Simple Pension Scheme Setup Platform utilizes a modular monolith architecture. The database schema is designed to support core functional domains: Onboarding, Contributions, Investments, Benefits, and Compliance. The target database engine is currently Proposed (TBD) as the system is in the design phase. All constraints are derived from the FRD and architecture components.

## Mermaid.js Entity Relationship Diagram
```mermaid
erDiagram
  account {
    VARCHAR(36) account_id PK "account id"
    VARCHAR(20) status "status"
  }
  contribution {
    VARCHAR(36) contribution_id PK "contribution id"
    VARCHAR(36) account_id FK "account id"
    NUMERIC(18,2) amount "amount"
  }
  investment {
    VARCHAR(36) investment_id PK "investment id"
    VARCHAR(36) account_id FK "account id"
    VARCHAR(50) fund_id "fund id"
  }
  payment {
    VARCHAR(36) payment_id PK "payment id"
    VARCHAR(36) account_id FK "account id"
    NUMERIC(18,2) amount "amount"
  }
  audit_log {
    VARCHAR(36) log_id PK "log id"
    TEXT entry "entry"
    TIMESTAMP created_at "created at"
  }
  account ||--o{ contribution : "makes"
  account ||--o{ investment : "holds"
  account ||--o{ payment : "receives"
```

## Data Dictionary / Table Definitions
| Table | Column | Data Type | Constraints | Description |
|---|---|---|---|---|
| account | account_id | VARCHAR(36) | PK | Unique identifier for the account |
| account | status | VARCHAR(20) |  | Current status of the account |
| contribution | contribution_id | VARCHAR(36) | PK | Unique identifier for the contribution |
| contribution | account_id | VARCHAR(36) | FK | Reference to the owning account |
| contribution | amount | NUMERIC(18,2) |  | Monetary value of the contribution |
| investment | investment_id | VARCHAR(36) | PK | Unique identifier for the investment |
| investment | account_id | VARCHAR(36) | FK | Reference to the owning account |
| investment | fund_id | VARCHAR(50) |  | Identifier for the selected fund |
| payment | payment_id | VARCHAR(36) | PK | Unique identifier for the payment |
| payment | account_id | VARCHAR(36) | FK | Reference to the receiving account |
| payment | amount | NUMERIC(18,2) |  | Monetary value of the payment |
| audit_log | log_id | VARCHAR(36) | PK | Unique identifier for the log entry |
| audit_log | entry | TEXT |  | Immutable transaction log details |
| audit_log | created_at | TIMESTAMP |  | Timestamp of the log creation |

## Relationship & Cardinality Mapping
- account to contribution (Proposed 1:N): The child foreign key references the parent primary key. ** An account can have multiple contributions over time. Implemented via `contribution.account_id` FK. Confirm optionality and any uniqueness rule. The source does not establish cardinality or optionality; confirm these rules.
- account to investment (Proposed 1:N): The child foreign key references the parent primary key. ** An account can hold multiple investment allocations. Implemented via `investment.account_id` FK. Confirm optionality and any uniqueness rule. The source does not establish cardinality or optionality; confirm these rules.
- account to payment (Proposed 1:N): The child foreign key references the parent primary key. ** An account can receive multiple benefit payments. Implemented via `payment.account_id` FK. Confirm optionality and any uniqueness rule. The source does not establish cardinality or optionality; confirm these rules.
- Unresolved reference columns: `investment.fund_id` are not declared foreign keys because their target entities are not established by the source. Confirm their target and key before implementation.

## Traceability Matrix
| Table Name | Source Component ID | Source Data Entity |
|---|---|---|
| account | COMP-ONBOARDING-1 | Account |
| contribution | COMP-CONTRIBUTIONS-1 | Contribution |
| investment | COMP-INVESTMENTS-1 | Investment |
| payment | COMP-BENEFITS-1 | Payment |
| audit_log | COMP-COMPLIANCE-1 | AuditLog |
