import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  DEFAULT_VISIBLE_VERIFICATION_STATUSES,
  IDENTIFIER_KINDS,
  VERIFICATION_STATUSES,
  VOCABULARY_TUPLES,
  isVisibleByDefault,
  vocabularies,
} from './vocab.ts';

test('every TypeScript tuple matches enums.json exactly, in order', () => {
  for (const [key, tuple] of Object.entries(VOCABULARY_TUPLES)) {
    const entry = (vocabularies as Record<string, { values?: string[] }>)[key];
    assert.ok(entry?.values, `enums.json has no entry for "${key}"`);
    assert.deepEqual(tuple, entry.values, `"${key}" drifted between vocab.ts and enums.json`);
  }
});

test('enums.json has no vocabulary that TypeScript forgot to expose', () => {
  const jsonKeys = Object.keys(vocabularies).filter((k) => !k.startsWith('$'));
  const tupleKeys = Object.keys(VOCABULARY_TUPLES);
  assert.deepEqual(jsonKeys.sort(), tupleKeys.sort());
});

test('identifier precedence follows spec section 16', () => {
  assert.deepEqual(IDENTIFIER_KINDS, [
    'doi',
    'arxiv',
    'semantic_scholar',
    'openalex',
    'title_author_year',
  ]);
});

test('unverified derivations are hidden by default (spec section 12)', () => {
  assert.equal(isVisibleByDefault('unverified'), false);
  for (const status of VERIFICATION_STATUSES) {
    if (status === 'unverified') continue;
    assert.equal(isVisibleByDefault(status), true, `${status} should be visible by default`);
  }
  assert.equal(DEFAULT_VISIBLE_VERIFICATION_STATUSES.length, VERIFICATION_STATUSES.length - 1);
});
