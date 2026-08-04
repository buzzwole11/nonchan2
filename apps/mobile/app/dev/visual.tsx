/**
 * The visual-regression gallery (TASKS.md Phase 1-D; spec sections 19, 20, 22).
 *
 * The spec asks for the app to be confirmed in light and dark, on small and large screens,
 * with long Japanese text, at larger Dynamic Type sizes and with Reduce Motion on. Six
 * conditions across a dozen components is more combinations than anyone checks by hand
 * twice, so this screen puts the components on one page and takes the conditions from the
 * URL. `scripts/visual-regression.mjs` walks the matrix and diffs the result.
 *
 * **Fixed content, real components.** The fixtures are constants (`visualFixtures.ts`)
 * because a screenshot of the live feed would differ on every run and the suite would be
 * ignored within a week. But the components are the ones the app ships — a gallery of
 * lookalikes would go stale silently, which is the failure mode a screenshot suite exists
 * to catch.
 *
 * **Its own ThemeProvider.** Nested inside the app's, so the theme inputs can be forced per
 * URL without touching the root. The values it forces are the same seams the unit tests
 * use, so the gallery and the tests cannot drift apart in what "dark" or "large type" mean.
 *
 * A development screen; nothing in the app links to it.
 */
import { useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';

import { AbstractCard } from '../../src/discover/AbstractCard';
import { ActionBar } from '../../src/discover/ActionBar';
import { UndoToast } from '../../src/discover/UndoToast';
import { Chip } from '../../src/components/Chip';
import { PressableRow } from '../../src/components/PressableRow';
import { Text } from '../../src/components/Text';
import {
  VISUAL_FEED,
  VISUAL_LATEX,
  VISUAL_SAVED,
  VISUAL_WIDE_LATEX,
} from '../../src/dev/visualFixtures';
import { type MessageKey, translate } from '../../src/i18n';
import { MathView } from '../../src/math/MathView';
import { ThemeProvider, useTheme } from '../../src/theme/ThemeProvider';

export default function VisualGalleryScreen() {
  const params = useLocalSearchParams<{
    theme?: string;
    fontScale?: string;
    reduceMotion?: string;
    locale?: string;
  }>();

  const scheme = params.theme === 'dark' ? 'dark' : 'light';
  const fontScale = Number(params.fontScale ?? '1') || 1;
  const reduceMotion = params.reduceMotion === '1';
  const locale: 'ja' | 'en' = params.locale === 'en' ? 'en' : 'ja';

  return (
    <ThemeProvider
      initialPreference={scheme}
      forceReduceMotion={reduceMotion}
      forceFontScale={fontScale}
    >
      <Gallery locale={locale} />
    </ThemeProvider>
  );
}

function Gallery({ locale }: { locale: 'ja' | 'en' }) {
  const theme = useTheme();
  const t = (key: MessageKey, params?: Record<string, string | number>) =>
    translate(locale, key, params);

  const [first, second] = VISUAL_FEED;
  const [savedA, savedB] = VISUAL_SAVED;

  return (
    // A plain `View`, not a `ScrollView`: a scroll container clips everything below the
    // viewport, and a full-page screenshot cannot reach inside one. Sections 4 onwards were
    // silently never captured until this changed. Letting the page itself grow means the
    // screenshot is the whole gallery.
    <View
      style={{
        backgroundColor: theme.color.background,
        padding: theme.spacing.screenHorizontal,
        gap: theme.spacing.xl,
      }}
    >
      <Section title="1. Abstract カード">
        {first !== undefined && (
          <AbstractCard
            item={first}
            locale={locale}
            selection={null}
            onSelectSentence={noop}
            onOpenSource={noop}
          />
        )}
      </Section>

      <Section title="2. Abstract カード（日本語の長いタイトル・掲載先とライセンス不明）">
        {second !== undefined && (
          <AbstractCard
            item={second}
            locale={locale}
            selection={null}
            onSelectSentence={noop}
            onOpenSource={noop}
          />
        )}
      </Section>

      <Section title="3. 操作ボタン（スワイプと等価）">
        <ActionBar locale={locale} onAction={noop} />
      </Section>

      <Section title="4. Undo トースト（サーバ確認前 / 確認後）">
        {first !== undefined && (
          <>
            <UndoToast
              pending={{ item: first, actionId: null, actionType: 'save' }}
              locale={locale}
              onUndo={noop}
              onDismiss={noop}
            />
            <UndoToast
              pending={{ item: first, actionId: 'a1', actionType: 'save' }}
              locale={locale}
              onUndo={noop}
              onDismiss={noop}
              reasons={['interesting', 'math']}
              onToggleReason={noop}
            />
          </>
        )}
      </Section>

      <Section title="5. 保存した論文の行">
        {[savedA, savedB].map(
          (entry) =>
            entry !== undefined && (
              <View
                key={entry.savedPaper.paperId}
                style={{
                  backgroundColor: theme.color.card,
                  borderColor: theme.color.border,
                  borderWidth: 1,
                  borderRadius: theme.radius.tile,
                  padding: theme.spacing.lg,
                  gap: theme.spacing.sm,
                }}
              >
                <Text variant="caption" tone="secondary">
                  {entry.paper.primaryFieldId} · {entry.paper.year}
                </Text>
                <Text variant="body">{entry.paper.title}</Text>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
                  <Chip
                    label={t(`savedStatus.${entry.savedPaper.status}` as MessageKey)}
                    tone={entry.savedPaper.status === 'finished' ? 'saved' : 'neutral'}
                  />
                  {entry.savedPaper.reasons.map((reason) => (
                    <Chip key={reason} label={t(`saveReason.${reason}` as MessageKey)} />
                  ))}
                </View>
                <View style={{ flexDirection: 'row', gap: theme.spacing.sm }}>
                  <PressableRow onPress={noop} accessibilityLabel="a" style={{ flex: 1 }}>
                    <Text variant="caption" tone="accent">
                      {t('discover.read')}
                    </Text>
                  </PressableRow>
                  <PressableRow onPress={noop} accessibilityLabel="b" style={{ flex: 1 }}>
                    <Text variant="caption" tone="warning">
                      {t('saved.remove')}
                    </Text>
                  </PressableRow>
                </View>
              </View>
            ),
        )}
      </Section>

      <Section title="6. 文字と色のトーン">
        <Text variant="title">見出し Title</Text>
        <Text variant="label">ラベル Label</Text>
        <Text variant="body">本文 Body — 日本語と English が同じ行に混ざったとき</Text>
        <Text variant="caption" tone="secondary">
          補助 Secondary
        </Text>
        <Text variant="caption" tone="accent">
          強調 Accent
        </Text>
        <Text variant="caption" tone="warning">
          注意 Warning
        </Text>
        <Text variant="caption" tone="saved">
          保存 Saved
        </Text>
      </Section>

      <Section title="7. チップの選択状態（色だけに頼らないこと）">
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: theme.spacing.sm }}>
          <Chip label="未選択" />
          <Chip label="選択済み" selected />
          <Chip label="強調" tone="accent" selected />
          <Chip label="保存" tone="saved" selected />
        </View>
      </Section>

      <Section title="8. 数式（通常 / 横に長い / サーバが拒否）">
        <MathView latex={VISUAL_LATEX} locale={locale} zoomable={false} />
        <MathView latex={VISUAL_WIDE_LATEX} locale={locale} zoomable={false} />
        <MathView
          latex={String.raw`\href{https://example.invalid}{x}`}
          locale={locale}
          renderable={false}
          refusalReasons={['href']}
          zoomable={false}
        />
      </Section>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const theme = useTheme();
  return (
    <View style={{ gap: theme.spacing.sm }}>
      <Text variant="caption" tone="secondary">
        {title}
      </Text>
      {children}
    </View>
  );
}

function noop(): void {
  // The gallery is a still life; nothing here is meant to respond.
}
