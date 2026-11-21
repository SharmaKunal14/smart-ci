// Read-only TypeScript analysis using the enrolled repository's compiler.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire, builtinModules } from 'node:module';
const [root, input, output] = process.argv.slice(2);
const req = createRequire(path.join(root, 'package.json'));
const ts = req('typescript');
const request = JSON.parse(fs.readFileSync(input, 'utf8'));
const tracked = new Set(request.files);
const dependencies = Object.fromEntries(request.files.map(p => [p, []]));
const widened = new Set();
const gaps = new Set();
const options = new Map();
const relative = p => path.relative(root, p).split(path.sep).join('/');
if (!/^5\./.test(ts.version)) gaps.add('UNSUPPORTED_TYPESCRIPT_VERSION');
for (const project of request.projects) {
  const file = path.join(root, project);
  const parsed = ts.readConfigFile(file, ts.sys.readFile);
  if (parsed.error || parsed.config.extends || parsed.config.references) {
    gaps.add('UNSUPPORTED_PROJECT_CONFIGURATION'); continue;
  }
  const config = ts.parseJsonConfigFileContent(parsed.config, ts.sys, path.dirname(file));
  if (config.errors.length) gaps.add('INVALID_PROJECT_CONFIGURATION');
  for (const p of config.fileNames) {
    const name = relative(p);
    if (options.has(name)) gaps.add('OVERLAPPING_PROJECTS');
    options.set(name, config.options);
  }
}
// Support an explicit literal Vitest configuration; never silently ignore plugins/loaders.
function literal(n) {
  if (ts.isStringLiteral(n) || ts.isNumericLiteral(n)) return n.text;
  if (n.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (n.kind === ts.SyntaxKind.FalseKeyword) return false;
  if (ts.isArrayLiteralExpression(n)) return n.elements.map(literal);
  if (ts.isObjectLiteralExpression(n)) {
    const result = Object.create(null);
    for (const p of n.properties) {
      if (!ts.isPropertyAssignment(p) || !(ts.isIdentifier(p.name) || ts.isStringLiteral(p.name))) throw Error('config');
      if (Object.hasOwn(result, p.name.text)) throw Error('duplicate');
      result[p.name.text] = literal(p.initializer);
    }
    return result;
  }
  throw Error('config');
}
let setup = [];
try {
  const code = fs.readFileSync(path.join(root, 'vitest.config.ts'), 'utf8');
  const file = ts.createSourceFile('vitest.config.ts', code, ts.ScriptTarget.Latest, true);
  if (file.statements.length !== 2) throw Error('config');
  const imp = file.statements[0], exp = file.statements[1];
  if (!ts.isImportDeclaration(imp) || imp.moduleSpecifier.text !== 'vitest/config' ||
      imp.importClause?.namedBindings?.elements?.length !== 1 ||
      imp.importClause.namedBindings.elements[0].name.text !== 'defineConfig' ||
      imp.importClause.namedBindings.elements[0].propertyName || imp.importClause.isTypeOnly || imp.importClause.name ||
      file.parseDiagnostics.length || !ts.isExportAssignment(exp) || exp.isExportEquals || !ts.isCallExpression(exp.expression) ||
      exp.expression.expression.getText(file) !== 'defineConfig' || exp.expression.arguments.length !== 1) throw Error('config');
  const config = literal(exp.expression.arguments[0]);
  if (Object.keys(config).some(k => k !== 'test') || !config.test) throw Error('config');
  const allowed = new Set(['coverage', 'environment', 'include', 'exclude', 'mockReset', 'restoreMocks', 'globals', 'setupFiles', 'testTimeout']);
  if (Object.keys(config.test).some(k => !allowed.has(k)) || config.test.environment !== 'node') throw Error('config');
  if (config.test.coverage?.enabled) throw Error('coverage');
  setup = config.test.setupFiles || [];
  if (typeof setup === 'string') setup = [setup];
  if (setup.some(p => typeof p !== 'string' || !tracked.has(p))) throw Error('setup');
} catch { gaps.add('UNSUPPORTED_VITEST_CONFIGURATION'); }
const builtins = new Set(builtinModules.map(p => p.replace(/^node:/, '')));
function edge(from, spec, opts) {
  if (typeof spec !== 'string') { widened.add(from); return; }
  const bare = spec.replace(/^node:/, '');
  if (builtins.has(bare)) {
    if (/^(fs|child_process|worker_threads|vm|module)(\/|$)/.test(bare)) widened.add(from);
    return;
  }
  const resolved = ts.resolveModuleName(spec, path.join(root, from), opts, ts.sys).resolvedModule;
  if (!resolved) { widened.add(from); return; }
  const real = fs.realpathSync(resolved.resolvedFileName);
  const installed = path.relative(fs.realpathSync(path.join(root, 'node_modules')), real);
  if (installed && !installed.startsWith('..' + path.sep) && !path.isAbsolute(installed)) return;
  const target = relative(real);
  if (!tracked.has(target) || !options.has(target) && /\.[cm]?[jt]sx?$/.test(target)) { widened.add(from); return; }
  dependencies[from].push(target);
}
for (const [name, opts] of [...options.entries()].sort()) {
  if (!tracked.has(name)) { gaps.add('UNTRACKED_PROJECT_SOURCE'); continue; }
  const code = fs.readFileSync(path.join(root, name), 'utf8');
  const file = ts.createSourceFile(name, code, ts.ScriptTarget.Latest, true);
  if (file.parseDiagnostics.length) gaps.add('PARSE_ERROR');
  function visit(n) {
    if (request.tests.includes(name) && (
        ts.isPropertyAccessExpression(n) && n.name.text === 'only' ||
        ts.isElementAccessExpression(n) && ts.isStringLiteral(n.argumentExpression) && n.argumentExpression.text === 'only' ||
        ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === 'only')) gaps.add('FOCUSED_TESTS_UNSUPPORTED');
    if (ts.isIdentifier(n) && ['require', 'eval', 'Function'].includes(n.text) && !(ts.isCallExpression(n.parent) && n.parent.expression === n)) widened.add(name);
    if ((ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) && n.moduleSpecifier) edge(name, n.moduleSpecifier.text, opts);
    if (ts.isImportEqualsDeclaration(n)) widened.add(name);
    if (ts.isCallExpression(n)) {
      const expression = n.expression.getText(file);
      if (n.expression.kind === ts.SyntaxKind.ImportKeyword || expression === 'require' || /\.(mock|doMock|importActual|importMock)$/.test(expression)) {
        const arg = n.arguments[0];
        edge(name, arg && ts.isStringLiteral(arg) ? arg.text : null, opts);
      } else if (expression === 'eval' || expression.includes('import.meta.glob') || expression.endsWith('.readFile') || expression.endsWith('.readFileSync')) widened.add(name);
    }
    if (ts.isNewExpression(n) && ['Function', 'Worker', 'URL'].includes(n.expression.getText(file))) widened.add(name);
    ts.forEachChild(n, visit);
  }
  visit(file);
}
for (const name of request.tests) {
  if (!options.has(name)) gaps.add('TEST_OUTSIDE_PROJECT');
  dependencies[name]?.push(...setup);
}
// An opaque module may consume any tracked input. Preserve that uncertainty as edges.
for (const name of widened) dependencies[name] = request.files.filter(p => p !== name);
for (const name of Object.keys(dependencies)) dependencies[name] = [...new Set(dependencies[name])].sort();
fs.writeFileSync(output, JSON.stringify({dependencies, widened: [...widened].sort(), gaps: [...gaps].sort(), typescript: ts.version, node: process.version, analyzed: [...options.keys()].sort()}));
