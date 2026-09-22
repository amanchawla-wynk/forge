# Seller Payout Dashboard PRD

## Problem

Sellers cannot see when a payout will arrive, and support handles about 300 payout questions each week.
Sellers running daily operations are the people affected.

## Goals

We want payout transparency to feel effortless and to make sellers trust the platform more.
We will track payout page engagement.

## Requirements

Sellers can open a payout dashboard from the account menu.
The dashboard lists each payout with its status and expected arrival date.
A seller can filter payouts by date range.
Everything listed here is required for launch.

## States

If the payout service is unavailable the dashboard shows a cached view with a stale-data notice.
A new seller with no payouts sees onboarding guidance instead of an empty table.

## Dependencies

This work depends on the Payouts service team and the existing notification platform.

## Rollout

We will ship the dashboard to all sellers in a single release.

## Open questions

Whether we show fee breakdowns is still undecided.
