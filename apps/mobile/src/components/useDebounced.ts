/**
 * Hold a rapidly changing value still for a moment.
 *
 * Search is the reason this exists. Firing a request per keystroke means「量子」 sends three
 * requests, two of which are already stale before they land, and the results flicker
 * through the prefixes on the way to the answer. The delay is short enough that a reader
 * who stops typing sees results immediately and long enough that mid-word states never
 * reach the network.
 *
 * The timer is cleared on every change and on unmount, so the last value always wins and a
 * screen that goes away never sets state afterwards.
 */
import { useEffect, useState } from 'react';

export function useDebounced<T>(value: T, delayMs = 250): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    // setState inside the timer callback rather than in the effect body: this runs after
    // the delay, not during the render's commit, so it is not the pattern React Compiler
    // warns about.
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}
