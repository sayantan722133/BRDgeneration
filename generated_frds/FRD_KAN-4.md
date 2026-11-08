# 1. Purpose, Source Documents, and Scope
This document defines the functional requirements for the Simple Pension Scheme Setup Platform. It is based on the Business Vision (KAN-4) and the attached BRD (BRD_KAN-4.md). The scope includes digital onboarding, contribution management, investment tracking, benefit payments, and compliance auditing.

# 2. System Context and Boundaries
- **Responsibilities:** The system manages pension scheme lifecycles, from employer/member onboarding to benefit disbursement.
- **Exclusions:** None specified.
- **Actors:** Scheme Administrators, Employers/HR Managers, Individual Scheme Members, Regulators/Auditors.
- **External Systems:** Third-party banking APIs (for direct debit contributions).
- **Trust Boundaries:** The system must enforce strict data privacy and security controls as per local financial authority regulations.

# 3. Actors and Use-Case Index
- **UC-FR-1:** Digital KYC / Onboarding
- **UC-FR-2:** Contribution Management
- **UC-FR-3:** Investment Tracking
- **UC-FR-4:** Benefit Payments
- **UC-FR-5:** Compliance & Audit

# 4. Detailed Use Cases
## FR-1: Digital KYC / Onboarding
- **Goal:** Onboard employer or member.
- **Primary Actor:** Employer / HR Manager or Member.
- **Preconditions:** User has access to the platform.
- **Trigger:** User initiates onboarding process.
- **Main Success Flow:** 1. User submits data. 2. System validates identity. 3. System creates account. 4. System confirms success.
- **Alternate Flows:** 1. Data incomplete: System prompts user for missing fields.
- **Exception Flows:** 1. Identity validation fails: System rejects onboarding and notifies user.
- **Postconditions:** Account created and status set to Active.
- **Linked FR IDs:** FR-1

## FR-2: Contribution Management
- **Goal:** Process salary deductions.
- **Primary Actor:** Employer / HR Manager.
- **Preconditions:** Employer account is active.
- **Trigger:** Salary deduction event occurs.
- **Main Success Flow:** 1. System receives deduction data. 2. System generates automated billing. 3. System updates member records. 4. System confirms update.
- **Alternate Flows:** 1. Payment failure: System flags billing as overdue.
- **Exception Flows:** 1. Data mismatch: System halts processing and alerts administrator.
- **Postconditions:** Member balance updated.
- **Linked FR IDs:** FR-2

## FR-3: Investment Tracking
- **Goal:** View and manage investments.
- **Primary Actor:** Individual Scheme Member.
- **Preconditions:** Member is logged in.
- **Trigger:** Member accesses portal.
- **Main Success Flow:** 1. Member requests investment view. 2. System displays current allocation. 3. Member initiates fund switch. 4. System updates allocation.
- **Alternate Flows:** 1. Fund unavailable: System restricts selection.
- **Exception Flows:** 1. System error: System displays error message and logs event.
- **Postconditions:** Investment allocation updated.
- **Linked FR IDs:** FR-3

## FR-4: Benefit Payments
- **Goal:** Disburse benefits.
- **Primary Actor:** Scheme Administrator.
- **Preconditions:** Benefit criteria met.
- **Trigger:** Payment trigger event.
- **Main Success Flow:** 1. System detects trigger. 2. System calculates benefit amount. 3. System initiates disbursement. 4. System records payment.
- **Alternate Flows:** 1. Insufficient funds: System notifies administrator.
- **Exception Flows:** 1. Calculation error: System halts payment and flags for review.
- **Postconditions:** Benefit payment recorded.
- **Linked FR IDs:** FR-4

## FR-5: Compliance & Audit
- **Goal:** Generate audit trail.
- **Primary Actor:** Regulator / Auditor.
- **Preconditions:** System transaction completed.
- **Trigger:** Transaction completion.
- **Main Success Flow:** 1. Transaction completes. 2. System generates immutable audit log entry. 3. System stores entry.
- **Alternate Flows:** 1. Log failure: System alerts administrator.
- **Exception Flows:** 1. Storage full: System halts transaction.
- **Postconditions:** Audit trail updated.
- **Linked FR IDs:** FR-5

# 5. Functional Behavior and Workflows
- **MOD-ONBOARDING:** Validates identity and provisions accounts.
- **MOD-CONTRIBUTIONS:** Interfaces with banking APIs for billing.
- **MOD-INVESTMENTS:** Manages fund allocation logic.
- **MOD-BENEFITS:** Automates calculation and disbursement.
- **MOD-COMPLIANCE:** Ensures all transactions are logged immutably.

# 6. Data Entities and Data Dictionary
| Entity | Purpose | Attribute | Data Type | Required | Relationships | Source FR | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Account | Identity | ID | UUID | Yes | N/A | FR-1 | Confirmed |
| Contribution | Billing | Amount | Decimal | Yes | Member | FR-2 | Confirmed |
| Investment | Allocation | FundID | String | Yes | Member | FR-3 | Confirmed |
| Payment | Disbursement | Amount | Decimal | Yes | Member | FR-4 | Confirmed |
| AuditLog | Compliance | Entry | String | Yes | Transaction | FR-5 | Confirmed |

# 7. Interfaces and Integrations
| System | Direction | Data | Trigger | Success/Failure | Open Decisions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Banking API | Outbound | Payment Data | Contribution | Success/Failure | TBD |

# 8. System Constraints and Non-Functional Requirements
- **Security:** Compliance with local financial authority regulations.
- **Performance:** TBD.
- **Availability:** TBD.

# 9. Traceability Matrix
| FR ID | Story ID | Source Jira Issue Keys |
|---|---|---|
| FR-1 | US-FR-1 | KAN-10 |
| FR-2 | US-FR-2 | KAN-11 |
| FR-3 | US-FR-3 | KAN-12 |
| FR-4 | US-FR-4 | KAN-13 |
| FR-5 | US-FR-5 | KAN-25 |

# 10. Assumptions, Open Questions, and Decisions
- **Assumption:** Banking APIs are available.
- **Open Question:** FR-6 (KAN-26) is a duplicate of FR-5; confirm if it should be merged or dropped.
