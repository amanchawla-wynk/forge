# Rapid Refund PRD

Owner: Maya Chen. Status: approved v1.3, last materially updated 2026-09-20.

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

The primary flow starts when an authenticated seller opens an eligible order, requests a refund, and ends when the seller sees the settlement status.
The seller must own the order, have refund permission, and provide an amount no greater than the captured payment.
Sellers can request a refund from the order detail screen.
The system validates that the order is eligible before submitting.
A refund that exceeds 500 USD requires manager approval.
The request and validation flows are must-have for launch, and manager approval is a should-have.

## 5. Acceptance criteria

A refund request on an eligible order settles within 2 business days.
An ineligible order shows a rejection reason and does not create a refund record.
Requests without permission, above the captured amount, or submitted twice must be rejected without creating a second refund.

## 6. Error and empty states

On payment provider failure the request is queued and the seller sees a retry banner.
A seller with no refunds sees an empty state explaining eligibility rules.
While eligibility is checked the seller sees a loading state, and an interrupted request can be resumed from the queued state.
The supported platforms are responsive web, iOS, and Android; other channels are excluded from this release.
The web and mobile flows must meet WCAG 2.1 AA, keyboard-navigation, and screen-reader checks before launch.

## 7. Instrumentation

We will log refund_requested, refund_settled, and refund_rejected events.
Median settlement time is computed from the interval between refund_requested and refund_settled.
Operations monitors settlement queue depth on a dashboard and receives an alert when queued refunds exceed 100.

## 8. Dependencies

This depends on the Payments platform team, the Ledger service, and our payout vendor.
Payments owns platform readiness by build start; Ledger owns idempotency by QA; if the vendor is unavailable, requests remain queued on the legacy path.
Settlement cannot exceed the vendor daily cut-off of 18:00 UTC.

## 9. Privacy and compliance

The flow handles seller bank account identifiers and transaction records.
Bank identifiers are required only to route the refund; the flow stores the existing token rather than collecting new bank details.
Only Finance Operations and the Payments service can access the token; the payout vendor processes it under the existing data-processing agreement.
A privacy review has been requested and is scheduled before build starts.
Transaction audit records are retained for 7 years, while bank account identifiers are deleted 30 days after settlement.

## 10. Rollout

We will release behind the rapid_refund feature flag to 5% of sellers first.
We expand after 7 days if median settlement is at most 2 days and dispute contacts stay below 3%; we pause if queue depth exceeds 100 or error rate exceeds 1%.
The flag can be disabled to revert all traffic to the legacy refund path.
Maya Chen owns rollout decisions and the Payments on-call lead can execute rollback.
Support receives a troubleshooting guide before pilot launch; affected sellers receive an in-product notice, while sales and marketing need no launch campaign.

## 11. Open questions

Whether partial refunds are included is unresolved, owned by Priya Raman, and due before design sign-off on 2026-09-28.
The vendor contract renewal date is unconfirmed, owned by Daniel Okafor, and must be resolved before build starts on 2026-10-02.

## 12. Alternatives considered

We considered extending the existing batch settlement job.
That was rejected because it cannot meet a 2 day target.
We also considered a manual finance workflow.
That was rejected because it does not scale beyond 200 refunds per week.

## 13. Assumptions and validation

We assume at least 70% of delayed refunds are eligible for the accelerated vendor route and that sellers understand the existing settlement-status language.
Priya Raman will validate route eligibility against August transaction data by 2026-09-27, and Design Research will test the status language with five sellers before design sign-off.

## 14. Operational readiness

The service must sustain 40 refunds per second, keep refund API p95 latency below 500 ms, and recover queued requests within 30 minutes after a provider outage.
The Payments on-call team owns monitoring, first-line incident response, and escalation to Finance Operations.
The rapid-refund runbook covers queue diagnosis, feature-flag rollback, replay from the durable queue, and reconciliation against Ledger records.
