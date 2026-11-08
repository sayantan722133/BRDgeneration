# System Architecture Document: Simple Pension Scheme Setup Platform

## 1. Executive Architecture Summary
The Simple Pension Scheme Setup Platform is a digital-first solution designed to automate pension administration. The system aims to eliminate manual onboarding, streamline contribution management, provide member-facing investment tracking, and ensure regulatory compliance through automated audit trails.

## 2. Architecture Pattern & Topology
- **Pattern:** Modular Monolith (Proposed). This pattern provides clear separation of concerns across functional domains (Onboarding, Contributions, Investments, Benefits, Compliance) while maintaining operational simplicity.
- **Status:** Proposed. TBD: Deployment topology (Cloud vs On-Premise) and specific infrastructure orchestration.

## 3. Component Catalog & Boundaries
- **COMP-ONBOARDING-1:** Manages identity validation and account provisioning.
- **COMP-CONTRIBUTIONS-1:** Handles salary deduction processing and banking integration.
- **COMP-INVESTMENTS-1:** Manages member investment allocations and fund switching.
- **COMP-BENEFITS-1:** Automates benefit calculation and disbursement logic.
- **COMP-COMPLIANCE-1:** Ensures immutable logging of all system transactions.
- **COMP-CONTRIBUTIONS-2:** External integration for direct debit contributions.

## 4. Integration & Communication Contracts
- **COMP-CONTRIBUTIONS-1 to COMP-CONTRIBUTIONS-2:** REST/Synchronous Request-Response for payment processing.
- **Internal:** All other components communicate via internal service calls (Proposed).

## 5. Data Architecture Strategy
- **Account:** Owned by COMP-ONBOARDING-1.
- **Contribution:** Owned by COMP-CONTRIBUTIONS-1.
- **Investment:** Owned by COMP-INVESTMENTS-1.
- **Payment:** Owned by COMP-BENEFITS-1.
- **AuditLog:** Owned by COMP-COMPLIANCE-1.

## 6. Security, Authentication & Trust Boundaries
- **Constraint:** Must comply with local financial authority privacy and security regulations.
- **Status:** TBD: Specific authentication protocols, RBAC implementation, and encryption standards.

## 7. Scalability, Resilience & Non-Functional Architecture
- **Performance/Availability:** TBD.
- **Resilience:** TBD: Backup/Recovery and RTO/RPO targets.

## 8. Deployment Architecture & Infrastructure
- **Status:** TBD: Infrastructure as Code (IaC) and containerization strategy.

## 9. Traceability Matrix
| Component ID | Module ID | FR IDs | Story IDs | Managed Entities |
|---|---|---|---|---|
| COMP-ONBOARDING-1 | MOD-ONBOARDING | FR-1 | US-FR-1 | Account |
| COMP-CONTRIBUTIONS-1 | MOD-CONTRIBUTIONS | FR-2 | US-FR-2 | Contribution |
| COMP-INVESTMENTS-1 | MOD-INVESTMENTS | FR-3 | US-FR-3 | Investment |
| COMP-BENEFITS-1 | MOD-BENEFITS | FR-4 | US-FR-4 | Payment |
| COMP-COMPLIANCE-1 | MOD-COMPLIANCE | FR-5, FR-6 | US-FR-5, US-FR-6 | AuditLog |
| COMP-CONTRIBUTIONS-2 | MOD-CONTRIBUTIONS | FR-2 | US-FR-2 |  |

## 10. Architecture Decision Records & Technical Assumptions
- **Assumption:** Banking APIs are available for integration.
- **Decision:** FR-6 is treated as a functional extension of the Compliance module (MOD-COMPLIANCE).
