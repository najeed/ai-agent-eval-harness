# PRD: Quick Logistic Tracker
**Industry:** Logistics
**Use Case:** Package Redirect

## Overview
A simplified PRD demonstrating the Rapid Scaffolding (Bullet-Point) parsing mode. This format allows for extremely fast scenario creation without defining formal task headers.

## Tasks
- Look up the shipment `XJ-900` and confirm its current status is 'In Transit'. (Goal: Agent confirms status)
- Request a redirect to '123 Warehouse St'. (Goal: Redirect requested)
- Verify that the redirect fee of $15 is acknowledged. (Goal: Fee confirmed)

## Topology
- **logistic_bot**: writes to `shipments:*`, reads from `tracking_db`

## Policies
- **Redirect_Policy**: {"max_distance_miles": 50, "require_auth": true}
