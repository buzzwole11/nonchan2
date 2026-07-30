import { type Locale, type MessageKey, messages } from './locales';

export { LOCALES, type Locale, type MessageKey } from './locales';

/**
 * Look up a UI string, substituting `{name}` placeholders.
 *
 * Falls back to Japanese and then to the key itself, so a missing translation shows
 * something identifiable rather than an empty label.
 */
export function translate(
  locale: Locale,
  key: MessageKey,
  params: Record<string, string | number> = {},
): string {
  const table = messages[locale] ?? messages.ja;
  const template: string = table[key] ?? messages.ja[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

/** Every key that is missing from a locale — used by the i18n coverage test. */
export function missingKeys(locale: Locale): MessageKey[] {
  const reference = Object.keys(messages.ja) as MessageKey[];
  const table = messages[locale] as Record<string, string>;
  return reference.filter((key) => !(key in table));
}
