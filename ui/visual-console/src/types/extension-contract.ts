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
] as const;

export const KNOWN_HOST_APIS = [
  'runtime.health.get',
  'runtime.runs.list',
  'runtime.runs.get',
  'runtime.scenarios.list',
  'runtime.evidence.link',
] as const;

export type ExtensionCapability = (typeof KNOWN_CAPABILITIES)[number];
export type HostApiName = (typeof KNOWN_HOST_APIS)[number];

export interface ExtensionRoute {
  path: string;
  label: string;
  icon?: string;
  required_role?: string;
}

export interface ExtensionLifecycle {
  on_mount?: string;
  on_unmount?: string;
  on_error?: string;
}

export interface RuntimeExtensionManifest {
  extension_id: string;
  display_name: string;
  /** SemVer of the extension itself */
  version: string;
  api_version: string;
  compatibility_version: string;
  compatible_runtime_versions: string[];
  capabilities: string[];
  required_permissions: string[];
  routes: ExtensionRoute[];
  nav_group: string;
  remote_entry: string;
  sri_hash: string;
  publisher: string;
  signature: string;
  lifecycle: ExtensionLifecycle;
  host_apis: string[];
}

export function parseSemver(version: string): [number, number, number] {
  const core = version.trim().replace(/^v/, '').split('-')[0].split('.');
  if (core.length < 2) throw new Error(`Not a SemVer core: ${version}`);
  return [Number(core[0]), Number(core[1]), Number(core[2] ?? 0)];
}

/** Same major; manifest minor must not exceed host minor. */
export function isCompatible(manifestApiVersion: string, hostApiVersion: string): boolean {
  try {
    const [mj, mn] = parseSemver(manifestApiVersion);
    const [hmj, hmn] = parseSemver(hostApiVersion);
    return mj === hmj && mn <= hmn;
  } catch {
    return false;
  }
}

/**
 * Validates a manifest object against the contract.
 * @returns list of violations; empty means valid.
 */
export function validateExtensionManifest(
  manifest: unknown,
  opts: { requireSignature?: boolean } = {}
): string[] {
  const { requireSignature = true } = opts;
  const violations: string[] = [];
  if (!manifest || typeof manifest !== 'object') {
    return ['Manifest is missing or not an object'];
  }
  const m = manifest as Partial<RuntimeExtensionManifest>;
  if (!m.extension_id) violations.push('extension_id is required');
  if (!m.display_name) violations.push('display_name is required');
  if (!m.version) violations.push('version is required');
  const remoteEntry = (m as any).remote_entry ?? (m as any).remoteEntry;
  const sriHash = (m as any).sri_hash ?? (m as any).sriHash;
  if (!remoteEntry) violations.push('remote_entry is required');
  if (!sriHash) violations.push('sri_hash (integrity digest) is required');

  try {
    parseSemver(m.version ?? '');
  } catch {
    violations.push(`version must be SemVer: ${String(m.version)}`);
  }

  if (
    m.api_version &&
    !isCompatible(m.api_version, EXTENSION_CONTRACT_VERSION)
  ) {
    violations.push(
      `api_version ${m.api_version} is incompatible with host contract ${EXTENSION_CONTRACT_VERSION}`
    );
  }

  if (requireSignature) {
    if (!m.publisher) violations.push('publisher identity is required for signed manifests');
    if (!m.signature)
      violations.push('signature is required: SRI alone proves bytes, not trust');
  }

  for (const cap of m.capabilities ?? []) {
    if (!(KNOWN_CAPABILITIES as readonly string[]).includes(cap)) {
      violations.push(`Unknown capability declared: ${cap}`);
    }
  }
  for (const api of m.host_apis ?? []) {
    if (!(KNOWN_HOST_APIS as readonly string[]).includes(api)) {
      violations.push(`Undeclared host API referenced: ${api}`);
    }
  }
  for (const route of m.routes ?? []) {
    if (route.path && !route.path.startsWith('/')) {
      violations.push(`Route path must be absolute: ${route.path}`);
    }
  }
  return violations;
}

/** Shape accepted from the loaded ESM module. */
export interface RuntimeExtensionModule {
  manifest?: RuntimeExtensionManifest | Record<string, unknown>;
  /** Default export may be the mount component; validated separately. */
  default?: unknown;
  [key: string]: unknown;
}
