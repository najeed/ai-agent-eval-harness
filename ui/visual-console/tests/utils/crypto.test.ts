import assert from 'node:assert/strict';
import test from 'node:test';

import { bytesToHex, sha3Digest, verifySubresourceIntegrity } from '../../src/utils/crypto.js';

test('SHA3 implements NIST FIPS 202 vectors', () => {
  const encoder = new TextEncoder();
  assert.equal(bytesToHex(sha3Digest(new Uint8Array(), 256)), 'a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a');
  assert.equal(bytesToHex(sha3Digest(encoder.encode('abc'), 256)), '3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532');
  assert.equal(bytesToHex(sha3Digest(new Uint8Array(), 384)), '0c63a75b845e4f7d01107d852e4c2485c51a50aaaa94fc61995e71bbee983a2ac3713831264adb47fb6bd1e058d5f004');
  assert.equal(bytesToHex(sha3Digest(new Uint8Array(), 512)), 'a69f73cca23a9ac5c8b567dc185a756e97c982164fe25859e0d1dcc1475c80a615b2123af1f5f94c11e3e9402c3ac558f500199d95b6d3e301758586281dcd26');
});

test('SHA3 SRI accepts unchanged bytes and rejects a one-byte mutation', async () => {
  const bytes = new TextEncoder().encode('published extension entry');
  const sri = 'sha3-256-' + btoa(String.fromCharCode(...sha3Digest(bytes, 256)));
  assert.equal((await verifySubresourceIntegrity(bytes.buffer, sri)).valid, true);
  bytes[0] ^= 1;
  assert.equal((await verifySubresourceIntegrity(bytes.buffer, sri)).valid, false);
});
