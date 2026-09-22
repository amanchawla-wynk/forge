# Rapid Refund PRD

## 1. Problem

Small-business sellers wait 9 days on average for marketplace refunds to settle.
41% of surveyed sellers said delayed refunds forced them to pause restocking.
Finance operations analysts handle the resulting disputes manually.
If we do nothing we expect to keep losing roughly 120 sellers per quarter to competing marketplaces.

## 2. Success metrics

The primary metric is median refund settlement time.
It is currently 9 days.
We will reduce it to 2 days.
Success is judged over the 90 days after general availability.
Dispute contact rate must not regress above 3%.

## 3. Non-goals

Cross-border refunds are explicitly out of scope for this release.
We will not change the chargeback process.

## 4. Requirements

Sellers can request a refund from the order detail screen.
The system validates that the order is eligible before submitting.
A refund that exceeds 500 USD requires manager approval.
The request and validation flows are must-have for launch, and manager approval is a should-have.

## 5. Acceptance criteria

A refund request on an eligible order settles within 2 business days.
An ineligible order shows a rejection reason and does not create a refund record.

## 6. Error and empty states

On payment provider failure the request is queued and the seller sees a retry banner.
A seller with no refunds sees an empty state explaining eligibility rules.

## 7. Instrumentation

We will log refund_requested, refund_settled, and refund_rejected events.
Median settlement time is computed from the interval between refund_requested and refund_settled.

## 8. Dependencies

This depends on the Payments platform team, the Ledger service, and our payout vendor.
Settlement cannot exceed the vendor daily cut-off of 18:00 UTC.

## 9. Privacy and compliance

The flow handles seller bank account identifiers and transaction records.
A privacy review has been requested and is scheduled before build starts.

## 10. Rollout

We will release behind the rapid_refund feature flag to 5% of sellers first.
The flag can be disabled to revert all traffic to the legacy refund path.

## 11. Open questions

Whether partial refunds are included is unresolved and owned by Priya Raman.
The vendor contract renewal date is unconfirmed and owned by Daniel Okafor.

## 12. Alternatives considered

We considered extending the existing batch settlement job.
That was rejected because it cannot meet a 2 day target.
We also considered a manual finance workflow.
That was rejected because it does not scale beyond 200 refunds per week.
