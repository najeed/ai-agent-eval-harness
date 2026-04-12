---
title: E-Commerce Sector
description: Transactional and behavioral metrics for personalization and inventory agents.
---

The E-Commerce sector focuses on high-fidelity transactional and user behavioral data, enabling deep evaluation of agents specializing in personalization, dynamic pricing, and inventory management.

## 🛒 Status: **HARDENED**

- **Architecture**: Olist & UCI Transactional Layer.
- **Verification**: 100% Parity with the Olist Public Dataset.

## 📡 Data Sources

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
