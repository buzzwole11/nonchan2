import { LOCALES, missingKeys, translate } from '../src/i18n';

describe('i18n', () => {
  it('has every Japanese key translated in every other locale', () => {
    for (const locale of LOCALES) {
      expect(missingKeys(locale)).toEqual([]);
    }
  });

  it('substitutes placeholders', () => {
    expect(translate('ja', 'status.papersLoaded', { count: 12 })).toContain('12');
    expect(translate('en', 'paper.readingMinutes', { minutes: 4 })).toBe('About 4 min');
  });

  it('leaves an unknown placeholder visible rather than blanking it', () => {
    expect(translate('en', 'status.papersLoaded', {})).toContain('{count}');
  });

  it('falls back to Japanese for a locale that is not configured', () => {
    // @ts-expect-error deliberately passing an unsupported locale
    expect(translate('fr', 'app.name')).toBe('PaperMatch');
  });

  it('exposes provenance labels for every kind, so colour is never the only signal', () => {
    for (const key of [
      'provenance.original',
      'provenance.verifiedStep',
      'provenance.aiExplanation',
      'provenance.assumption',
      'provenance.humanReviewed',
    ] as const) {
      expect(translate('ja', key).length).toBeGreaterThan(0);
      expect(translate('en', key).length).toBeGreaterThan(0);
    }
  });

  it('gives every gesture an accessible button label (spec section 20)', () => {
    for (const key of [
      'a11y.skipButton',
      'a11y.saveButton',
      'a11y.openSourceButton',
      'a11y.undoButton',
    ] as const) {
      expect(translate('ja', key).length).toBeGreaterThan(0);
    }
  });
});
