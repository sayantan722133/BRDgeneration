# System Architecture Document: Simple Pension Scheme Setup Platform

## 1. Executive Summary
The Simple Pension Scheme Setup Platform (KAN-4) is a digital ecosystem designed to automate pension administration, including onboarding, contribution management, investment tracking, and benefit disbursement. The system aims to eliminate manual paperwork and ensure regulatory compliance through immutable audit trails.

## 2. Architecture Pattern & Topology
We adopt a **Modular Monolith** pattern. This provides the necessary encapsulation for domain-specific modules (Onboarding, Contributions, Investments, Benefits, Compliance) while avoiding the operational complexity of microservices during the initial rollout.

## 3. Component Catalog & Service Boundaries
- **MOD-ONBOARDING:** Manages KYC and employer/member registration.
- **MOD-CONTRIBUTIONS:** Handles payroll integration and billing.
- **MOD-INVESTMENTS:** Manages member fund allocations.
- **MOD-BENEFITS:** Automates disbursement calculations.
- **MOD-COMPLIANCE:** Ensures immutable logging for auditability.

## 4. Integration & Communication Contracts
- Internal: Synchronous REST APIs between modules.
- External: REST/Webhooks for Third-party Banking APIs (Proposed).

## 5. Data Architecture Strategy
- Relational Database (Proposed: PostgreSQL) for transactional integrity (Profiles, Contributions, Benefits).
- Immutable Ledger/Append-only store (Proposed: AWS QLDB or similar) for Audit Logs (FR-5, FR-6).

## 6. Security & Trust Boundaries
- Authentication: OIDC/OAuth2 (Proposed).
- Data Protection: Encryption at rest (AES-256) and in transit (TLS 1.3).
- RBAC: Role-based access control for Admins, Employers, and Members.

## 7. Scalability & Resilience
- Resilience: Circuit breakers for external banking API calls.
- Scalability: Horizontal scaling of the application tier via container orchestration (Proposed: Kubernetes).

## 8. Deployment Architecture
- CI/CD: Automated pipelines (Proposed: GitHub Actions/GitLab CI).
- Infrastructure: IaC (Proposed: Terraform).

## 9. Traceability Matrix
- COMP-ONBOARD-1 -> MOD-ONBOARDING -> FR-1 -> US-FR-1
- COMP-CONTRIB-1 -> MOD-CONTRIBUTIONS -> FR-2 -> US-FR-2
- COMP-INVEST-1 -> MOD-INVESTMENTS -> FR-3 -> US-FR-3
- COMP-BENEFIT-1 -> MOD-BENEFITS -> FR-4 -> US-FR-4
- COMP-COMPLIANCE-1 -> MOD-COMPLIANCE -> FR-5, FR-6 -> US-FR-5, US-FR-6

## 10. ADRs & Assumptions
- ADR-001: Modular Monolith chosen for development velocity and domain clarity.
- Assumption: Third-party banking APIs support standard RESTful webhooks for reconciliation.
