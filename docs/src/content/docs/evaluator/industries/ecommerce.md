---
title: E-Commerce Sector
description: Transactional and behavioral metrics for personalization and inventory agents.
---

The E-Commerce sector focuses on high-fidelity transactional and user behavioral data, enabling deep evaluation of agents specializing in personalization, dynamic pricing, and inventory management.

## 🛒 Status: **Provider-dependent coverage**

- **Architecture**: Olist & UCI Transactional Layer.
- **Verification**: Validate the selected source and output records for this run; no universal live-source parity guarantee is implied.

## 📡 Data Sources

The sources below describe reference datasets and task models. Actual connectivity
depends on the implemented provider, credentials and supplied input files.
Simulation is disabled by default; enable `--allow-simulation` deliberately and
retain `simulation`/`execution_mode` provenance. A listed source is not proof
that its live API was used or that all records match it.


| Source | Description |
| :--- | :--- |
| **Olist** | Brazilian E-commerce Public Dataset (Authoritative transactional data). |
| **UCI** | Online Retail datasets for behavioral and churn modeling. |
| **PriceTrack** | Real-time competitive pricing simulators for dynamic adjustment tests. |

---

## 🛠️ Industry Schema

E-Commerce records utilize identifiers for customers, products, and orders:

- `order_id` / `customer_id` / `product_id`: Deterministic transaction identifiers.
- `price`: Numerical reading (standardized to USD).
- `score`: Review score (1-5 scale) or sentiment analysis index (0-1).
- `product_category`: Standardized category labels from Olist/UCI.

---

## 🎯 Core Functions

Key functions identified for this sector include:

- **Sales & Merchandising**: Promotions, product updates, and storefront management.
- **Operations & CX**: Returns, refunds, and order status lifecycle.
- **Inventory**: Stock level monitoring and procurement.

[Explore all 1,800+ Core Functions](/builder/core-functions/)
