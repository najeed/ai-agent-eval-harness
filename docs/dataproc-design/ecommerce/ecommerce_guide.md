# 🛒 eCommerce Sector: Deep-Dive Guide

## 🛰️ Data Source Strategy
The eCommerce sector provides the "Gold Standard" for transactional audit trails and customer sentiment.

### 1. Olist (Brazilian eCommerce)
*   **Role**: Primary source for relational order-to-delivery logistics.
*   **Logic**:
    *   Fetch **Relational CSVs** (Orders, Payments, Reviews).
    *   Field focus: `delivery_latency`, `payment_installments`, `sentiment`.
    *   **Simulation**: Uses synthetic order logs for CI/CD parity.

### 2. UCI Online Retail (UK)
*   **Role**: High-volume transactional logs.
*   **Logic**:
    *   **Factual Benchmark**: Used for validating basket-analysis agents.
    *   **Reasoning Injection**: Perform multi-currency VAT calculation and return-rate probability modeling.

## 🛠️ ETL & Transformation
1.  **Relational Flattening**: Denormalize 7+ eCommerce tables into a unified `StandardSchema` record.
2.  **Sentiment Mapping**: LLM-driven conversion of customer reviews (1-5 star) to a calibrated 0-1 scale.
3.  **Temporal Drift**: Historical price change tracking acrossSKU categories.

## 🛡️ Robustness & Safety
*   **License Compliance**: Strict enforcement of CC BY-NC-SA terms via external linking.
*   **Veracity**: Every transaction is hash-linked to ensure deterministic replays.
*   **Fallback**: High-fidelity simulation for transactional logs is active by default.
