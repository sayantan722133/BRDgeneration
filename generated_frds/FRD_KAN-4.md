# Functional Requirements Document: Simple Pension Scheme Setup Platform

## 1. Purpose and Scope
This document defines the functional requirements for the Simple Pension Scheme Setup Platform (KAN-4). The scope includes digitizing employer onboarding, contribution management, member self-service, and automated benefit disbursements.

## 2. System Context
- **Actors:** Scheme Administrators, Employers/HR Managers, Scheme Members, Regulators/Auditors.
- **External Systems:** Third-party Banking APIs (Direct Debit), Payroll Software Providers (Dependency).
- **Trust Boundaries:** All financial transactions and PII must comply with local financial authority regulations.

## 3. Use Case Index
- UC-1: Employer Digital Onboarding (FR-1)
- UC-2: Automated Contribution Processing (FR-2)
- UC-3: Member Portal Access (FR-3)
- UC-4: Automated Benefit Disbursement (FR-4)

## 4. Functional Behavior
- **MOD-ONBOARDING:** Digital KYC and scheme setup.
- **MOD-CONTRIBUTIONS:** Automated salary deduction and billing via banking API.
- **MOD-MEMBER-EXPERIENCE:** Real-time contribution and performance tracking.
- **MOD-BENEFITS:** Automated calculation and disbursement of benefits.

## 5. Data Dictionary (Proposed)
- **EmployerProfile:** {OrgID, Name, KYCStatus, SchemeDetails}
- **ContributionRecord:** {MemberID, Amount, Date, Status}
- **BenefitCalculation:** {MemberID, EligibilityDate, Amount, AuditTrailID}

## 6. Traceability Matrix
- FR-1: KAN-10
- FR-2: KAN-11
- FR-3: KAN-12
- FR-4: KAN-13

## 7. Assumptions & Open Questions
- **Assumptions:** Banking APIs are stable; Payroll integration is required.
- **Open Questions:** Specific KYC document requirements; Benefit calculation rule definitions.
