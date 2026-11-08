# Functional Requirements Document: Simple Pension Scheme Setup Platform

## 1. Purpose, Source Documents, and Scope
This document defines the functional requirements for the Simple Pension Scheme Setup Platform (KAN-4). It is based on the BRD_KAN-4.md document. The scope includes digital onboarding, contribution management, investment tracking, benefit payments, and compliance auditing.

## 2. System Context and Boundaries
- **Responsibilities:** The system manages pension lifecycle data, performs automated calculations, and integrates with banking APIs.
- **Exclusions:** Specific third-party banking API providers are TBD.
- **Actors:** Scheme Administrators, Employers/HR Managers, Scheme Members, Regulators/Auditors.
- **External Systems:** Third-party Banking APIs (for direct debit).
- **Trust Boundaries:** The system must enforce strict access control and data privacy per local financial regulations.

## 3. Actors and Use-Case Index
- **FR-01:** Employer/Member Onboarding
- **FR-02:** Contribution Management
- **FR-03:** Investment Tracking
- **FR-04:** Benefit Payments
- **FR-05:** Compliance/Audit

## 4. Detailed Use Cases
### FR-01: Digital KYC/Onboarding
- **Goal:** Onboard new employers or members.
- **Primary Actor:** Employer/Member.
- **Preconditions:** User has valid identity documentation.
- **Trigger:** User initiates registration.
- **Main Success Flow:** 1. User submits data. 2. System validates data. 3. System creates account. 4. System confirms onboarding.
- **Alternate Flows:** 1. Data incomplete: System prompts for missing fields.
- **Exception Flows:** 1. Validation failure: System rejects submission and notifies user.
- **Postconditions:** Account created and status set to Active.
- **Linked FR IDs:** FR-01

### FR-02: Contribution Management
- **Goal:** Process salary deductions and billing.
- **Primary Actor:** Employer.
- **Preconditions:** Employer account active.
- **Trigger:** Payroll cycle completion.
- **Main Success Flow:** 1. Employer submits deduction data. 2. System validates data. 3. System generates billing. 4. System updates contribution records.
- **Alternate Flows:** 1. Payment failure: System flags for manual review.
- **Exception Flows:** 1. Invalid data: System rejects batch.
- **Postconditions:** Contribution records updated.
- **Linked FR IDs:** FR-02

### FR-03: Investment Tracking
- **Goal:** View and manage investments.
- **Primary Actor:** Scheme Member.
- **Preconditions:** Member account active.
- **Trigger:** Member logs into portal.
- **Main Success Flow:** 1. Member accesses portal. 2. System retrieves account data. 3. System displays allocation. 4. Member initiates fund switch. 5. System processes switch.
- **Alternate Flows:** 1. Read-only access: Member views but cannot switch.
- **Exception Flows:** 1. System error: Display error message.
- **Postconditions:** Investment allocation updated.
- **Linked FR IDs:** FR-03

### FR-04: Benefit Payments
- **Goal:** Calculate and disburse benefits.
- **Primary Actor:** Scheme Administrator.
- **Preconditions:** Eligibility event confirmed.
- **Trigger:** Benefit eligibility event.
- **Main Success Flow:** 1. System detects event. 2. System calculates benefit. 3. System initiates disbursement. 4. System records transaction.
- **Alternate Flows:** 1. Manual override: Admin adjusts calculation.
- **Exception Flows:** 1. Insufficient funds: Halt disbursement.
- **Postconditions:** Benefit paid.
- **Linked FR IDs:** FR-04

### FR-05: Compliance/Audit
- **Goal:** Generate audit trails.
- **Primary Actor:** Regulator/Auditor.
- **Preconditions:** Transaction completed.
- **Trigger:** System event.
- **Main Success Flow:** 1. Transaction occurs. 2. System captures event details. 3. System writes to immutable log.
- **Alternate Flows:** None.
- **Exception Flows:** 1. Log failure: System alerts admin.
- **Postconditions:** Audit entry created.
- **Linked FR IDs:** FR-05

## 5. Functional Behavior and Workflows
- **MOD-ONBOARDING:** Validates KYC data against regulatory rules.
- **MOD-CONTRIBUTIONS:** Automates billing via banking API.
- **MOD-INVESTMENTS:** Provides real-time allocation views.
- **MOD-BENEFITS:** Automates calculations based on scheme rules.
- **MOD-COMPLIANCE:** Ensures all state changes are logged.

## 6. Data Entities and Data Dictionary
| Entity | Purpose | Attribute | Data Type | Required | Relationships | Source FR | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Member | Identity | MemberID | UUID | Yes | N/A | FR-01 | Proposed |
| Contribution | Record | Amount | Decimal | Yes | Member | FR-02 | Proposed |
| Investment | Allocation | FundID | String | Yes | Member | FR-03 | Proposed |
| Benefit | Payment | Calculation | Decimal | Yes | Member | FR-04 | Proposed |
| AuditLog | Compliance | EventID | UUID | Yes | All | FR-05 | Proposed |

## 7. Interfaces and Integrations
| System | Direction | Data | Trigger | Success | Failure |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Banking API | Outbound | Payment Request | Billing | Success | Retry/Alert |

## 8. System Constraints and Non-Functional Requirements
- **Security:** Compliance with local financial regulations.
- **Integration:** Banking API integration required.
- **Performance:** TBD.
- **Availability:** TBD.

## 9. Traceability Matrix
| FR ID | Story ID | Source Jira Issue Keys |
|---|---|---|
| FR-01 | US-FR-01 | KAN-10 |
| FR-02 | US-FR-02 | KAN-11 |
| FR-03 | US-FR-03 | KAN-12 |
| FR-04 | US-FR-04 | KAN-13 |
| FR-05 | US-FR-05 | KAN-25 |

## 10. Assumptions, Open Questions, and Decisions
- **Assumption:** Banking APIs are available.
- **Open Question:** Which specific banking providers are supported? (TBD)
- **Decision:** FR-6 in Jira is a duplicate of FR-05 and will be ignored.
