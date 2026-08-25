/**
 * jsdom-free behavioral tests for the remote-extension failure isolation
 * boundary: static lifecycle methods + render() element identity, no DOM.
 *
 * Run: npm run test:docmodel  (tsc → node --test)
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { RemoteErrorBoundary, } from '../../src/components/RemoteErrorBoundary.js';
import { ExtensionLoadError } from '../../src/components/ExtensionLoadError.js';
import { canCallHostApi, hostApisForTier, KNOWN_HOST_APIS, READ_ONLY_HOST_APIS, TRUSTED_HOST_APIS, } from '../../src/types/extension-contract.js';
const PROPS = { children: React.createElement('div', null, 'extension content'), entryUrl: 'https://cdn.example.com/ext.js' };
const CHILD = PROPS.children;
function mountedInstance() {
    const instance = new RemoteErrorBoundary(PROPS);
    assert.equal(instance.state.hasError, false);
    return instance;
}
test('getDerivedStateFromError flags the error state (direct method call)', () => {
    const boom = new Error('remote module evaluation failed');
    const next = RemoteErrorBoundary.getDerivedStateFromError(boom);
    assert.deepEqual(next, { hasError: true, error: boom });
});
test('failure isolation: throwing-child state renders ExtensionLoadError with the failing entryUrl', () => {
    const instance = mountedInstance();
    instance.state = RemoteErrorBoundary.getDerivedStateFromError(new Error('boom'));
    const el = instance.render();
    assert.equal(el.type, ExtensionLoadError);
    assert.equal(el.props.title, 'Failed to Load Extension Module');
    assert.equal(el.props.entryUrl, PROPS.entryUrl);
    assert.match(String(el.props.message), /boom/);
});
test('healthy child passes through untouched', () => {
    const instance = mountedInstance();
    assert.equal(instance.render(), CHILD);
});
const ALL_TIERS = [
    'official',
    'community',
    'unsigned-local',
    'invalid-signature',
];
test('tier policy: unsigned tiers are capped at read-only host APIs', () => {
    for (const tier of ['unsigned-local', 'invalid-signature']) {
        const granted = hostApisForTier(tier);
        for (const api of granted) {
            assert.ok(READ_ONLY_HOST_APIS.includes(api), `${tier} must not grant non-read-only API ${api}`);
        }
        for (const trusted of TRUSTED_HOST_APIS) {
            assert.ok(!granted.includes(trusted), `${tier} must never grant ${trusted}`);
        }
    }
});
test('canCallHostApi denies every name outside the tier allow-list (default-deny)', () => {
    const outside = [
        'runtime.evidence.write',
        'runtime.scenarios.delete',
        'runtime.runs.purge',
        'admin.shell.exec',
        'totally.unknown.api',
    ];
    for (const tier of ALL_TIERS) {
        for (const call of outside) {
            assert.equal(canCallHostApi(tier, call), false, `${tier} granted unknown API ${call}`);
        }
        // Known APIs inside the list are granted; consistency across the surface.
        for (const api of KNOWN_HOST_APIS) {
            assert.equal(canCallHostApi(tier, api), hostApisForTier(tier).includes(api));
        }
    }
});
