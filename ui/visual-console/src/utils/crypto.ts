/**
 * ui/visual-console/src/utils/crypto.ts
 * Enterprise Cryptographic Engine for AgentV Visual Console.
 * Native FIPS 202 Keccak / SHA3-256 / SHA3-384 / SHA3-512 Implementation & Multi-Format SRI Verification.
 */

/**
 * Keccak-f[1600] permutation round constants
 */
const RC = new BigUint64Array([
  0x0000000000000001n, 0x0000000000008082n, 0x800000000000808an, 0x8000000080008000n,
  0x000000000000808bn, 0x0000000080000001n, 0x8000000080008081n, 0x8000000000008009n,
  0x000000000000008an, 0x0000000000000088n, 0x0000000080008009n, 0x000000008000000an,
  0x000000008000808bn, 0x800000000000008bn, 0x8000000000008089n, 0x8000000000008003n,
  0x8000000000008002n, 0x8000000000000080n, 0x000000000000800an, 0x800000008000000an,
  0x8000000080008081n, 0x8000000000008080n, 0x0000000080000001n, 0x8000000080008008n,
]);

const RHO = [
  0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14,
];

function rotl64(n: bigint, shift: number): bigint {
  const s = BigInt(shift % 64);
  return ((n << s) | (n >> (64n - s))) & 0xffffffffffffffffn;
}

function keccakF1600(state: BigUint64Array): void {
  const C = new BigUint64Array(5);
  const D = new BigUint64Array(5);
  const B = new BigUint64Array(25);

  for (let round = 0; round < 24; round++) {
    // Theta step
    for (let x = 0; x < 5; x++) {
      C[x] = state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20];
    }
    for (let x = 0; x < 5; x++) {
      D[x] = C[(x + 4) % 5] ^ rotl64(C[(x + 1) % 5], 1);
    }
    for (let i = 0; i < 25; i++) {
      state[i] ^= D[i % 5];
    }

    // Rho and Pi steps
    for (let i = 0; i < 25; i++) {
      B[i] = rotl64(state[i], RHO[i]);
    }
    for (let y = 0; y < 5; y++) {
      for (let x = 0; x < 5; x++) {
        state[y * 5 + x] = B[x * 5 + ((2 * x + 3 * y) % 5)];
      }
    }

    // Chi step
    for (let y = 0; y < 5; y++) {
      const rowStart = y * 5;
      for (let x = 0; x < 5; x++) {
        C[x] = state[rowStart + x];
      }
      for (let x = 0; x < 5; x++) {
        state[rowStart + x] = C[x] ^ (~C[(x + 1) % 5] & C[(x + 2) % 5]);
      }
    }

    // Iota step
    state[0] ^= RC[round];
  }
}

/**
 * Standard NIST FIPS 202 SHA3 Sponge implementation
 */
export function sha3Digest(data: Uint8Array, bits: 256 | 384 | 512 = 256): Uint8Array {
  const rateBytes = (1600 - bits * 2) / 8;
  const state = new BigUint64Array(25);
  const stateBytes = new Uint8Array(state.buffer);

  let offset = 0;
  while (offset + rateBytes <= data.length) {
    for (let i = 0; i < rateBytes; i++) {
      stateBytes[i] ^= data[offset + i];
    }
    keccakF1600(state);
    offset += rateBytes;
  }

  // Padding: SHA3 domain suffix is 0x06 (0110 in binary)
  const remaining = data.length - offset;
  const block = new Uint8Array(rateBytes);
  block.set(data.subarray(offset));
  block[remaining] ^= 0x06;
  block[rateBytes - 1] ^= 0x80;

  for (let i = 0; i < rateBytes; i++) {
    stateBytes[i] ^= block[i];
  }
  keccakF1600(state);

  // Squeeze output
  const outBytes = bits / 8;
  const output = new Uint8Array(outBytes);
  let outOffset = 0;

  while (outOffset < outBytes) {
    const chunk = Math.min(rateBytes, outBytes - outOffset);
    output.set(stateBytes.subarray(0, chunk), outOffset);
    outOffset += chunk;
    if (outOffset < outBytes) {
      keccakF1600(state);
    }
  }

  return output;
}

export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Computes canonical SHA3-256 digest in hex format (`sha3_256:...`)
 */
export function computeSha3_256Hex(data: Uint8Array | string): string {
  const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  return `sha3_256:${bytesToHex(sha3Digest(bytes, 256))}`;
}

/**
 * Computes canonical SHA3-256 SRI string (`sha3-256-<base64>`)
 */
export function computeSha3_256SRI(data: Uint8Array | string): string {
  const bytes = typeof data === 'string' ? new TextEncoder().encode(data) : data;
  return `sha3-256-${bytesToBase64(sha3Digest(bytes, 256))}`;
}

/**
 * Universal Subresource Integrity (SRI) Validator supporting SHA3 and legacy SHA-2 fallback.
 */
export async function verifySubresourceIntegrity(
  buffer: ArrayBuffer,
  sriString: string
): Promise<{ valid: boolean; computed: string; algorithm: string }> {
  const data = new Uint8Array(buffer);
  const cleanSri = sriString.trim();

  // 1. Native FIPS 202 SHA3-256 / SHA3-384 / SHA3-512
  if (cleanSri.startsWith('sha3-256-') || cleanSri.startsWith('sha3_256:')) {
    const hash = sha3Digest(data, 256);
    const b64 = bytesToBase64(hash);
    const hex = bytesToHex(hash);
    const valid = cleanSri.includes(b64) || cleanSri.includes(hex);
    return { valid, computed: `sha3-256-${b64}`, algorithm: 'SHA3-256' };
  }

  if (cleanSri.startsWith('sha3-384-') || cleanSri.startsWith('sha3_384:')) {
    const hash = sha3Digest(data, 384);
    const b64 = bytesToBase64(hash);
    const hex = bytesToHex(hash);
    const valid = cleanSri.includes(b64) || cleanSri.includes(hex);
    return { valid, computed: `sha3-384-${b64}`, algorithm: 'SHA3-384' };
  }

  if (cleanSri.startsWith('sha3-512-') || cleanSri.startsWith('sha3_512:')) {
    const hash = sha3Digest(data, 512);
    const b64 = bytesToBase64(hash);
    const hex = bytesToHex(hash);
    const valid = cleanSri.includes(b64) || cleanSri.includes(hex);
    return { valid, computed: `sha3-512-${b64}`, algorithm: 'SHA3-512' };
  }

  // 2. WebCrypto SHA-2 Fallback (Legacy W3C SRI compatibility)
  let webCryptoAlgo = 'SHA-384';
  let expectedBase64 = cleanSri;
  if (cleanSri.startsWith('sha256-')) {
    webCryptoAlgo = 'SHA-256';
    expectedBase64 = cleanSri.replace('sha256-', '');
  } else if (cleanSri.startsWith('sha384-')) {
    webCryptoAlgo = 'SHA-384';
    expectedBase64 = cleanSri.replace('sha384-', '');
  } else if (cleanSri.startsWith('sha512-')) {
    webCryptoAlgo = 'SHA-512';
    expectedBase64 = cleanSri.replace('sha512-', '');
  }

  const digestBuffer = await window.crypto.subtle.digest(webCryptoAlgo, buffer);
  const computedBase64 = btoa(String.fromCharCode(...new Uint8Array(digestBuffer)));
  const computedSRI = `${webCryptoAlgo.toLowerCase().replace('-', '')}-${computedBase64}`;
  const valid = computedBase64 === expectedBase64 || cleanSri.includes(computedBase64);

  return { valid, computed: computedSRI, algorithm: webCryptoAlgo };
}
