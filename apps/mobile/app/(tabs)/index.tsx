/**
 * Discover: the Abstract swipe deck (spec sections 5, 6).
 *
 * Holds the pieces together — deck state, the card, the equivalent buttons, the undo
 * affordance and the translation sheet — and owns the two decisions that need the whole
 * screen in view: when a card counts as "shown", and what happens when there is nothing
 * to show.
 */
import type { SaveReason } from '@papermatch/shared-types';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useSession } from '../../src/api/session';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import { AbstractCard } from '../../src/discover/AbstractCard';
import { ActionBar } from '../../src/discover/ActionBar';
import { BeforeReadSheet } from '../../src/discover/BeforeReadSheet';
import { FeedbackSheet, type FeedbackStatus } from '../../src/discover/FeedbackSheet';
import { SwipeDeck } from '../../src/discover/SwipeDeck';
import { UndoToast } from '../../src/discover/UndoToast';
import type { SwipeDirection } from '../../src/discover/deck';
import type { FeedbackControl } from '../../src/discover/feedback';
import { DEFAULT_SAVE_REASON, toggleReason } from '../../src/discover/saveReasons';
import { useDeck } from '../../src/discover/useDeck';
import { type MessageKey, translate } from '../../src/i18n';
import { TranslationSheet } from '../../src/reading/TranslationSheet';
import {
  type ScopedSelection,
  rangeToSelection,
  selectionFor,
  splitSentences,
  toggleSentence,
} from '../../src/reading/sentences';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function DiscoverScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useSession();
  const deck = useDeck();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [beforeReadOpen, setBeforeReadOpen] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<FeedbackStatus>({ kind: 'idle' });

  // What the server has actually accepted for the paper the toast is about. Kept here
  // rather than assumed from the taps, so a chip never sits lit for a tag that failed to
  // save — the difference between showing state and showing a wish.
  const [savedReasons, setSavedReasons] = useState<readonly SaveReason[]>([]);
  const [tagError, setTagError] = useState(false);

  // The selection belongs to the paper it was made on, so it carries that paper's id and
  // is derived away when the card changes. Clearing it in an effect instead — which is
  // what this used to do — leaves a one-render window where `selectionOffsets` maps
  // sentence indices from the previous abstract onto this one, and the translation
  // request that comes out of it is for text the reader never selected.
  const [selectionState, setSelectionState] = useState<ScopedSelection | null>(null);

  // Set by the effect below, on the render where the card actually reaches the screen.
  const shownAtRef = useRef<number>(0);

  const locale: 'ja' | 'en' = (user?.settings.locale ?? 'ja').startsWith('en') ? 'en' : 'ja';
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const current = deck.current;
  const { noteImpression } = deck;

  const selection = selectionFor(selectionState, current?.paper.id ?? null);

  // A card counts as shown once it is actually on screen, not when it was fetched.
  useEffect(() => {
    if (current === null) return;
    shownAtRef.current = Date.now();
    noteImpression(current.paper.id, current.position);
    // Depends on the recorder, not the whole controller: what this effect needs is the
    // card and a way to record it, and listing the controller made it re-run on state it
    // does not care about — which, since the body of the effect dispatches, was a loop.
  }, [current, noteImpression]);

  const openSource = useCallback(async () => {
    if (current === null) return;
    try {
      // An external browser, not an in-app WebView: spec section 25 restricts WebView
      // navigation, and the publisher's page is somewhere we deliberately do not host.
      await WebBrowser.openBrowserAsync(current.paper.sourceUrl);
    } catch {
      // Nothing to recover; the link is also printed on the card.
    }
  }, [current]);

  const handleAction = useCallback(
    (direction: SwipeDirection) => {
      if (current === null) return;

      if (direction === 'up') {
        void openSource();
        return;
      }
      if (direction === 'down') {
        // Before you read (spec section 8). Requested, never pushed — the swipe is the
        // request, and the card stays in the deck exactly as with the upward swipe.
        setBeforeReadOpen(true);
        return;
      }

      // Dwell is reported when the card leaves, which is what the re-injection rule in
      // spec section 16 reads.
      deck.noteImpression(current.paper.id, current.position, Date.now() - shownAtRef.current);
      // A right swipe saves with the default reason on its own (spec section 9); the tags
      // in the toast are added afterwards, to a paper that is already in the library.
      setSavedReasons(direction === 'right' ? [DEFAULT_SAVE_REASON] : []);
      setTagError(false);
      void deck.act(direction);
    },
    [current, deck, openSource],
  );

  const { sendFeedback } = deck;
  const handleFeedback = useCallback(
    async (control: FeedbackControl) => {
      setFeedbackStatus({ kind: 'sending', control: control.kind });
      const actionId = await sendFeedback(control);
      setFeedbackStatus(
        actionId === null ? { kind: 'failed' } : { kind: 'applied', control: control.kind },
      );
      // The sheet stays open on purpose. Section 16's controls are things a reader reaches
      // for together — "less of this topic, and more classic work" is one thought — and
      // closing after each tap would make the second one a second trip.
    },
    [sendFeedback],
  );

  const { setSaveReasons } = deck;
  const pendingPaperId = deck.state.pendingUndo?.item.paper.id ?? null;
  const toggleSavedReason = useCallback(
    (reason: SaveReason) => {
      if (pendingPaperId === null) return;
      const next = toggleReason(savedReasons, reason);
      // Shown immediately and rolled back if the server refuses. A tag is a small enough
      // claim that waiting for a round trip before the chip responds would feel broken.
      setSavedReasons(next);
      setTagError(false);
      void setSaveReasons(pendingPaperId, next).then((ok) => {
        if (ok) return;
        setSavedReasons(savedReasons);
        setTagError(true);
      });
    },
    [pendingPaperId, savedReasons, setSaveReasons],
  );

  const selectionOffsets = useMemo(() => {
    if (current === null || selection === null) return null;
    return rangeToSelection(
      current.paper.abstract,
      splitSentences(current.paper.abstract),
      selection,
    );
  }, [current, selection]);

  function onSelectSentence(index: number) {
    if (current === null) return;
    const next = toggleSentence(selection, index);
    setSelectionState(next === null ? null : { paperId: current.paper.id, range: next });
    setSheetOpen(next !== null);
  }

  const banner =
    deck.state.error === 'offline'
      ? t('discover.offline')
      : deck.state.degraded
        ? t('discover.degraded')
        : null;

  return (
    <View style={{ flex: 1, backgroundColor: theme.color.background }}>
      <View
        style={{
          paddingTop: insets.top + theme.spacing.md,
          paddingHorizontal: theme.spacing.screenHorizontal,
          gap: theme.spacing.xs,
        }}
      >
        <View style={styles.headerRow}>
          <Text variant="label" accessibilityRole="header">
            {t('discover.title')}
          </Text>
          {/* Section 16's feed controls need a way in that is not a gesture and not buried
              in Settings — the reader forms the opinion while looking at a card. */}
          <PressableRow
            onPress={() => {
              setFeedbackStatus({ kind: 'idle' });
              setFeedbackOpen(true);
            }}
            accessibilityLabel={t('feedback.open')}
            style={styles.headerButton}
          >
            <Text variant="caption" tone="accent">
              {t('feedback.open')}
            </Text>
          </PressableRow>
        </View>
        {banner !== null && (
          <Text variant="caption" tone="warning" accessibilityLiveRegion="polite">
            {banner}
          </Text>
        )}
      </View>

      <View style={[styles.deckArea, { margin: theme.spacing.screenHorizontal }]}>
        {current !== null ? (
          <SwipeDeck
            onSwipe={handleAction}
            front={
              <AbstractCard
                item={current}
                locale={locale}
                selection={selection}
                onSelectSentence={onSelectSentence}
                onOpenSource={() => void openSource()}
              />
            }
            behind={
              deck.next !== null ? (
                <AbstractCard
                  item={deck.next}
                  locale={locale}
                  selection={null}
                  onSelectSentence={() => undefined}
                  onOpenSource={() => undefined}
                  behind
                />
              ) : undefined
            }
          />
        ) : deck.state.loading ? (
          <View style={styles.centre}>
            <ActivityIndicator
              accessibilityLabel={t('common.loading')}
              color={theme.color.accent}
            />
          </View>
        ) : deck.state.error !== null ? (
          <View style={[styles.centre, { gap: theme.spacing.md }]}>
            <Text tone="warning">{t('discover.loadFailed')}</Text>
            <PressableRow onPress={deck.reload} accessibilityLabel={t('discover.reload')}>
              <Text tone="accent">{t('discover.reload')}</Text>
            </PressableRow>
          </View>
        ) : (
          <View style={[styles.centre, { gap: theme.spacing.sm }]}>
            <Text variant="label">{t('discover.empty')}</Text>
            <Text variant="caption" tone="secondary" style={{ textAlign: 'center' }}>
              {t('discover.emptyHint')}
            </Text>
          </View>
        )}
      </View>

      <View
        style={{
          paddingHorizontal: theme.spacing.screenHorizontal,
          paddingBottom: theme.spacing.md,
          gap: theme.spacing.md,
        }}
      >
        {deck.state.pendingUndo !== null && (
          <UndoToast
            pending={deck.state.pendingUndo}
            locale={locale}
            onUndo={() => void deck.undo()}
            onDismiss={deck.dismissUndo}
            reasons={savedReasons}
            onToggleReason={toggleSavedReason}
          />
        )}
        {tagError && (
          <Text variant="caption" tone="warning" accessibilityLiveRegion="polite">
            {t('save.tagFailed')}
          </Text>
        )}
        <ActionBar
          locale={locale}
          onAction={handleAction}
          disabled={current === null}
          hapticsEnabled={user?.settings.hapticsEnabled ?? true}
        />
      </View>

      <BeforeReadSheet
        visible={beforeReadOpen}
        locale={locale}
        paperId={current?.paper.id ?? null}
        paperTitle={current?.paper.title ?? null}
        onClose={() => setBeforeReadOpen(false)}
      />

      <FeedbackSheet
        visible={feedbackOpen}
        locale={locale}
        item={current}
        status={feedbackStatus}
        onSend={(control) => void handleFeedback(control)}
        onClose={() => setFeedbackOpen(false)}
      />

      {current !== null && (
        <TranslationSheet
          visible={sheetOpen && selectionOffsets !== null}
          locale={locale}
          paperId={current.paper.id}
          selection={selectionOffsets}
          initialStage={user?.settings.initialTranslationStage ?? 'natural'}
          onClose={() => {
            setSheetOpen(false);
            setSelectionState(null);
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerButton: {
    // The row default is a full-width block; in the header it sits beside the title.
    paddingVertical: 4,
  },
  deckArea: {
    flex: 1,
  },
  centre: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
