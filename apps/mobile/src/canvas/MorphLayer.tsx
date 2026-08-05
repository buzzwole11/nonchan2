/**
 * The travelling shape (spec section 14: 選択中のタイルがLibraryの該当行へ連続変形).
 *
 * One absolutely-positioned view above both layouts, running from the rectangle the paper
 * occupied in the view being left to the one it occupies in the view being entered. It is
 * `pointerEvents="none"` and carries no controls: it exists for the ~240 ms in which the
 * reader is following their paper across, and everything real is underneath it the whole
 * time. Nothing is gated on the animation finishing, so an interrupted or dropped frame
 * costs the animation and not the switch.
 *
 * **Reduce Motion never reaches this component.** Section 20 asks for the continuous
 * transformation to become a short fade, and the caller does that by not starting a morph
 * at all. A "reduced" morph that still flew across the screen, only faster, would be the
 * same motion the setting exists to remove.
 *
 * **Colour travels in Oklab**, in stops. `Animated` interpolates colour strings in sRGB,
 * which would dip darker than both ends in the middle (D-048); precomputing the stops in
 * Oklab keeps the path perceptually straight between them.
 */
import { useEffect, useState } from 'react';
import { Animated, Easing } from 'react-native';

import { type MorphEnds, interpolateColor, morphFrame } from './morph';

export interface MorphLayerProps {
  ends: MorphEnds;
  durationMs: number;
  /** Called when the shape has landed, so the caller can take the overlay down. */
  onDone: () => void;
}

/** Enough that the Oklab path is followed closely; few enough to stay cheap. */
const COLOR_STOPS = 6;

export function MorphLayer({ ends, durationMs, onDone }: MorphLayerProps) {
  // Lazily-initialised state rather than a ref: the value is read while rendering (it is
  // what the style is built from), and a ref read during render is what the React Compiler
  // rules forbid. `Animated.Value` is a stable mutable object, so this never re-renders.
  const [progress] = useState(() => new Animated.Value(0));

  useEffect(() => {
    const animation = Animated.timing(progress, {
      toValue: 1,
      duration: durationMs,
      // Decelerating: the shape arrives gently at the row rather than stopping dead on it,
      // which is what makes it read as landing there instead of being cut off.
      easing: Easing.bezier(0, 0, 0, 1),
      // Layout properties (left/top/width/height) cannot be driven natively.
      useNativeDriver: false,
    });
    animation.start(({ finished }) => {
      if (finished) onDone();
    });
    return () => animation.stop();
    // `onDone` is deliberately not a dependency: it is an inline closure at the call site, so
    // depending on it would restart the animation from zero on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress, durationMs]);

  const stops = Array.from({ length: COLOR_STOPS }, (_, index) => index / (COLOR_STOPS - 1));
  const start = morphFrame(ends, 0);
  const end = morphFrame(ends, 1);

  const between = (from: number, to: number) =>
    progress.interpolate({ inputRange: [0, 1], outputRange: [from, to] });

  return (
    <Animated.View
      pointerEvents="none"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{
        position: 'absolute',
        left: between(start.x, end.x),
        top: between(start.y, end.y),
        width: between(start.width, end.width),
        height: between(start.height, end.height),
        borderRadius: between(start.borderRadius, end.borderRadius),
        backgroundColor: progress.interpolate({
          inputRange: stops,
          outputRange: stops.map((t) => interpolateColor(ends.fromColor, ends.toColor, t)),
        }),
      }}
    />
  );
}
