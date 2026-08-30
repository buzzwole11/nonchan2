/**
 * What happened, and what can still be done about it (spec sections 6, 9).
 *
 * Deliberately not auto-dismissing on a timer. A card that vanishes while the user is
 * still deciding turns Undo into a reflex test, and the spec's tone is 静かな達成感 rather
 * than urgency. It clears when the next card is acted on, or when dismissed.
 *
 * After a save it also carries the optional tags of section 9. They live here rather than
 * in a sheet of their own because **the save has already happened** — 右スワイプの既定は
 * 「気になる」 and the tags are 任意. One surface saying "saved; you can undo that, or say
 * why" is honest about the order things occurred in; a modal asking for a reason first
 * would make a one-gesture action into a decision.
 */
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import type { SaveReason } from '@papermatch/shared-types';

import { Text } from '../components/Text';
import type { PendingUndo } from './deck';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';
import { OPTIONAL_SAVE_REASONS, isReasonSelected } from './saveReasons';

export interface UndoToastProps {
  pending: PendingUndo;
  locale: 'ja' | 'en';
  onUndo: () => void;
  onDismiss: () => void;
  /** Tags already on the paper, so a chip can show its state. */
  reasons?: readonly SaveReason[];
  /** Absent on a skip, and while the save is still unconfirmed. */
  onToggleReason?: (reason: SaveReason) => void;
}

export function UndoToast({
  pending,
  locale,
  onUndo,
  onDismiss,
  reasons = [],
  onToggleReason,
}: UndoToastProps) {
  const theme = useTheme();
  const t = (key: MessageKey) => translate(locale, key);
  const message =
    pending.actionType === 'save' ? t('discover.savedToast') : t('discover.skippedToast');
  // Undo needs a server-side action to reverse; until the request lands there is nothing
  // to point at, so the control is disabled rather than silently doing nothing.
  const ready = pending.actionId !== null;

  // Only after a save, and only once the server has confirmed it — tagging a paper the
  // server has not accepted yet would send a PATCH for a row that does not exist.
  const showReasons = pending.actionType === 'save' && ready && onToggleReason !== undefined;

  return (
    <View
      accessibilityLiveRegion="polite"
      style={[
        styles.shell,
        {
          backgroundColor: theme.color.card,
          borderColor: theme.color.border,
          borderRadius: theme.radius.tile,
          padding: theme.spacing.md,
          gap: theme.spacing.sm,
        },
      ]}
    >
      <View style={[styles.toast, { gap: theme.spacing.md }]}>
        <View style={styles.message}>
          <Text variant="caption" tone={pending.actionType === 'save' ? 'saved' : 'secondary'}>
            {message}
          </Text>
          <Text variant="caption" tone="secondary" numberOfLines={1}>
            {pending.item.paper.title}
          </Text>
        </View>

        <Pressable
          onPress={onUndo}
          disabled={!ready}
          accessibilityRole="button"
          accessibilityLabel={t('a11y.undoButton')}
          accessibilityState={{ disabled: !ready }}
          hitSlop={8}
          style={{
            minHeight: theme.touchTarget,
            justifyContent: 'center',
            opacity: ready ? 1 : 0.4,
          }}
        >
          <Text variant="label" tone="accent">
            {t('discover.undo')}
          </Text>
        </Pressable>

        <Pressable
          onPress={onDismiss}
          accessibilityRole="button"
          accessibilityLabel={t('common.close')}
          hitSlop={8}
          style={{ minHeight: theme.touchTarget, justifyContent: 'center' }}
        >
          <Text variant="label" tone="secondary">
            ✕
          </Text>
        </Pressable>
      </View>

      {showReasons && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: theme.spacing.xs, paddingRight: theme.spacing.md }}
          accessibilityLabel={t('save.whyLabel')}
        >
          {OPTIONAL_SAVE_REASONS.map((reason) => {
            const on = isReasonSelected(reasons, reason);
            return (
              <Pressable
                key={reason}
                onPress={() => onToggleReason?.(reason)}
                accessibilityRole="button"
                // The state is in the label as well as the border, so a screen reader user
                // and a greyscale screen both get it (spec section 20).
                accessibilityState={{ selected: on }}
                accessibilityLabel={`${t(`saveReason.${reason}` as MessageKey)}${
                  on ? ` — ${t('save.tagOn')}` : ''
                }`}
                hitSlop={6}
                style={{
                  minHeight: theme.touchTarget,
                  justifyContent: 'center',
                  paddingHorizontal: theme.spacing.md,
                  borderRadius: theme.radius.chip,
                  borderWidth: on ? 2 : StyleSheet.hairlineWidth,
                  borderColor: on ? theme.color.accent : theme.color.border,
                  backgroundColor: on ? theme.color.translationSurface : 'transparent',
                }}
              >
                <Text variant="caption" tone={on ? 'accent' : 'secondary'}>
                  {on ? '✓ ' : ''}
                  {t(`saveReason.${reason}` as MessageKey)}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    borderWidth: StyleSheet.hairlineWidth,
  },
  toast: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  message: {
    flex: 1,
    gap: 2,
  },
});
