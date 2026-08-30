/**
 * Partial-translation bottom sheet (spec section 7).
 *
 * The selected English stays pinned at the top and is never replaced — the translation is
 * scaffolding under the original, not a substitute for it (spec section 3: Original
 * first). The staged hints from section 7 are tabs; Phase 2 fills in the richer content
 * behind them, but the staging itself is here so the reading habit it is meant to build
 * starts now.
 *
 * Two states matter and are both shown in words: a translation that fell back to the
 * original because a formula could not be preserved, and a refusal because the paper's
 * terms do not permit sending its text to a provider.
 */
import { useMutation } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Modal, ScrollView, StyleSheet, View } from 'react-native';

import type { TranslationStage } from '@papermatch/shared-types';

import { ApiError, NetworkError } from '../api/client';
import { useSession } from '../api/session';
import { Chip } from '../components/Chip';
import { PressableRow } from '../components/PressableRow';
import { Text } from '../components/Text';
import { type MessageKey, translate } from '../i18n';
import { useTheme } from '../theme/ThemeProvider';

/** Spec section 7: 段階的ヒント, in the order the section lists them. */
export const STAGES: TranslationStage[] = [
  'hard_words',
  'sentence_skeleton',
  'phrase_structure',
  'literal',
  'natural',
  'domain_meaning',
];

export interface TranslationSheetProps {
  visible: boolean;
  locale: 'ja' | 'en';
  paperId: string;
  selection: { start: number; end: number; exactText: string } | null;
  initialStage: TranslationStage;
  onClose: () => void;
}

type SheetState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; translated: string; fellBack: boolean; notice: string | null }
  | { kind: 'error'; messageKey: MessageKey };

/** Result of the "save expression" action, shown as a sentence rather than a toast. */
type SaveState = { kind: 'idle' } | { kind: 'saving' } | { kind: 'done'; messageKey: MessageKey };

/** Map the API's error codes onto sentences the reader can act on. */
function errorMessageKey(error: unknown): MessageKey {
  if (error instanceof NetworkError) return 'status.api.offline';
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'selection_splits_formula':
        return 'translate.splitsFormula';
      case 'selection_too_long':
        return 'translate.tooLong';
      case 'abstract_not_redistributable':
        return 'translate.notRedistributable';
      default:
        return 'translate.failed';
    }
  }
  return 'translate.failed';
}

/**
 * The sheet shell. Everything with state lives in the body below, which is mounted only
 * while the sheet is open.
 *
 * The body used to stay mounted and reset itself in an effect when `visible` went false.
 * Unmounting is the same reset without the window: a sheet reopened on a new selection
 * cannot show the previous selection's translation for a frame while the new request is
 * still in flight.
 */
export function TranslationSheet({ visible, onClose, ...rest }: TranslationSheetProps) {
  const theme = useTheme();
  return (
    <Modal
      visible={visible}
      animationType={theme.reduceMotion ? 'fade' : 'slide'}
      transparent
      onRequestClose={onClose}
      // Spec section 20: the sheet traps focus so a screen reader does not wander back
      // into the card behind it.
      accessibilityViewIsModal
    >
      {visible ? <TranslationSheetBody onClose={onClose} {...rest} /> : null}
    </Modal>
  );
}

type TranslationSheetBodyProps = Omit<TranslationSheetProps, 'visible'>;

function TranslationSheetBody({
  locale,
  paperId,
  selection,
  initialStage,
  onClose,
}: TranslationSheetBodyProps) {
  const theme = useTheme();
  const { api } = useSession();
  const [stage, setStage] = useState<TranslationStage>(initialStage);
  const [saveState, setSaveState] = useState<SaveState>({ kind: 'idle' });
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  // A mutation, not a query: `POST /translations` stores the selection and the translation
  // (spec section 7), so it is a write with a result rather than a cached read. That also
  // fixes the effect this used to need — `mutate` is a call, not a setState, so firing it
  // on mount is no longer state written from an effect.
  const translation = useMutation({
    mutationFn: async (wanted: TranslationStage) => {
      if (selection === null) throw new Error('nothing selected');
      return api.translate({
        paperId,
        selection: { field: 'abstract', ...selection },
        style: 'natural',
        stage: wanted,
      });
    },
  });

  const { mutate } = translation;
  // Runs once per opening, because this component only exists while the sheet is open.
  useEffect(() => {
    mutate(initialStage);
  }, [initialStage, mutate]);

  const state: SheetState = translation.isPending
    ? { kind: 'loading' }
    : translation.isError
      ? { kind: 'error', messageKey: errorMessageKey(translation.error) }
      : translation.data === undefined
        ? { kind: 'idle' }
        : {
            kind: 'ready',
            translated: translation.data.translation.translated,
            fellBack: translation.data.translation.fellBackToOriginal,
            notice: translation.data.translation.generation.model.startsWith('mock')
              ? t('translate.mockNotice')
              : null,
          };

  function chooseStage(next: TranslationStage) {
    setStage(next);
    mutate(next);
  }

  /**
   * Save the selection to the personal dictionary (spec section 7: 表現保存).
   *
   * The meaning saved is whatever the sheet is currently showing, and the selection
   * itself becomes the entry's context — spec section 9 wants 実際に読んだ論文の用例, and
   * the sentence the reader was looking at is exactly that.
   */
  async function saveExpression(): Promise<void> {
    if (selection === null || saveState.kind === 'saving') return;
    setSaveState({ kind: 'saving' });
    try {
      const response = await api.saveExpression({
        phrase: selection.exactText,
        meaning: state.kind === 'ready' ? state.translated : '',
        context: selection.exactText,
        sourcePaperId: paperId,
      });
      setSaveState({
        kind: 'done',
        messageKey: response.created ? 'translate.expressionSaved' : 'translate.expressionExists',
      });
    } catch {
      setSaveState({ kind: 'done', messageKey: 'translate.saveFailed' });
    }
  }

  return (
    <View style={[styles.backdrop, { backgroundColor: theme.color.overlay }]}>
      <View
        style={[
          styles.sheet,
          {
            backgroundColor: theme.color.card,
            borderTopLeftRadius: theme.radius.sheet,
            borderTopRightRadius: theme.radius.sheet,
            padding: theme.spacing.cardPadding,
            gap: theme.spacing.md,
          },
        ]}
      >
        <View style={styles.header}>
          <Text variant="label" accessibilityRole="header">
            {t('translate.title')}
          </Text>
          <PressableRow
            onPress={onClose}
            accessibilityLabel={t('translate.cancel')}
            style={{ borderWidth: 0, backgroundColor: 'transparent', paddingHorizontal: 0 }}
          >
            <Text variant="label" tone="accent">
              {t('translate.cancel')}
            </Text>
          </PressableRow>
        </View>

        {/* The original stays visible above everything else. */}
        <View
          style={{
            backgroundColor: theme.color.background,
            borderRadius: theme.radius.tile,
            padding: theme.spacing.md,
          }}
        >
          <Text variant="caption" tone="secondary">
            {t('translate.original')}
          </Text>
          <Text variant="abstract">{selection?.exactText ?? ''}</Text>
        </View>

        <Text variant="caption" tone="secondary">
          {t('translate.stage')}
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
            {STAGES.map((option) => (
              <Chip
                key={option}
                label={t(`stage.${option}` as MessageKey)}
                selected={option === stage}
                tone="accent"
                onPress={() => chooseStage(option)}
              />
            ))}
          </View>
        </ScrollView>

        <ScrollView style={{ maxHeight: 220 }}>
          {state.kind === 'loading' && (
            <ActivityIndicator
              accessibilityLabel={t('translate.loading')}
              color={theme.color.accent}
            />
          )}

          {state.kind === 'error' && (
            <View style={{ gap: theme.spacing.sm }}>
              <Text tone="warning">{t(state.messageKey)}</Text>
              <PressableRow onPress={() => mutate(stage)} accessibilityLabel={t('common.retry')}>
                <Text tone="accent">{t('common.retry')}</Text>
              </PressableRow>
            </View>
          )}

          {state.kind === 'ready' && (
            <View style={{ gap: theme.spacing.sm }}>
              {state.fellBack && <Text tone="warning">{t('translate.fellBack')}</Text>}
              <Text variant="abstract">{state.translated}</Text>
              {state.notice !== null && (
                <Text variant="caption" tone="secondary">
                  {state.notice}
                </Text>
              )}
            </View>
          )}
        </ScrollView>

        <View style={{ gap: theme.spacing.xs }}>
          <PressableRow
            onPress={() => void saveExpression()}
            disabled={selection === null || saveState.kind === 'saving'}
            accessibilityLabel={t('translate.saveExpression')}
          >
            <Text tone="accent">{t('translate.saveExpression')}</Text>
          </PressableRow>
          {saveState.kind === 'done' && (
            <Text
              variant="caption"
              tone={saveState.messageKey === 'translate.saveFailed' ? 'warning' : 'saved'}
              accessibilityLiveRegion="polite"
            >
              {t(saveState.messageKey)}
            </Text>
          )}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheet: {
    maxHeight: '80%',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
});
