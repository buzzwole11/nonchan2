/**
 * The abstract on a Discover card (spec sections 6, 7, 11, 20).
 *
 * 95% of the abstracts in this corpus carry inline maths. Rendered as plain React Native
 * text — which is what this replaced — a sentence came out as
 * `We obtain the deviation bound $\mathbb{P}(|f - \mathbb{E}f| > t) \le 2\exp(...)$.`
 * in the middle of a card a reader is meant to skim in ten seconds. Section 11 makes the
 * LaTeX source the *fallback* for a formula that cannot be typeset, not the presentation.
 *
 * Three decisions are worth stating, because each of them could reasonably have gone the
 * other way.
 *
 * **The whole abstract is one document, not one per formula.** Section 7 selects whole
 * sentences (DECISIONS.md D-018), so a sentence has to stay a single tap target; splitting
 * it around its formulas would leave pieces that cannot be selected as a unit, and put a
 * renderer on screen for every formula on the card.
 *
 * **The card behind gets plain text.** It is scaled and faded under the front card and
 * cannot be tapped, so paying for a second renderer to typeset something nobody can read
 * would be a cost with no reader on the other end.
 *
 * **The plain-text path is kept, not deleted.** It renders until the document reports its
 * height, and it stays if that never happens. A renderer that fails then leaves the reader
 * with the abstract they had before rather than with an empty card — which matters more
 * than usual here, because this is the one screen whose failure has nothing behind it.
 */
import { useCallback, useMemo, useState } from 'react';
import { View } from 'react-native';

import { Text } from '../components/Text';
import {
  ABSTRACT_MESSAGE_KIND,
  type AbstractMessage,
  buildAbstractDocument,
} from '../math/abstractDocument';
import { type MessageKey, translate } from '../i18n';
import {
  type SelectionRange,
  type Sentence,
  isSelected,
  splitMathRuns,
} from '../reading/sentences';
import { useTheme } from '../theme/ThemeProvider';
import { AbstractFrame } from './AbstractFrame';

export interface AbstractBodyProps {
  sentences: readonly Sentence[];
  selection: SelectionRange | null;
  locale: 'ja' | 'en';
  onSelectSentence: (index: number) => void;
  /** True for the card stacked behind, which is a preview and takes no taps. */
  behind?: boolean;
}

/** Before the document reports its own height. Roughly a short abstract. */
const INITIAL_HEIGHT = 180;

/** Past this the abstract scrolls with the card rather than growing without limit. */
const MAX_HEIGHT = 900;

export function AbstractBody({
  sentences,
  selection,
  locale,
  onSelectSentence,
  behind = false,
}: AbstractBodyProps) {
  const theme = useTheme();
  const [height, setHeight] = useState(INITIAL_HEIGHT);
  const [ready, setReady] = useState(false);
  const t = useCallback((key: MessageKey) => translate(locale, key), [locale]);

  const hasMaths = useMemo(
    () => sentences.some((sentence) => splitMathRuns(sentence.text).some((r) => r.kind === 'math')),
    [sentences],
  );

  const selected = useMemo(
    () => sentences.filter((s) => isSelected(selection, s.index)).map((s) => s.index),
    [sentences, selection],
  );

  const type = theme.type('abstract');
  const html = useMemo(
    () =>
      buildAbstractDocument(
        sentences.map((s) => ({ index: s.index, text: s.text })),
        {
          fontSize: type.fontSize,
          lineHeight: type.lineHeight / type.fontSize,
          fontFamily: type.fontFamily,
          color: theme.color.textPrimary,
          backgroundColor: 'transparent',
          selectionColor: theme.color.translationSurface,
          selected,
          tapHint: t('discover.tapToTranslate'),
        },
      ),
    // `selected` is deliberately absent: it seeds the first render, and every change after
    // that is pushed into the live document instead of rebuilding it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      sentences,
      type.fontSize,
      type.lineHeight,
      type.fontFamily,
      theme.color.textPrimary,
      theme.color.translationSurface,
      t,
    ],
  );

  const onMessage = useCallback(
    (raw: string) => {
      let message: AbstractMessage;
      try {
        message = JSON.parse(raw) as AbstractMessage;
      } catch {
        return;
      }
      if (message.kind !== ABSTRACT_MESSAGE_KIND) return;
      if (message.type === 'height') {
        setHeight(Math.min(MAX_HEIGHT, Math.max(1, message.height)));
        setReady(true);
        return;
      }
      if (message.type === 'sentence') {
        onSelectSentence(message.index);
      }
      // The handler's identity changing only re-registers a listener; the document is built
      // from `html`, which does not depend on it, so nothing is re-parsed.
    },
    [onSelectSentence],
  );

  const plain = (
    <Text variant="abstract">
      {sentences.map((sentence) => (
        <Text
          key={sentence.index}
          variant="abstract"
          onPress={behind ? undefined : () => onSelectSentence(sentence.index)}
          accessibilityRole="button"
          accessibilityState={{ selected: isSelected(selection, sentence.index) }}
          accessibilityLabel={sentence.text}
          accessibilityHint={t('discover.tapToTranslate')}
          style={
            isSelected(selection, sentence.index)
              ? {
                  // Tint *and* underline: the selection has to survive greyscale and
                  // colour blindness (spec section 20).
                  backgroundColor: theme.color.translationSurface,
                  textDecorationLine: 'underline',
                }
              : undefined
          }
        >
          {sentence.text}{' '}
        </Text>
      ))}
    </Text>
  );

  // No formulas, no renderer. Roughly one abstract in twenty has no maths at all, and
  // starting a WebView to typeset nothing costs a 600KB parse for a result identical to
  // the text already rendered above.
  if (behind || !hasMaths) return plain;

  return (
    <View>
      {/* Held until the document reports a height, then hidden. If that never arrives the
          reader keeps the abstract rather than looking at an empty card. */}
      <View style={ready ? { height: 0, overflow: 'hidden' } : undefined}>{plain}</View>
      <AbstractFrame
        html={html}
        height={ready ? height : 1}
        selected={selected}
        onMessage={onMessage}
        style={ready ? undefined : { position: 'absolute', opacity: 0 }}
      />
    </View>
  );
}
