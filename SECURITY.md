# Security Policy

## Supported Versions

We actively maintain and provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < Latest| :x:                |

## Industrial Security & Trust (v1.6.2)

The Evaluation Harness v1.6.2 includes advanced **Industrial Security Hardening**, a **Cryptographic Trust Protocol (v3.0.0)**, and **Post-Quantum Cryptographic (PQC) Certification** to guarantee the integrity and non-repudiability of your evaluations.

For detailed technical information on these features, please refer to:
- **[COMPLIANCE.md](COMPLIANCE.md)**: Deep dive into **NIST AI RMF Alignment**, the **Weighted Severity Model (WSM)**, and our **Hybrid PQC Protocol**.
- **[Industrial Security Hardening (R1-R3)](docs-old/guides/07_SECURITY_AND_AUTHENTICATION.md#5-industrial-security-hardening-v123)**: Details on SSRF protection, telemetry masking, and operational controls.
- **[The Trust Protocol](docs-old/guides/07_SECURITY_AND_AUTHENTICATION.md#6-the-trust-protocol-fingerprinting--certification)**: Overview of trace fingerprinting and the public Certification API.

### Core Security Guarantees

1. **Hybrid Post-Quantum Cryptography (PQC)**:
   * Aligned with NIST standards, evaluations employ a dual-layer cryptographic signature scheme: a **Classical Layer (Ed25519)** coupled with a **Post-Quantum Layer (ML-DSA-65)**.
   * Signatures are chained inside the `provenance_chain` of the **Verification Certificate (VC) v3.0.0** manifest, protecting reports against quantum-aided decryption or forgery.

2. **Zero-Exposure Signing (ZES)**:
   * To prevent any leak of proprietary trajectories, agent data, or environment configurations, the framework implements **Zero-Exposure Signing (ZES)**.
   * Traces are hashed locally using **SHAKE-256**, and only the resulting digest is securely transmitted to post-quantum key management endpoints (such as CycleCore) for signing.

3. **Strict Policy Enforcement (Fail-Closed)**:
   * When `PQC_STRICT_MODE=true` is enabled, the pipeline enforces a strict, fail-closed policy. If the PQC validation fails or the provider is unreachable, evaluations are automatically marked **NON-COMPLIANT**, blocking promotion.

4. **Hardened Sandboxed Isolation (VFS/Jails)**:
   * Untrusted agent code is executed within structurally isolated sandboxes utilizing **Virtual File Systems (VFS)** and restricted jail environments. This ensures tight path jail enforcement, memory limits, and strict network routing restrictions to prevent jailbreak attempts.

---

## Reporting a Vulnerability

We take the security of the AgentV seriously. If you discover a security vulnerability, please follow these steps:

### How to Report

1. **Do NOT create a public GitHub issue** for security vulnerabilities
2. Send an email to agentv@agentvos.ai with the subject line: "Security Vulnerability Report"
3. Include the following information:
   - Description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact assessment
   - Any suggested fixes (if available)
   - Your contact information for follow-up

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Initial Assessment**: We will provide an initial assessment within 5 business days
- **Regular Updates**: We will keep you informed of our progress every 7 days until resolution
- **Resolution Timeline**: We aim to resolve critical vulnerabilities within 30 days

### Responsible Disclosure

We follow responsible disclosure practices:
- We will work with you to understand and resolve the issue
- We will credit you in our security advisory (unless you prefer to remain anonymous)
- We ask that you do not publicly disclose the vulnerability until we have released a fix

## Security Best Practices for Contributors

### Code Security

1. **Input Validation**: Always validate and sanitize inputs, especially when executing AI agent code
2. **Sandboxing**: Ensure proper isolation when running untrusted agent code
3. **Dependency Management**: 
   - Keep dependencies up to date
   - Use `pip-audit` or similar tools to check for known vulnerabilities
   - Pin dependency versions in requirements files

### AgentV Security

1. **Code Execution**: 
   - Use secure sandboxes for agent code execution
   - Implement proper timeouts and resource limits
   - Never execute agent code with elevated privileges
2. **Data Handling**:
   - Don't log sensitive information from agent interactions
   - Sanitize outputs before storing or displaying
   - Be cautious with file system access in evaluations

### Environment Security

1. **API Keys and Secrets**:
   - Never commit API keys, tokens, or secrets to the repository
   - Use environment variables or secure secret management
   - Provide clear documentation on required environment variables
2. **Configuration**:
   - Use secure defaults in configuration files
   - Validate configuration parameters
   - Document security implications of configuration options

## Security Considerations for Users

### Running Evaluations

1. **Isolated Environment**: Run evaluations in isolated environments (containers, VMs)
2. **Network Access**: Be cautious about agent network access during evaluations
3. **File System**: Limit agent file system access to necessary directories only
4. **Resource Limits**: Set appropriate CPU, memory, and time limits

### AI Model Integration

1. **API Security**: Use secure connections (HTTPS) for AI model APIs
2. **Authentication**: Properly secure API keys and authentication tokens
3. **Rate Limiting**: Implement appropriate rate limiting to prevent abuse
4. **Data Privacy**: Be aware of data sent to external AI services

## Known Security Considerations

### Agent Code Execution
- This framework executes AI-generated code, which inherently carries security risks
- Always run in isolated, sandboxed environments
- Review agent outputs before execution in production environments

### External Dependencies
- AI agents may attempt to install or import external packages
- Use virtual environments and dependency isolation
- Monitor and control package installation during evaluations

### Data Exposure
- Evaluation results may contain sensitive information
- Implement proper access controls for evaluation data
- Consider data retention and deletion policies

### Upstream Toolchain Vulnerabilities
- Certain core tools (e.g., `pip`) may have known vulnerabilities with no immediate upstream fix.
- **CVE-2026-3219 (pip)**: Handling of concatenated archives. Currently unpatchable as of 2026-04-25. 
- Mitigation: We enforce the use of trusted, verified package sources and hashes in production environments. CI/CD pipelines explicitly document these exclusions.

## Security Updates

### How We Handle Security Issues

1. **Assessment**: We assess the severity and impact of reported vulnerabilities
2. **Fix Development**: We develop and test fixes in private branches
3. **Coordinated Release**: We coordinate the release of fixes with security advisories
4. **Communication**: We communicate security updates through:
   - GitHub Security Advisories
   - Release notes
   - Email notifications to maintainers

### Severity Classification

We use the following severity levels:

- **Critical**: Immediate threat to user security or data
- **High**: Significant security risk requiring prompt attention
- **Medium**: Important security issue with moderate impact
- **Low**: Minor security concern with limited impact

## Compliance and Standards

This project aims to follow security best practices including:
- OWASP security guidelines
- Secure coding practices for Python
- Container security best practices (when applicable)
- API security standards

## Contact Information

For security-related questions or concerns:
- Security issues: agentv@agentvos.ai
- General questions: agentv@agentvos.ai
- Maintainer: agentv@agentvos.ai

## Acknowledgments

We appreciate the security research community's efforts in keeping open source projects secure. Contributors who responsibly disclose security vulnerabilities will be acknowledged in our security advisories.

---

*This security policy is reviewed and updated regularly to ensure it remains current with best practices and project needs.*
