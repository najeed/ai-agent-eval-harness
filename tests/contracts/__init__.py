"""
tests/contracts/__init__.py
Contract Test Suite Package for agentv v2.0.0.

Validates public surface area contracts that, when broken, require a semver MAJOR bump.
Test categories:
  - test_aes_schema_contract.py        (AES v1.4 scenario validation)
  - test_plugin_discovery_contract.py  (Plugin entry-point discovery)
  - test_config_hash_contract.py       (ResolvedRuntimeConfig hash stability)
  - test_execution_lifecycle_contract.py (ExecutionBackend lifecycle)
  - test_verification_contract.py      (TraceVerifier and cert chain)
"""
