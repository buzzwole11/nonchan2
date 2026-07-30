/**
 * The swipe deck (spec section 6).
 *
 * Gestures: left skips, right saves, up opens the source, down shows what to read first.
 * Every one of them also has a button in `ActionBar` — spec section 20 requires the
 * gesture never to be the only way, and spec section 29 makes that a completion criterion.
 *
 * Reduce Motion is honoured by shortening the release animation rather than removing it:
 * the card still has to leave the screen, but it does so without the long spring that some
 * users find nauseating (spec section 19/20).
 */
import type { ReactNode } from 'react';
import { Dimensions, StyleSheet, View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';

import { tokens } from '@papermatch/design-tokens';

import type { SwipeDirection } from './deck';
import { useTheme } from '../theme/ThemeProvider';

const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');
const COMMIT_RATIO = tokens.motion.swipe.commitThresholdRatio;
const VELOCITY = tokens.motion.swipe.velocityThreshold;
const MAX_ROTATION = tokens.motion.swipe.maxRotationDeg;

export interface SwipeDeckProps {
  /** The card the gestures apply to. */
  front: ReactNode;
  /** Rendered behind, so the deck reads as a stack rather than a single card. */
  behind?: ReactNode;
  onSwipe: (direction: SwipeDirection) => void;
  enabled?: boolean;
}

export function SwipeDeck({ front, behind, onSwipe, enabled = true }: SwipeDeckProps) {
  const theme = useTheme();
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);

  const commitX = SCREEN_WIDTH * COMMIT_RATIO;
  const commitY = SCREEN_HEIGHT * COMMIT_RATIO * 0.6;
  const exitDuration = theme.duration('fast');
  const reduceMotion = theme.reduceMotion;

  function reset() {
    'worklet';
    if (reduceMotion) {
      translateX.value = withTiming(0, { duration: exitDuration });
      translateY.value = withTiming(0, { duration: exitDuration });
    } else {
      translateX.value = withSpring(0, { damping: 18, stiffness: 180 });
      translateY.value = withSpring(0, { damping: 18, stiffness: 180 });
    }
  }

  const pan = Gesture.Pan()
    .enabled(enabled)
    // The card is full of tappable sentences (spec section 7). A pan that claims the
    // pointer immediately swallows every one of those taps — selection simply stopped
    // working, which was only visible once the app was driven end to end. Requiring real
    // movement first lets a tap fall through to the child, and also stops the card
    // twitching when the user means to select rather than swipe.
    .activeOffsetX([-12, 12])
    .activeOffsetY([-12, 12])
    .onUpdate((event) => {
      translateX.value = event.translationX;
      translateY.value = event.translationY;
    })
    .onEnd((event) => {
      const horizontal = Math.abs(event.translationX) > Math.abs(event.translationY);

      if (horizontal) {
        const committed =
          Math.abs(event.translationX) > commitX || Math.abs(event.velocityX) > VELOCITY;
        if (committed) {
          const direction: SwipeDirection = event.translationX > 0 ? 'right' : 'left';
          translateX.value = withTiming(
            Math.sign(event.translationX) * SCREEN_WIDTH * 1.4,
            { duration: exitDuration },
            () => {
              // Reset before the parent swaps the card in, so the next one does not
              // appear already flung off-screen.
              translateX.value = 0;
              translateY.value = 0;
              runOnJS(onSwipe)(direction);
            },
          );
          return;
        }
      } else {
        const committed =
          Math.abs(event.translationY) > commitY || Math.abs(event.velocityY) > VELOCITY;
        if (committed) {
          // Up and down do not remove the card, so it springs back either way.
          const direction: SwipeDirection = event.translationY < 0 ? 'up' : 'down';
          runOnJS(onSwipe)(direction);
          reset();
          return;
        }
      }
      reset();
    });

  const frontStyle = useAnimatedStyle(() => {
    const rotate = interpolate(
      translateX.value,
      [-SCREEN_WIDTH, 0, SCREEN_WIDTH],
      [-MAX_ROTATION, 0, MAX_ROTATION],
    );
    return {
      transform: [
        { translateX: translateX.value },
        { translateY: translateY.value },
        { rotateZ: reduceMotion ? '0deg' : `${rotate}deg` },
      ],
    };
  });

  const behindStyle = useAnimatedStyle(() => {
    const progress = Math.min(1, Math.abs(translateX.value) / commitX);
    // The card underneath rises as the top one leaves. Reduce Motion pins it in place.
    const scale = reduceMotion ? 0.97 : interpolate(progress, [0, 1], [0.94, 1]);
    return { transform: [{ scale }] };
  });

  return (
    <View style={styles.stack}>
      {behind !== undefined && (
        <Animated.View style={[styles.layer, behindStyle]} pointerEvents="none">
          {behind}
        </Animated.View>
      )}
      <GestureDetector gesture={pan}>
        <Animated.View style={[styles.layer, frontStyle]}>{front}</Animated.View>
      </GestureDetector>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    flex: 1,
  },
  layer: {
    ...StyleSheet.absoluteFill,
  },
});
