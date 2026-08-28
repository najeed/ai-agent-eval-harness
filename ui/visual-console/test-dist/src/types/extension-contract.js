/**
 * TypeScript mirror of agentv_runtime.extension_contract (SemVer-guaranteed
 * public API, contract version 1.0.0 — additive-only within 1.x).
 *
 * The host MUST validate dynamically imported remote modules against this
 * contract before mounting. SRI proves bytes; only a signed manifest with an
 * explicit publisher and capability declarations grants trust.
 */
export const EXTENSION_CONTRACT_VERSION = '1.0.0';
export const EXTENSION_CONTRACT_STATUS = 'stable';
export const KNOWN_CAPABILITIES = [
    'routes',
    'navigation',
    'lifecycle',
    'runs:read',
    'scenarios:read',
];
export const KNOWN_HOST_APIS = [
    'runtime.health.get',
    'runtime.runs.list',
    'runtime.runs.get',
    'runtime.scenarios.list',
    'runtime.evidence.link',
];
/**
 * [D2] Host APIs that only READ host state. These are the ONLY APIs granted
 * to unsigned/local extensions. Any future mutating host API MUST NOT be
 * added here.
 */
export const READ_ONLY_HOST_APIS = [
    'runtime.health.get',
    'runtime.runs.list',
    'runtime.runs.get',
    'runtime.scenarios.list',
    'runtime.evidence.link',
];
/** Host APIs reserved for trusted tiers (must be non-read-only calls). */
export const TRUSTED_HOST_APIS = [];
/** [D2] Tier-based host API access policy. */
export function hostApisForTier(tier) {
    return tier === 'official' || tier === 'community'
        ? [...READ_ONLY_HOST_APIS, ...TRUSTED_HOST_APIS]
        : READ_ONLY_HOST_APIS;
}
/**
 * [D2] Single authorization predicate used by the extension host context.
 * A call is granted iff it is explicitly declared in the extension's
 * manifest AND allowed by the tier's allow-list; every name outside the
 * intersection — including undeclared or unknown APIs — is denied by default.
 */
export function canCallHostApi(tier, call, manifest) {
    if (manifest?.host_apis && Array.isArray(manifest.host_apis)) {
        if (!manifest.host_apis.includes(call))
            return false;
    }
    return hostApisForTier(tier).includes(call);
}
export function parseSemver(version) {
    const core = version.trim().replace(/^v/, '').split('-')[0].split('.');
    if (core.length < 2)
        throw new Error(`Not a SemVer core: ${version}`);
    return [Number(core[0]), Number(core[1]), Number(core[2] ?? 0)];
}
/** Same major; manifest minor must not exceed host minor. */
export function isCompatible(manifestApiVersion, hostApiVersion) {
    try {
        const [mj, mn] = parseSemver(manifestApiVersion);
        const [hmj, hmn] = parseSemver(hostApiVersion);
        return mj === hmj && mn <= hmn;
    }
    catch {
        return false;
    }
}
/**
 * Validates a manifest object against the contract.
 * @returns list of violations; empty means valid.
 */
export function validateExtensionManifest(manifest, opts = {}) {
    const { requireSignature = true } = opts;
    const violations = [];
    if (!manifest || typeof manifest !== 'object') {
        return ['Manifest is missing or not an object'];
    }
    const m = manifest;
    if (!m.extension_id)
        violations.push('extension_id is required');
    if (!m.display_name)
        violations.push('display_name is required');
    if (!m.version)
        violations.push('version is required');
    const remoteEntry = m.remote_entry ?? m.remoteEntry;
    const sriHash = m.sri_hash ?? m.sriHash;
    if (!remoteEntry)
        violations.push('remote_entry is required');
    if (!sriHash)
        violations.push('sri_hash (integrity digest) is required');
    try {
        parseSemver(m.version ?? '');
    }
    catch {
        violations.push(`version must be SemVer: ${String(m.version)}`);
    }
    if (m.api_version &&
        !isCompatible(m.api_version, EXTENSION_CONTRACT_VERSION)) {
        violations.push(`api_version ${m.api_version} is incompatible with host contract ${EXTENSION_CONTRACT_VERSION}`);
    }
    if (requireSignature) {
        if (!m.publisher)
            violations.push('publisher identity is required for signed manifests');
        if (!m.signature)
            violations.push('signature is required: SRI alone proves bytes, not trust');
    }
    for (const cap of m.capabilities ?? []) {
        if (!KNOWN_CAPABILITIES.includes(cap)) {
            violations.push(`Unknown capability declared: ${cap}`);
        }
    }
    for (const api of m.host_apis ?? []) {
        if (!KNOWN_HOST_APIS.includes(api)) {
            violations.push(`Undeclared host API referenced: ${api}`);
        }
    }
    for (const route of m.routes ?? []) {
        if (route.path && !route.path.startsWith('/')) {
            violations.push(`Route path must be absolute: ${route.path}`);
        }
    }
    // [D2] Tier, when declared, must be a known enum value.
    const tier = m.tier;
    if (tier !== undefined &&
        !['official', 'community', 'unsigned-local', 'invalid-signature'].includes(tier)) {
        violations.push(`Unknown trust tier: ${String(tier)}`);
    }
    return violations;
}
