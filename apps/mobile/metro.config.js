// Monorepo-aware Metro config: the app imports `@papermatch/*` workspace packages as
// TypeScript source, so Metro must watch the repository root and resolve modules that
// npm hoisted there.
const path = require('node:path');

const { getDefaultConfig } = require('expo/metro-config');

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, '../..');

const config = getDefaultConfig(projectRoot);

config.watchFolders = [workspaceRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, 'node_modules'),
  path.resolve(workspaceRoot, 'node_modules'),
];
// Without this, two copies of React can be resolved through the workspace symlinks.
config.resolver.disableHierarchicalLookup = true;

module.exports = config;
