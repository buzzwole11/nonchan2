/**
 * "This looks wrong" (spec sections 12, 27).
 *
 * The app labels which parts of a maths card came from a model rather than the paper, and
 * section 12 requires AI説明は数式的真偽を保証しないことを明示する. Saying so and then giving
 * the reader nowhere to disagree is half a promise: the label admits the content might be
 * wrong, and the reader who finds that it is has to close the app.
 *
 * Two things the wording has to get right, because both are easy to fake.
 *
 * **It does not promise a reply.** Nobody reviews the queue in this build. "確認します" would
 * be a promise the app cannot keep, so the confirmation says what actually happened — the
 * report was recorded — and nothing more.
 *
 * **It does not claim the content changed.** A report does not hide the card or move its
 * verification status. The sheet says so up front, because a reader who believed a report
 * fixed something would stop checking.
 */
import { useState } from 'react';
import { Modal, ScrollView, StyleSheet, TextInput, View } from 'react-native';

import { REPORT_REASONS, type ReportReason } from '@papermatch/shared-types';

import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

/** Mirrors the server's limit; a report is a pointer, not a discussion. */
export const MAX_REPORT_NOTE = 500;

export type ReportStatus =
  | { kind: 'idle' }
  | { kind: 'sending' }
  | { kind: 'recorded'; already: boolean }
  | { kind: 'failed' };

export interface ReportSheetProps {
  visible: boolean;
  locale: 'ja' | 'en';
  status: ReportStatus;
  /** Set when the reader opened this from one derivation step rather than the card. */
  stepIndex?: number | null;
  onSend: (reason: ReportReason, note: string) => void;
  onClose: () => void;
}

export function ReportSheet({
  visible,
  locale,
  status,
  stepIndex = null,
  onSend,
  onClose,
}: ReportSheetProps) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);
  const [note, setNote] = useState('');

  const outcome =
    status.kind === 'recorded'
      ? status.already
        ? t('report.alreadyRecorded')
        : t('report.recorded')
      : status.kind === 'failed'
        ? t('report.failed')
        : null;

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
            maxHeight: '85%',
          }}
        >
          <View style={styles.header}>
            <Text variant="label" accessibilityRole="header">
              {stepIndex === null
                ? t('report.title')
                : t('report.titleStep', { number: stepIndex + 1 })}
            </Text>
            <PressableRow onPress={onClose} accessibilityLabel={t('common.close')}>
              <Text variant="label" tone="accent">
                {t('common.close')}
              </Text>
            </PressableRow>
          </View>

          {/* Said before anything is picked, not after. A reader who believed a report
              fixed something would stop checking. */}
          <Text variant="caption" tone="secondary">
            {t('report.intro')}
          </Text>

          {outcome !== null && (
            <Text
              variant="caption"
              tone={status.kind === 'failed' ? 'warning' : 'saved'}
              accessibilityLiveRegion="polite"
            >
              {outcome}
            </Text>
          )}

          <ScrollView contentContainerStyle={{ gap: theme.spacing.xs }}>
            {REPORT_REASONS.map((reason) => (
              <PressableRow
                key={reason}
                onPress={() => onSend(reason, note)}
                disabled={status.kind === 'sending'}
                accessibilityLabel={t(`report.reason.${reason}` as MessageKey)}
                style={{
                  borderWidth: StyleSheet.hairlineWidth,
                  borderColor: theme.color.border,
                  borderRadius: theme.radius.tile,
                  paddingHorizontal: theme.spacing.md,
                  paddingVertical: theme.spacing.sm,
                }}
              >
                <Text variant="body">{t(`report.reason.${reason}` as MessageKey)}</Text>
              </PressableRow>
            ))}

            <Text variant="caption" tone="secondary" style={{ marginTop: theme.spacing.sm }}>
              {t('report.noteLabel')}
            </Text>
            <TextInput
              value={note}
              onChangeText={setNote}
              multiline
              maxLength={MAX_REPORT_NOTE}
              accessibilityLabel={t('report.noteLabel')}
              placeholder={t('report.notePlaceholder')}
              placeholderTextColor={theme.color.textSecondary}
              style={{
                minHeight: theme.touchTarget * 2,
                borderWidth: StyleSheet.hairlineWidth,
                borderColor: theme.color.border,
                borderRadius: theme.radius.tile,
                padding: theme.spacing.sm,
                color: theme.color.textPrimary,
                textAlignVertical: 'top',
              }}
            />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
});
