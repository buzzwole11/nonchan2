/**
 * On-device check for the formula renderer.
 *
 * `MathView` wraps a WebView, and a WebView cannot be exercised in the web build or in
 * jest. Everything it renders is tested — the document generator is a pure function
 * covered both as text and by rendering its output in a real browser — but the native
 * half is not, and the ways it can fail are all invisible from here: a view that collapses
 * to zero height, a transparent background that comes out white on Android, a formula that
 * VoiceOver reads as nothing.
 *
 * So this screen exists to make that check one launch rather than a list of steps. Open
 * `/dev/math` on a device and the cases that matter are all on one page, each labelled with
 * what it should look like. The height each formula reported is printed next to it, because
 * that is the number the layout depends on and the one that is wrong when a formula is
 * clipped in half.
 *
 * It is a development screen and is not linked from anywhere in the app.
 */

import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Text } from '../../src/components/Text';
import { MathView } from '../../src/math/MathView';
import { useTheme, useThemeControls } from '../../src/theme/ThemeProvider';
import { PressableRow } from '../../src/components/PressableRow';

interface Case {
  title: string;
  expectation: string;
  latex: string;
  display?: boolean;
  renderable?: boolean;
  refusalReasons?: string[];
}

const CASES: Case[] = [
  {
    title: '1. ディスプレイ数式',
    expectation: '中央寄せで組版される。積分記号と分数が潰れていないこと。',
    latex: String.raw`I(a) = \int_{-\infty}^{\infty} e^{-a x^{2}}\,dx = \sqrt{\frac{\pi}{a}}`,
  },
  {
    title: '2. 縦に高い式',
    expectation: '行列の高さぶん枠が広がる。上下が切れていたら高さ通知が効いていない。',
    latex: String.raw`\begin{pmatrix} a & b \\ c & d \end{pmatrix}^{-1} = \frac{1}{ad-bc}\begin{pmatrix} d & -b \\ -c & a \end{pmatrix}`,
  },
  {
    title: '3. 横に長い式',
    expectation: '右端で切れず、横スクロールできること（画面外に押し出さない）。',
    latex: String.raw`\mathcal{L} = -\frac{1}{4}F_{\mu\nu}F^{\mu\nu} + i\bar{\psi}\gamma^{\mu}D_{\mu}\psi + |D_{\mu}\phi|^{2} - V(\phi) + \text{h.c.}`,
  },
  {
    title: '4. インライン',
    expectation:
      '本文の行に収まる高さ。ディスプレイと同じ大きさなら display の指定が効いていない。',
    latex: String.raw`E = mc^2`,
    display: false,
  },
  {
    title: '5. 組版できない式',
    expectation: 'LaTeX ソースが等幅で出て、下に警告文が出る（空白にはならない）。',
    latex: String.raw`\frac{a}{`,
  },
  {
    title: '6. サーバが拒否した式',
    expectation: 'WebView を起動せずソース表示。理由が括弧内に出る。',
    latex: String.raw`\href{javascript:alert(1)}{x}`,
    renderable: false,
    refusalReasons: ['forbidden_command'],
  },
  {
    title: '7. 攻撃的な入力',
    expectation: 'ソースがそのまま組版に失敗して出るだけ。アラートやレイアウト崩れが起きないこと。',
    latex: String.raw`</script><script>alert('xss')</script>`,
  },
];

export default function MathCheckScreen() {
  const theme = useTheme();
  const { preference, setPreference } = useThemeControls();
  const insets = useSafeAreaInsets();

  return (
    <ScrollView
      style={{ backgroundColor: theme.color.background }}
      contentContainerStyle={{
        paddingTop: insets.top + theme.spacing.lg,
        paddingHorizontal: theme.spacing.screenHorizontal,
        paddingBottom: insets.bottom + theme.spacing.xxl,
        gap: theme.spacing.lg,
      }}
    >
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="title" accessibilityRole="header">
          数式レンダラの実機確認
        </Text>
        <Text variant="caption" tone="secondary">
          開発用の画面です。各項目の「期待」と実際を見比べてください。VoiceOver / TalkBack
          を有効にして、式がラベルとして読み上げられることも確認してください。
        </Text>
        <PressableRow
          onPress={() => setPreference(preference === 'dark' ? 'light' : 'dark')}
          accessibilityLabel="テーマを切り替える"
        >
          <Text tone="accent">テーマを切り替える（現在: {preference}）</Text>
        </PressableRow>
      </View>

      {CASES.map((item) => (
        <CaseBlock key={item.title} item={item} />
      ))}
    </ScrollView>
  );
}

function CaseBlock({ item }: { item: Case }) {
  const theme = useTheme();
  // Not wired to MathView's own reporting — this is what the *layout* ended up as, which
  // is the thing that is wrong when a formula is clipped.
  const [measured, setMeasured] = useState<number | null>(null);

  return (
    <View style={{ gap: theme.spacing.xs }}>
      <Text variant="label">{item.title}</Text>
      <Text variant="caption" tone="secondary">
        期待: {item.expectation}
      </Text>
      <View
        onLayout={(event) => setMeasured(Math.round(event.nativeEvent.layout.height))}
        style={{
          backgroundColor: theme.color.card,
          borderColor: theme.color.border,
          borderWidth: 1,
          borderRadius: theme.radius.tile,
          padding: theme.spacing.sm,
        }}
      >
        <MathView
          latex={item.latex}
          locale="ja"
          display={item.display ?? true}
          renderable={item.renderable ?? true}
          refusalReasons={item.refusalReasons ?? []}
          accessibilityLabel={`${item.title} の数式`}
        />
      </View>
      <Text variant="caption" tone="secondary">
        実測の高さ: {measured === null ? '—' : `${measured}px`}
      </Text>
    </View>
  );
}
