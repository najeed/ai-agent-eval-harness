---
title: Security & Authentication
description: Industrial-grade security standards, authentication protocols, and NIST AI-100-1 alignment.
---

AgentV separates authenticated management, provider-owned execution evidence and
public certificate projections. Configure these boundaries for the deployment;
the local runtime is not an operating-system isolation layer.

## Authentication and permissions

Configure `DASHBOARD_API_KEY` / `SERVICE_API_KEY` or an AuthorizationBackend.
Use `X-Api-Key` for static headless credentials. Login at `/api/auth/login`
creates a signed session; cookies are HttpOnly, SameSite=Lax and Secure in
production. Login failures are limited to ten per minute per remote IP.

In local non-production startup with no configured keys, the Console creates a
bootstrap key under `.aes/keys/bootstrap.key` and prints onboarding instructions.
Production requires stable configured credentials/secrets and rejects ephemeral
startup. Protected reads, including scenarios and runs, require authentication;
an anonymous Viewer label does not grant API access.

The authorization provider supplies permissions and scope entitlements. Active
scope is resolved server-side and passed to run/approval/storage operations.
Client query/body context cannot confer tenant ownership. OIDC deployments can
configure `OIDC_JWKS_URL`, `OIDC_ISSUER`, `OIDC_AUDIENCE` and
`OIDC_JWKS_CACHE_TTL`; use the provider's verified claims for PBAC decisions.

## Network boundaries

`validate_http_endpoint` validates HTTP(S) URL syntax and applies configured
airgap checks. It does not impose a universal SSRF/private-address blocklist.
Readiness probes and external state-authority connections have their own URL,
allowlist and redirect checks; do not extend their guarantees to every adapter.

With `AIRGAPPED_MODE=true`, selected runtime transports reject public WAN targets
through `AirgappedConfigurationError`. The helper permits local/private/link-local
destinations and configured internal hosts. Hostname resolution checks are not
connection-level DNS pinning; recognized internal names can be accepted when DNS
is unavailable. The flag is application-level defense in depth, not a guarantee
that every process/library cannot make outbound connections.

Enforce authoritative network isolation using the deployment's container/network
policy. Treat metadata-service restrictions, egress rules, DNS and redirect
handling as explicit deployment controls. Console CSP and local assets reduce
external dependencies but do not replace network enforcement.

## Files and sandbox execution

`AEH_STRICT_JAIL=1` restricts path checks to the project jail; standard mode also
permits designated temporary locations. Tool execution and shims apply their
own parameter/policy checks. The default subprocess jail is not an OS container;
choose an appropriate jail provider when stronger process isolation is required.

The Console PID guard is local process management, not ownership authorization.
See [the actual guard checks](/builder/stability-guard/).

## Extensions

Remote modules need entry/chunk integrity and a signed publisher manifest.
Verified React modules execute in the host, not an iframe sandbox. Production
rejects unsigned/community execution and permits verified official publishers.
SRI alone does not establish publisher trust. Enforce scope and permissions on
extension server APIs independently of client navigation metadata.

## Evidence and public trust

Execution alone does not issue a certificate. Certification requires eligible
execution truth, required oracle evidence, exact trace bytes, signed finalization
and trusted signing policy. Current artifact signatures use
[digest envelopes](/spec/digest-signature-envelope/).

Complete certificates are protected at `/api/v1/certificates/<run_id>`; the public
projection is `/api/v1/certificates/<run_id>/public`. Public verification is under
`/api/v1/verify/<run_id>`. Public projections do not expose the complete private
management manifest.

The local artifact store is logically sealed and tamper-evident, not physical
WORM. Deployments requiring retention must supply a retention-enforcing provider;
`REQUIRE_IMMUTABLE_WORM=true` rejects logical-only certification storage.
SigningBackend supports external vault adapters, but AWS/GCP/Azure implementations
are deployment integrations rather than all being built-in reference providers.

## Data handling and assurance claims

Telemetry sanitization redacts selected secret patterns. Forensic PII analyzers
diagnose supplied histories; they do not guarantee all PII is removed before
every persistence path. Mandatory evidence retains exact committed objects.
Apply data minimization and storage/access controls to sensitive evidence.

AgentV's WSM weights and safety floor are framework scoring rules, not proof of
regulatory compliance by themselves. Required scenario coverage, independently
observed outcomes, deployment controls and review determine the supported claim.
