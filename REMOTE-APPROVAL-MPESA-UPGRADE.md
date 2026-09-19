# Remote Welfare Approval + Automatic M-PESA Release

This upgrade adds a maker-checker welfare payout workflow to Alumni Hub.

## What is now enforced by the application

1. A welfare case must exist before a payout instruction can exist.
2. The case must pass the existing membership, household verification, waiting-period and annual-claim checks.
3. When the committee submits the case for approval, the amount and the principal member's registered payout number are snapshotted into a locked payout instruction.
4. Individual committee approvers sign in remotely using their own registered phone number and private PIN.
5. An approver linked to the principal member cannot approve a payout that benefits that member's household.
6. The system requires a configurable quorum (default: 2 approvals for payments up to KES 10,000; 3 approvals above KES 10,000).
7. The protected reserve is excluded from money available for new cases.
8. Other cases already awaiting approval or processing are treated as committed money and cannot be double-allocated.
9. After quorum, the system rechecks the fund. If safe funds are insufficient, the payout is blocked.
10. If M-PESA B2C is configured and `MPESA_AUTO_RELEASE=true`, the app automatically submits the disbursement after quorum. No bank visit is required for that case.
11. M-PESA callbacks mark the case Paid or Failed and store the provider reference.
12. Every material action is written to an audit log.

## M-PESA modes

- `disabled`: approval engine works, but no external payout is sent. The case becomes Authorized/Ready after quorum.
- `mock`: useful for testing. Quorum automatically produces a simulated successful payment.
- `sandbox`: sends to Safaricom Daraja sandbox using the configured credentials.
- `production`: sends to Safaricom production using the configured credentials.

Do not switch to `production` until the organization has completed Safaricom onboarding and tested the full workflow in sandbox.

## Render environment variables

Required for live B2C release:

- `MPESA_MODE=production`
- `MPESA_AUTO_RELEASE=true`
- `MPESA_CONSUMER_KEY`
- `MPESA_CONSUMER_SECRET`
- `MPESA_B2C_SHORTCODE`
- `MPESA_INITIATOR_NAME`
- `MPESA_SECURITY_CREDENTIAL`

The app derives result and timeout callbacks from `BASE_URL`. They can be overridden with `MPESA_RESULT_URL` and `MPESA_TIMEOUT_URL` if required.

## Important governance point

The software controls payouts initiated through Alumni Hub. It cannot physically stop someone who has independent high-level credentials on the M-PESA organization portal from using powers Safaricom has granted to that portal account. Configure Safaricom user roles and approval levels so the portal is at least as restrictive as Alumni Hub, and do not share Business Manager credentials.

## Existing database safety

The upgrade introduces new tables rather than adding columns to the existing member, contribution or support-case tables. `db.create_all()` can therefore create the approval, payout, fund-configuration and audit tables alongside an existing PostgreSQL database without deleting existing alumni records.
