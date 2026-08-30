/**
 * The five feed controls of spec section 16, as a sheet.
 *
 * Section 16's own instruction shapes the whole screen:
 *
 *   否定的フィードバックを「嫌い」と決めつけない。「今回は見送る」として扱う。
 *
 * So the sheet says, in words and before any button, that everything here is undoable and
 * temporary. Each row also states what it will actually do — a control whose effect the
 * reader has to infer from a changing deck is one they cannot consent to.
 *
 * **Nothing here is gesture-only** (spec section 20): every control is a labelled button
 * with a hit target, the sheet closes from a button as well as the system back gesture, and
 * the result is announced in a live region rather than signalled by the deck quietly
 * reordering behind the sheet.
 *
 * **A row that cannot act says why.** Hiding the author of a paper with no named authors
 * would be a button that reports success and changes nothing; the row is disabled instead
 * and carries the reason next to it.
 */
import { Modal, ScrollView, StyleSheet, View } from 'react-native';

import type { FeedItem } from '@papermatch/shared-types';

import { Text } from '../components/Text';
import { PressableRow } from '../components/PressableRow';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';
import {
  FEEDBACK_CONTROLS,
  type FeedbackControl,
  type FeedbackKind,
  firstAuthorName,
  unavailableReason,
} from './feedback';

export type FeedbackStatus =
  | { kind: 'idle' }
  | { kind: 'sending'; control: FeedbackKind }
  | { kind: 'applied'; control: FeedbackKind }
  | { kind: 'failed' };

export interface FeedbackSheetProps {
  visible: boolean;
  locale: 'ja' | 'en';
  item: FeedItem | null;
  status: FeedbackStatus;
  onSend: (control: FeedbackControl) => void;
  onClose: () => void;
}

export function FeedbackSheet({ visible, onClose, ...rest }: FeedbackSheetProps) {
  const theme = useTheme();
  return (
    <Modal
      visible={visible}
      animationType={theme.reduceMotion ? 'fade' : 'slide'}
      transparent
      onRequestClose={onClose}
      // Spec section 20: focus stays inside the sheet rather than wandering back into the
      // card behind it.
      accessibilityViewIsModal
    >
      {visible ? <FeedbackSheetBody onClose={onClose} {...rest} /> : null}
    </Modal>
  );
}

type BodyProps = Omit<FeedbackSheetProps, 'visible'>;

function FeedbackSheetBody({ locale, item, status, onSend, onClose }: BodyProps) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const author = firstAuthorName(item);
  // The sheet covers the card, so anything a row acts on has to be named in the row. The
  // field id is what the card itself shows on its chip, so the two agree.
  const field = item?.paper.primaryFieldId ?? '';
  const notice =
    status.kind === 'failed'
      ? t('feedback.failed')
      : status.kind === 'applied'
        ? t('feedback.applied')
        : null;

  return (
    <View style={styles.backdrop}>
      <View
        style={[
          styles.sheet,
          {
            backgroundColor: theme.color.card,
            borderTopLeftRadius: theme.radius.card,
            borderTopRightRadius: theme.radius.card,
            padding: theme.spacing.screenHorizontal,
            gap: theme.spacing.sm,
          },
        ]}
      >
        <Text variant="label" accessibilityRole="header">
          {t('feedback.title')}
        </Text>
        {/* Said once, up front, and not only in the per-row hints: this is the sentence
            that keeps the whole sheet on the 「今回は見送る」 side of section 16. */}
        <Text variant="caption" tone="secondary">
          {t('feedback.intro')}
        </Text>

        {notice !== null && (
          <Text
            variant="caption"
            tone={status.kind === 'failed' ? 'warning' : 'saved'}
            accessibilityLiveRegion="polite"
          >
            {notice}
          </Text>
        )}

        <ScrollView style={styles.list} contentContainerStyle={{ gap: theme.spacing.xs }}>
          {FEEDBACK_CONTROLS.map((control) => {
            const blocked = unavailableReason(control, item);
            const busy = status.kind === 'sending' && status.control === control.kind;
            const hint =
              blocked !== null ? t(blocked) : t(control.hintKey, { author: author ?? '', field });
            return (
              <PressableRow
                key={control.kind}
                onPress={() => onSend(control)}
                disabled={blocked !== null || busy}
                // The hint is part of the label rather than a separate hint prop: a screen
                // reader user choosing between five similar controls needs the consequence
                // in the same breath as the name, not on a second pass.
                accessibilityLabel={`${t(control.labelKey)}. ${hint}`}
              >
                <View style={{ gap: 2 }}>
                  <Text tone={blocked !== null ? 'secondary' : 'primary'}>
                    {t(control.labelKey)}
                  </Text>
                  {/* Never colour alone (spec section 20): the state is written out. */}
                  <Text variant="caption" tone={blocked !== null ? 'warning' : 'secondary'}>
                    {hint}
                  </Text>
                </View>
              </PressableRow>
            );
          })}
        </ScrollView>

        <PressableRow onPress={onClose} accessibilityLabel={t('feedback.close')}>
          <Text tone="accent">{t('feedback.close')}</Text>
        </PressableRow>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(0,0,0,0.35)',
  },
  sheet: {
    maxHeight: '80%',
  },
  list: {
    flexGrow: 0,
  },
});
