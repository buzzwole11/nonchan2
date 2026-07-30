/**
 * Rendering under each accessibility condition from spec section 20.
 *
 * Spec section 31 item 11 asks for light/dark, Reduce Motion and Dynamic Type to be
 * confirmed. These assertions are the automated half of that; the manual checklist is in
 * TASKS.md.
 */
import { render, screen } from '@testing-library/react-native';
import { tokens } from '@papermatch/design-tokens';

import { PressableRow } from '../src/components/PressableRow';
import { Text } from '../src/components/Text';
import { ThemeProvider } from '../src/theme/ThemeProvider';

function renderWithTheme(
  ui: React.ReactElement,
  options: { scheme?: 'light' | 'dark'; reduceMotion?: boolean; fontScale?: number } = {},
) {
  return render(
    <ThemeProvider
      initialPreference={options.scheme ?? 'light'}
      forceReduceMotion={options.reduceMotion ?? false}
      forceFontScale={options.fontScale ?? 1}
    >
      {ui}
    </ThemeProvider>,
  );
}

function flatten(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) return Object.assign({}, ...style.map(flatten));
  return (style ?? {}) as Record<string, unknown>;
}

describe('Text', () => {
  it('uses the light palette in the light theme', () => {
    renderWithTheme(<Text>Hello</Text>, { scheme: 'light' });
    expect(flatten(screen.getByText('Hello').props.style).color).toBe(
      tokens.color.light.textPrimary,
    );
  });

  it('uses the dark palette in the dark theme', () => {
    renderWithTheme(<Text>Hello</Text>, { scheme: 'dark' });
    expect(flatten(screen.getByText('Hello').props.style).color).toBe(
      tokens.color.dark.textPrimary,
    );
  });

  it('renders abstract text at the spec size and grows with Dynamic Type', () => {
    renderWithTheme(<Text variant="abstract">Body</Text>, { fontScale: 1 });
    const normal = flatten(screen.getByText('Body').props.style).fontSize;
    expect(normal).toBe(tokens.typography.scale.abstract.fontSize);

    screen.unmount();
    renderWithTheme(<Text variant="abstract">Body</Text>, { fontScale: 2 });
    const large = flatten(screen.getByText('Body').props.style).fontSize;
    expect(large as number).toBeGreaterThan(normal as number);
  });

  it('does not let the platform scale fonts a second time', () => {
    renderWithTheme(<Text>Hello</Text>);
    expect(screen.getByText('Hello').props.allowFontScaling).toBe(false);
  });
});

describe('PressableRow', () => {
  it('is exposed to assistive technology as a labelled button', () => {
    renderWithTheme(
      <PressableRow accessibilityLabel="この論文を保存する">
        <Text>Save</Text>
      </PressableRow>,
    );
    const button = screen.getByRole('button', { name: 'この論文を保存する' });
    expect(button).toBeTruthy();
  });

  it('meets the minimum touch target, and grows it with larger text', () => {
    renderWithTheme(
      <PressableRow accessibilityLabel="Row">
        <Text>Row</Text>
      </PressableRow>,
      { fontScale: 1 },
    );
    const normal = flatten(screen.getByRole('button').props.style).minHeight as number;
    expect(normal).toBeGreaterThanOrEqual(tokens.a11y.minTouchTarget);

    screen.unmount();
    renderWithTheme(
      <PressableRow accessibilityLabel="Row">
        <Text>Row</Text>
      </PressableRow>,
      { fontScale: 2 },
    );
    expect(flatten(screen.getByRole('button').props.style).minHeight as number).toBeGreaterThan(
      normal,
    );
  });

  it('reports its disabled state rather than only looking dimmer', () => {
    renderWithTheme(
      <PressableRow accessibilityLabel="Row" disabled>
        <Text>Row</Text>
      </PressableRow>,
    );
    expect(screen.getByRole('button').props.accessibilityState.disabled).toBe(true);
  });
});
