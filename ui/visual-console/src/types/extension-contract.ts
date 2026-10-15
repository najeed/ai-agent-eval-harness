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
  'header',
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

/**
 * [D2] Extension trust tier.
 *   - 'official': signature verifies against the runtime trust root AND the
 *     publisher identity is the platform's own.
 *   - 'community': third-party signature verified against a trust-root key.
 *   - 'local' / 'unsigned-local': no verifiable signature — restricted to
 *     READ-ONLY host APIs.
 */
export type ExtensionTier = 'official' | 'community' | 'unsigned-local' | 'invalid-signature';

/**
 * [D2] Host APIs that only READ host state. These are the ONLY APIs granted
 * to unsigned/local extensions. Any future mutating host API MUST NOT be
 * added here.
 */
export const READ_ONLY_HOST_APIS: readonly HostApiName[] = [
  'runtime.health.get',
  'runtime.runs.list',
  'runtime.runs.get',
  'runtime.scenarios.list',
  'runtime.evidence.link',
];

/** Host APIs reserved for trusted tiers (must be non-read-only calls). */
export const TRUSTED_HOST_APIS: readonly HostApiName[] = [];

/** [D2] Tier-based host API access policy. */
export function hostApisForTier(tier: ExtensionTier): readonly HostApiName[] {
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
export function canCallHostApi(
  tier: ExtensionTier,
  call: string,
  manifest?: { host_apis?: readonly string[] | string[] }
): boolean {
  if (manifest?.host_apis && Array.isArray(manifest.host_apis)) {
    if (!manifest.host_apis.includes(call)) return false;
  }
  return (hostApisForTier(tier) as readonly string[]).includes(call);
}


export interface ExtensionRoute {
  path: string;
  label?: string;
  required_permissions?: string[];
}

/** Signed, presentation-only metadata keyed to one declared route. */
export interface ExtensionNavigation {
  path: string;
  id?: string;
  title?: string;
  icon?: string;
  group?: string;
  badge?: string;
  provenance?: string;
}

/** The only authenticated context surface supplied to mounted extensions. */
export interface ExtensionRuntimeContextApi {
  context: import('../auth/runtimeAuthContext.js').RuntimeAuthContext;
  switchContext(workspaceId: string, activeEnvironment: string): Promise<void>;
  authorizedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

export interface ExtensionPageHostApi extends ExtensionRuntimeContextApi {
  route: ExtensionRoute;
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
  navigation: ExtensionNavigation[];
  nav_group: string;
  remote_entry: string;
  sri_hash: string;
  /** Signed integrity map for every relative ESM chunk imported by remote_entry. */
  verified_chunks?: Record<string, string>;
  /** ABI assertion: React is a host peer, never bundled into the extension. */
  react_peer?: boolean;
  publisher: string;
  signature: string;
  lifecycle: ExtensionLifecycle;
  host_apis: string[];
  /** Optional generic visual contribution point. */
  slot?: 'header';
  /** [D2] Declared trust tier (verified server-side; advisory client-side). */
  tier?: ExtensionTier | null;
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
  if (!m.api_version) violations.push('api_version is required');
  const remoteEntry = (m as any).remote_entry ?? (m as any).remoteEntry;
  const sriHash = (m as any).sri_hash ?? (m as any).sriHash;
  if (!remoteEntry) violations.push('remote_entry is required');
  if (!sriHash) violations.push('sri_hash (integrity digest) is required');

  try {
    parseSemver(m.version ?? '');
  } catch {
    violations.push(`version must be SemVer: ${String(m.version)}`);
  }

  if (m.api_version) {
    try {
      parseSemver(m.api_version);
      if (!isCompatible(m.api_version, EXTENSION_CONTRACT_VERSION)) {
        violations.push(
          `api_version ${m.api_version} is incompatible with host contract ${EXTENSION_CONTRACT_VERSION}`
        );
      }
    } catch {
      violations.push(`api_version must be SemVer: ${String(m.api_version)}`);
    }
  }

  if (requireSignature) {
    if (!m.publisher) violations.push('publisher identity is required for signed manifests');
    if (!m.signature)
      violations.push('signature is required: SRI alone proves bytes, not trust');
  }

  const caps = m.capabilities ?? [];
  if (!Array.isArray(caps)) {
    violations.push('capabilities must be an array');
  } else {
    for (const cap of caps) {
      if (!(KNOWN_CAPABILITIES as readonly string[]).includes(cap as any)) {
        violations.push(`Unknown capability declared: ${cap}`);
      }
    }
  }

  for (const api of m.host_apis ?? []) {
    if (!(KNOWN_HOST_APIS as readonly string[]).includes(api as any)) {
      violations.push(`Undeclared host API referenced: ${api}`);
    }
  }
  if (m.verified_chunks !== undefined) {
    if (typeof m.verified_chunks !== 'object' || Array.isArray(m.verified_chunks)) {
      violations.push('verified_chunks must be an object mapping chunk URL to SRI digest');
    } else if (Object.entries(m.verified_chunks).some(([url, digest]) => !url || url.startsWith('/') || url.split('/').includes('..') || typeof digest !== 'string' || !digest.startsWith('sha3-256-'))) {
      violations.push('verified_chunks entries require safe relative paths and sha3-256 SRI digests');
    }
  }
  if (m.slot !== undefined && m.slot !== 'header') violations.push(`Unknown extension slot: ${String(m.slot)}`);
  if (m.slot === 'header' && !caps.includes('header')) violations.push('Header slot requires the "header" capability');
  if (m.react_peer !== undefined && typeof m.react_peer !== 'boolean') violations.push('react_peer must be a boolean');

  const routes = m.routes ?? [];
  if (routes.length > 0 && !caps.includes('routes') && !caps.includes('navigation')) {
    violations.push('Manifest declares routes but does not declare "routes" or "navigation" capability');
  }

  const routePaths = new Set<string>();
  for (const route of routes) {
    if (!route.path || !route.path.startsWith('/')) {
      violations.push(`Route path must be non-empty and absolute: ${String(route.path)}`);
    }
    if (routePaths.has(route.path)) violations.push(`Duplicate route path: ${route.path}`);
    routePaths.add(route.path);
    if (route.label !== undefined && typeof route.label !== 'string') violations.push(`Route label must be a string when supplied: ${route.path}`);
    if (route.required_permissions !== undefined && (!Array.isArray(route.required_permissions) || route.required_permissions.some(permission => typeof permission !== 'string' || !permission))) {
      violations.push(`Route permissions must be non-empty strings: ${route.path}`);
    }
  }

  const navigation = m.navigation ?? [];
  if (!Array.isArray(navigation)) {
    violations.push('navigation must be an array');
  } else {
    const navigationPaths = new Set<string>();
    const navigationIds = new Set<string>();
    for (const item of navigation) {
      if (!item || typeof item !== 'object' || typeof item.path !== 'string' || !routePaths.has(item.path)) {
        violations.push(`Navigation path must name a declared route: ${String((item as any)?.path)}`);
        continue;
      }
      if (navigationPaths.has(item.path)) violations.push(`Duplicate navigation path: ${item.path}`);
      navigationPaths.add(item.path);
      if (item.id !== undefined) {
        if (typeof item.id !== 'string' || !item.id) violations.push(`Navigation id must be a non-empty string: ${item.path}`);
        else if (navigationIds.has(item.id)) violations.push(`Duplicate navigation id: ${item.id}`);
        navigationIds.add(item.id);
      }
      for (const field of ['title', 'group', 'badge', 'provenance'] as const) {
        if (item[field] !== undefined && typeof item[field] !== 'string') {
          violations.push(`Navigation ${field} must be a string when supplied: ${item.path}`);
        }
      }
      if (item.icon !== undefined && (typeof item.icon !== 'string' || !item.icon)) {
        violations.push(`Navigation icon must be a non-empty string when supplied: ${item.path}`);
      }
    }
  }

  // [D2] Tier, when declared, must be a known enum value.
  const tier = (m as any).tier;
  if (
    tier !== undefined &&
    tier !== null &&
    !['official', 'community', 'unsigned-local', 'invalid-signature'].includes(tier)
  ) {
    violations.push(`Unknown trust tier: ${String(tier)}`);
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

/**
 * Normalized Console Extension Inventory contract.
 * Represents a canonical extension capability/version without duplicate rows
 * caused by navigation registration details, and explicitly defines the
 * relationship when a signed remote extension supersedes or wraps a
 * server-registered component.
 */
export interface ExtensionInventoryItem {
  extensionId: string;
  publisher?: string;
  version?: string;
  capabilityId: string;
  registrationKind: 'remote_extension' | 'server_component';
  remoteEntry?: string;
  componentName?: string;
  trustTier?: string;
  sriHash?: string;
  relatedRegistrationIds?: string[];
}

/**
 * Normalizes and de-duplicates raw navigation and extension items into canonical
 * ExtensionInventoryItem records.
 *
 * Rules:
 * 1. Produces exactly one canonical inventory item per extension capability/version.
 * 2. When a signed remote extension supersedes or wraps a server-registered component,
 *    it exposes that relationship (with both remoteEntry and componentName preserved)
 *    and sets registrationKind to 'remote_extension'.
 * 3. Distinct capabilities remain separately visible.
 * 4. Generates stable extension/capability identities independent of labels or routes.
 * 5. Tags kind as 'remote_extension' or 'server_component' (never 'host').
 */
export function buildExtensionInventory(items: unknown[]): ExtensionInventoryItem[] {
  if (!Array.isArray(items)) return [];

  const candidates = items.filter((item): item is Record<string, any> => {
    if (!item || typeof item !== 'object') return false;
    const it = item as Record<string, any>;
    return (
      typeof it.remoteEntry === 'string' ||
      typeof it.componentName === 'string' ||
      it.type === 'component' ||
      it.registrationKind === 'remote_extension' ||
      it.registrationKind === 'server_component' ||
      (typeof it.extensionId === 'string' && it.extensionId.length > 0)
    );
  });

  // Group items by normalized capability identity
  const capabilityGroups = new Map<string, Record<string, any>[]>();

  for (const item of candidates) {
    const rawCap =
      item.capabilityId ||
      item.capability ||
      item.extensionId ||
      item.componentName ||
      (typeof item.id === 'string'
        ? item.id.replace(/-nav$|-component$|-remote$|-ext$/, '')
        : '') ||
      item.name ||
      'unknown';
    const capId = String(rawCap).trim().toLowerCase();

    if (!capabilityGroups.has(capId)) {
      capabilityGroups.set(capId, []);
    }
    capabilityGroups.get(capId)!.push(item);
  }

  const inventory: ExtensionInventoryItem[] = [];

  for (const [capIdKey, groupItems] of capabilityGroups.entries()) {
    // Check if there are multiple distinct non-empty versions among remote extensions
    const remoteVersions = Array.from(
      new Set(
        groupItems
          .filter(it => Boolean(it.remoteEntry))
          .map(it => (typeof it.version === 'string' ? it.version.trim() : ''))
          .filter(Boolean)
      )
    );

    const versionSubgroups: Record<string, any>[][] =
      remoteVersions.length > 1
        ? remoteVersions.map(v =>
            groupItems.filter(it => !it.version || it.version === v)
          )
        : [groupItems];

    for (const items of versionSubgroups) {
      // Identify remote extension registration vs server component registration
      const remoteItem = items.find(
        it => typeof it.remoteEntry === 'string' || it.registrationKind === 'remote_extension'
      );
      const componentItem = items.find(
        it => typeof it.componentName === 'string' || it.type === 'component' || it.registrationKind === 'server_component'
      );

      const primary = remoteItem || items[0];
      const isRemote = Boolean(remoteItem && remoteItem.remoteEntry);

      // Collect all unique registration IDs involved in this capability group
      const relatedIds = new Set<string>();
      for (const it of items) {
        if (typeof it.id === 'string' && it.id) {
          relatedIds.add(it.id);
        }
        if (Array.isArray(it.relatedRegistrationIds)) {
          for (const rel of it.relatedRegistrationIds) {
            if (typeof rel === 'string' && rel) {
              relatedIds.add(rel);
            }
          }
        }
      }

      const stableCapabilityId =
        primary.capabilityId ||
        (componentItem ? componentItem.capabilityId : undefined) ||
        primary.capability ||
        capIdKey;

      const stableExtensionId =
        primary.extensionId ||
        (remoteItem ? remoteItem.extensionId : undefined) ||
        (componentItem ? componentItem.extensionId : undefined) ||
        stableCapabilityId;

      const item: ExtensionInventoryItem = {
        extensionId: String(stableExtensionId),
        capabilityId: String(stableCapabilityId),
        registrationKind: isRemote ? 'remote_extension' : 'server_component',
      };

      if (primary.publisher || (componentItem && componentItem.publisher)) {
        item.publisher = primary.publisher || (componentItem ? componentItem.publisher : undefined);
      }

      if (primary.version || (componentItem && componentItem.version)) {
        item.version = primary.version || (componentItem ? componentItem.version : undefined);
      }

      if (isRemote && remoteItem?.remoteEntry) {
        item.remoteEntry = remoteItem.remoteEntry;
        if (remoteItem.sriHash || remoteItem.sri_hash) {
          item.sriHash = remoteItem.sriHash || remoteItem.sri_hash;
        }
      }

      // Preserve componentName if present in group (even when remote supersedes it)
      const compName =
        (componentItem && typeof componentItem.componentName === 'string')
          ? componentItem.componentName
          : typeof primary.componentName === 'string'
          ? primary.componentName
          : undefined;

      if (compName) {
        item.componentName = compName;
      }

      const tier =
        primary.trustTier ||
        primary.tier ||
        (componentItem ? componentItem.trustTier || componentItem.tier : undefined);
      if (tier) {
        item.trustTier = String(tier);
      }

      if (relatedIds.size > 0) {
        item.relatedRegistrationIds = Array.from(relatedIds);
      }

      inventory.push(item);
    }
  }

  return inventory;
}
