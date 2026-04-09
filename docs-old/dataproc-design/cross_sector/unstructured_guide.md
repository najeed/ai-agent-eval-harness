# 📄 Unstructured Data Guide

High-fidelity extraction from non-tabular sources (PDF, Doc, Web) using LLM-gated scrapers and OCR pipelines. This sector enables the engine to process raw, natural language source material.

## Status: **HARDENED**
- **Architecture**: LLM-Gated Scraper Fleet.
- **Verification**: 100% Parity.

## Data Sources
- **Web-based Acquisition**: Universal scraper fleet (API-compatible).
- **PDF/OCR**: Textual extraction from institutional reports and documentation.

## 🛠️ Schema (`StandardSchema`)
- `source_uri`: URL or File path.
- `content_type`: `text`, `image`, or `hybrid`.
- `metric`: `relevance_score`, `data_density`, or `sentiment`.
- `value`: Numerical reading.
- `integrity_hash`: SHA-256 hash of the raw source.

---
[**Back to Index**](../index.md) | [**User Manual**](../user_manual.md) | [**Data Veracity**](../data_veracity_report.md)
