// Native TypeScript 7 compiler and Vitest 5 project discovery. No replacement config.
import fs from 'node:fs';
import path from 'node:path';
import { builtinModules, createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [root, input, output] = process.argv.slice(2);
const request = JSON.parse(fs.readFileSync(input, 'utf8'));
const profile = request.native_project;
const req = createRequire(path.join(root, 'package.json'));
const version = req('typescript/package.json').version;
if (!/^7\.0\./.test(version) || !/^v26\./.test(process.version)) throw Error('unsupported native compiler/runtime');
const { API } = await import(pathToFileURL(req.resolve('typescript/unstable/sync')));
const ts = await import(pathToFileURL(req.resolve('typescript/unstable/ast')));
const { createVitest } = await import(pathToFileURL(req.resolve('vitest/node')));
const tracked = new Set(request.files);
const tests = new Set(request.tests);
const deps = Object.fromEntries(request.files.map(p => [p, new Set()]));
const gaps = new Set(), widened = new Set(), analyzed = new Set(), warnings = new Set();
const relative = p => path.relative(root, p).split(path.sep).join('/');
const builtins = new Set(builtinModules.map(p => p.replace(/^node:/, '')));

const vitest = await createVitest({
  root: path.join(root, profile.directory),
  config: path.join(root, profile.configuration),
  project: [profile.project], watch: false,
});
let setup = [];
try {
  if (vitest.projects.length !== 1 || vitest.projects[0].name !== profile.project) throw Error('ambiguous project');
  const project = vitest.projects[0];
  const config = project.config;
  const files = (await vitest.globTestSpecifications()).map(s => relative(s.moduleId)).sort();
  if (JSON.stringify(files) !== JSON.stringify([...tests].sort())) gaps.add('NATIVE_INVENTORY_MISMATCH');
  if (config.environment !== 'node' || config.browser?.enabled || config.typecheck.enabled ||
      config.testNamePattern || config.shard || config.runner || config.globalSetup.length ||
      config.includeSource?.length || !['forks', 'threads'].includes(config.pool)) gaps.add('UNSUPPORTED_NATIVE_PROJECT');
  if (config.isolate === false) warnings.add('NATIVE_SHARED_CONTEXT_REQUIRES_TEST_INDEPENDENCE');
  // Custom transforms and aliases require their own dependency collector.
  if (project.viteConfig.plugins.some(p => !/^(vite:|vitest:|alias$)/.test(p.name))) gaps.add('UNSUPPORTED_VITE_PLUGIN');
  if (project.viteConfig.resolve.alias.some(a =>
    !/\/vite\/dist\/client\/(env|client)\.mjs$/.test(a.replacement))) gaps.add('UNSUPPORTED_VITE_ALIAS');
  setup = config.setupFiles.map(relative);
  if (setup.some(p => !tracked.has(p))) gaps.add('UNTRACKED_SETUP');
} finally { await vitest.close(); }

const api = new API({ cwd: root });
try {
  const snapshot = api.updateSnapshot({ openProjects: request.projects.map(p => path.join(root, p)) });
  for (const configPath of request.projects) {
    const project = snapshot.getProject(path.join(root, configPath));
    if (!project) { gaps.add('MISSING_COMPILER_PROJECT'); continue; }
    if (project.program.getSyntacticDiagnostics().length) gaps.add('PARSE_ERROR');
    const sources = new Map();
    // Compiler paths are canonicalized on case-insensitive filesystems. Preserve
    // the exact Git spelling by mapping native SourceFile.path back to fileName.
    const canonical = new Map();
    for (const filename of project.program.getSourceFileNames()) {
      const name = relative(filename);
      if (!tracked.has(name)) continue;
      const source = project.program.getSourceFile(filename);
      if (!source) { gaps.add('MISSING_COMPILER_SOURCE'); continue; }
      canonical.set(source.path, name);
      sources.set(name, source);
      analyzed.add(name);
    }
    for (const [name, source] of sources) {
      const imports = [];
      function edge(node) {
        if (!node || !ts.isStringLiteral(node)) { widened.add(name); return; }
        const bare = node.text.replace(/^node:/, '');
        if (builtins.has(bare)) {
          if (/^(fs|child_process|worker_threads|vm|module)(\/|$)/.test(bare)) widened.add(name);
          return;
        }
        imports.push(node);
      }
      function visit(n) {
        if (tests.has(name) && (
          ts.isPropertyAccessExpression(n) && n.name.text === 'only' ||
          ts.isElementAccessExpression(n) && ts.isStringLiteral(n.argumentExpression) && n.argumentExpression.text === 'only' ||
          ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'only')) gaps.add('FOCUSED_TESTS_UNSUPPORTED');
        if (ts.isIdentifier(n) && ['require', 'eval', 'Function'].includes(n.text) &&
          !(ts.isCallExpression(n.parent) && n.parent.expression === n)) widened.add(name);
        if ((ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) && n.moduleSpecifier) edge(n.moduleSpecifier);
        if (ts.isImportEqualsDeclaration(n)) widened.add(name);
        if (ts.isCallExpression(n)) {
          const expression = n.expression.getText(source);
          if (n.expression.kind === ts.SyntaxKind.ImportKeyword || expression === 'require' ||
              /\.(mock|doMock|importActual|importMock)$/.test(expression)) edge(n.arguments[0]);
          else if (expression === 'eval' || expression.includes('import.meta.glob') ||
              expression.endsWith('.readFile') || expression.endsWith('.readFileSync')) widened.add(name);
        }
        if (ts.isNewExpression(n) && ['Function', 'Worker', 'URL'].includes(n.expression.getText(source))) widened.add(name);
        n.forEachChild(visit);
      }
      visit(source);
      const symbols = imports.length ? project.checker.getSymbolAtLocation(imports) : [];
      for (const symbol of symbols) {
        if (!symbol || !symbol.declarations.length) { widened.add(name); continue; }
        for (const declaration of symbol.declarations) {
          const target = canonical.get(declaration.path);
          if (target) deps[name].add(target);
          else if (!declaration.path.includes('/node_modules/')) widened.add(name);
        }
      }
      for (const reference of source.referencedFiles) {
        const target = relative(path.resolve(path.dirname(source.fileName), reference.fileName));
        if (tracked.has(target)) deps[name].add(target);
        else widened.add(name);
      }
    }
  }
} finally { api.close(); }
for (const test of tests) {
  if (!analyzed.has(test)) gaps.add('TEST_OUTSIDE_PROJECT');
  for (const file of setup) if (deps[test]) deps[test].add(file);
}
for (const name of widened) deps[name] = new Set(request.files.filter(p => p !== name));
fs.writeFileSync(output, JSON.stringify({
  dependencies: Object.fromEntries(Object.entries(deps).map(([p, edges]) => [p, [...edges].sort()])),
  widened: [...widened].sort(), gaps: [...gaps].sort(), analyzed: [...analyzed].sort(),
  warnings: [...warnings].sort(), typescript: version, node: process.version,
}));
