module.exports = function babelConfig(api) {
  api.cache(true);
  return {
    presets: [['babel-preset-expo', { jsxImportSource: 'react' }]],
    plugins: [
      // Must stay last (Reanimated requirement). Present from Phase 0 so the swipe deck
      // in Phase 1 does not need a config change mid-feature.
      'react-native-worklets/plugin',
    ],
  };
};
