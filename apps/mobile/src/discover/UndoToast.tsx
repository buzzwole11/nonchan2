/**
 * Undo affordance after a swipe (spec section 6: スキップ後にUndo).
 *
 * Deliberately not auto-dismissing on a timer. A card that vanishes while the user is
 * still deciding turns Undo into a reflex test, and the spec's tone is 静かな達成感 rather
 * than urgency. It clears when the next card is acted on, or when dismissed.
 */
import { Pressable, StyleSheet, View } from 'react-native';

import { Text } from '../components/Text';
import type { PendingUndo } from './deck';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

export interface UndoToastProps {
  pending: PendingUndo;
  locale: 'ja' | 'en';
  onUndo: () => void;
  onDismiss: () => void;
}

export function UndoToast({ pending, locale, onUndo, onDismiss }: UndoToastProps) {
  const theme = useTheme();
  const t = (key: MessageKey) => translate(locale, key);
  const message =
    pending.actionType === 'save' ? t('discover.savedToast') : t('discover.skippedToast');
  // Undo needs a server-side action to reverse; until the request lands there is nothing
  // to point at, so the control is disabled rather than silently doing nothing.
  const ready = pending.actionId !== null;

  return (
    <View
      accessibilityLiveRegion="polite"
      style={[
        styles.toast,
        {
          backgroundColor: theme.color.card,
          borderColor: theme.color.border,
          borderRadius: theme.radius.tile,
          padding: theme.spacing.md,
          gap: theme.spacing.md,
        },
      ]}
    >
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
        style={{ minHeight: theme.touchTarget, justifyContent: 'center', opacity: ready ? 1 : 0.4 }}
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
  );
}

const styles = StyleSheet.create({
  toast: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  message: {
    flex: 1,
    gap: 2,
  },
});
