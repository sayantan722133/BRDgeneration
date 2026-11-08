# System Architecture Document: Simple Pension Scheme Setup Platform

## 1. Executive Architecture Summary
The Simple Pension Scheme Setup Platform (KAN-4) is a digital ecosystem designed to automate pension administration. The system aims to eliminate manual onboarding, automate contribution billing, provide member self-service, and ensure regulatory compliance through immutable audit trails.

## 2. Architecture Pattern & Topology
- **Pattern:** Modular Monolith with Event-Driven Audit Logging.
- **Rationale:** Provides clear separation of concerns (Onboarding, Contributions, Investments, Benefits, Compliance) while maintaining data consistency for financial transactions.
- **Status:** Proposed.

## 3. Component Catalog & Boundaries
- **COMP-ONBOARDING-1:** Manages KYC and user registration.
- **COMP-CONTRIBUTIONS-1:** Handles salary deductions and billing.
- **COMP-INVESTMENTS-1:** Manages member fund allocation.
- **COMP-BENEFITS-1:** Automates benefit calculations.
- **COMP-COMPLIANCE-1:** Manages immutable audit logs.
- **COMP-CONTRIBUTIONS-2:** External integration for direct debit.

## 4. Integration & Communication Contracts
- **COMP-CONTRIBUTIONS-1** to **COMP-CONTRIBUTIONS-2**: REST, Synchronous Request-Response, Payment Request.
- **COMP-CONTRIBUTIONS-1** to **COMP-COMPLIANCE-1**: Asynchronous Event, Audit Log Entry.

## 5. Data Architecture Strategy
- **Entities:** Member, Contribution, Investment, Benefit, AuditLog.
- **Ownership:** Each component owns its respective domain entity.

## 6. Security, Authentication & Trust Boundaries
- **Constraint:** Compliance with local financial authority privacy regulations.
- **Status:** TBD (Authentication/RBAC mechanisms).

## 7. Scalability, Resilience & Non-Functional Architecture
- **Performance:** TBD.
- **Availability:** TBD.

## 8. Deployment Architecture & Infrastructure
- **Status:** TBD (Cloud provider, container orchestration).

## 9. Traceability Matrix
| Component ID | Module ID | FR IDs | Story IDs | Managed Entities |
|---|---|---|---|---|
| COMP-ONBOARDING-1 | MOD-ONBOARDING | FR-01 | US-FR-01 | Member |
| COMP-CONTRIBUTIONS-1 | MOD-CONTRIBUTIONS | FR-02 | US-FR-02 | Contribution |
| COMP-INVESTMENTS-1 | MOD-INVESTMENTS | FR-03 | US-FR-03 | Investment |
| COMP-BENEFITS-1 | MOD-BENEFITS | FR-04 | US-FR-04 | Benefit |
| COMP-COMPLIANCE-1 | MOD-COMPLIANCE | FR-05 | US-FR-05 | AuditLog |
| COMP-CONTRIBUTIONS-2 | MOD-CONTRIBUTIONS | FR-02 | US-FR-02 |  |

## 10. Architecture Decision Records
- **Decision:** FR-6 is treated as a duplicate of FR-05 per BRD instructions.
