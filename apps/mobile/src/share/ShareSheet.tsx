/**
 * Choosing what goes into a shared image (spec sections 15, 21).
 *
 * Section 15 asks for the title, authors, year and notes to be individually selectable.
 * The switches here are ordinary toggles with one asymmetry: **the private ones start
 * off**, and the sheet says plainly what is currently not in the picture.
 *
 * The preview is the actual card that would be exported, not an approximation of it. A
 * preview that differed from the export would be the worst possible place for a mismatch —
 * the reader checks the preview precisely because the export is irreversible.
 */
import * as Clipboard from 'expo-clipboard';
import { useState } from 'react';
import { Modal, ScrollView, StyleSheet, View } from 'react-native';

import type { Paper, SavedPaper } from '@papermatch/shared-types';

import { buildShareCard, shareCardSvg, type ShareCardOptions } from './shareCard';
import { Chip } from '../components/Chip';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

export interface ShareSheetProps {
  visible: boolean;
  paper: Paper;
  saved: SavedPaper | null;
  locale: 'ja' | 'en';
  onClose: () => void;
  /** Injectable for tests; the real one touches the system clipboard. */
  copy?: (text: string) => Promise<boolean>;
}

const OMITTED_LABEL: Record<'notes' | 'reasons', MessageKey> = {
  notes: 'share.omitted.notes',
  reasons: 'share.omitted.reasons',
};

export function ShareSheet({
  visible,
  paper,
  saved,
  locale,
  onClose,
  copy = Clipboard.setStringAsync,
}: ShareSheetProps) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const [options, setOptions] = useState<ShareCardOptions>({});
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const card = buildShareCard(paper, saved, options);
  // No theme override: the exported card uses the light scheme whatever the reader's own
  // scheme is, because the image is looked at somewhere else. The preview below follows
  // the app's theme, since that one is on this screen.
  const svg = shareCardSvg(card);

  function toggle(key: keyof ShareCardOptions, fallback: boolean): void {
    setOptions((current) => ({ ...current, [key]: !(current[key] ?? fallback) }));
    setCopyState('idle');
  }

  async function exportSvg(): Promise<void> {
    try {
      setCopyState((await copy(svg)) ? 'copied' : 'failed');
    } catch {
      setCopyState('failed');
    }
  }

  const toggles: { key: keyof ShareCardOptions; label: MessageKey; fallback: boolean }[] = [
    { key: 'includeTitle', label: 'share.title', fallback: true },
    { key: 'includeAuthors', label: 'share.authors', fallback: true },
    { key: 'includeYear', label: 'share.year', fallback: true },
    { key: 'includeVenue', label: 'share.venue', fallback: true },
    // The two private ones, last and off by default.
    { key: 'includeNotes', label: 'share.notes', fallback: false },
    { key: 'includeReasons', label: 'share.reasons', fallback: false },
  ];

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View
          style={{
            backgroundColor: theme.color.card,
            borderTopLeftRadius: theme.radius.sheet,
            borderTopRightRadius: theme.radius.sheet,
            padding: theme.spacing.lg,
            gap: theme.spacing.sm,
            maxHeight: '88%',
          }}
        >
          <View style={styles.header}>
            <Text variant="label" accessibilityRole="header">
              {t('share.heading')}
            </Text>
            <PressableRow onPress={onClose} accessibilityLabel={t('common.close')}>
              <Text variant="label" tone="accent">
                {t('common.close')}
              </Text>
            </PressableRow>
          </View>

          <ScrollView contentContainerStyle={{ gap: theme.spacing.sm }}>
            {/* Stated before the switches, not after: the reader should know the rule
                before they start turning things on. */}
            <Text variant="caption" tone="secondary">
              {t('share.private')}
            </Text>

            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
              {toggles.map(({ key, label, fallback }) => (
                <Chip
                  key={key}
                  label={t(label)}
                  selected={options[key] ?? fallback}
                  tone="accent"
                  onPress={() => toggle(key, fallback)}
                  accessibilityLabel={t(label)}
                />
              ))}
            </View>

            {/* Named rather than implied. A reader cannot check for the absence of
                something they have not been told about. */}
            {card.omitted.length > 0 && (
              <Text variant="caption" tone="secondary" accessibilityLiveRegion="polite">
                {t('share.omitted', {
                  fields: card.omitted.map((field) => t(OMITTED_LABEL[field])).join('、'),
                })}
              </Text>
            )}

            {/* The preview is the exported card's own fields, so it cannot drift from it. */}
            <View
              style={{
                borderWidth: StyleSheet.hairlineWidth,
                borderColor: theme.color.border,
                borderLeftWidth: 4,
                borderLeftColor: theme.color.accent,
                borderRadius: theme.radius.tile,
                padding: theme.spacing.md,
                gap: theme.spacing.xs,
              }}
              accessibilityLabel={t('share.preview')}
            >
              {card.title !== null && <Text variant="body">{card.title}</Text>}
              {(card.authors !== null || card.year !== null || card.venue !== null) && (
                <Text variant="caption" tone="secondary">
                  {[card.authors, card.venue, card.year === null ? null : String(card.year)]
                    .filter((value) => value !== null && value !== '')
                    .join(' · ')}
                </Text>
              )}
              {card.reasons !== null && (
                <Text variant="caption" tone="accent">
                  {card.reasons
                    .map((reason) => t(`saveReason.${reason}` as MessageKey))
                    .join(' · ')}
                </Text>
              )}
              {card.notes !== null && <Text variant="caption">{card.notes}</Text>}
              <Text variant="caption" tone="secondary">
                {card.sourceUrl} · {card.licenseId ?? t('share.unknownLicense')}
              </Text>
            </View>

            <PressableRow onPress={() => void exportSvg()} accessibilityLabel={t('share.export')}>
              <Text variant="body" tone="accent">
                {t('share.export')}
              </Text>
            </PressableRow>

            {copyState !== 'idle' && (
              <Text
                variant="caption"
                tone={copyState === 'copied' ? 'saved' : 'warning'}
                accessibilityLiveRegion="polite"
              >
                {t(copyState === 'copied' ? 'share.exported' : 'share.exportFailed')}
              </Text>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
});
