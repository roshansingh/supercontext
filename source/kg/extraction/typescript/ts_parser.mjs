import { createRequire } from "module";
import fs from "fs";
import path from "path";

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const repoRoot = input.repoRoot;
const files = input.files;

function loadTypeScript() {
  try {
    return createRequire(path.join(repoRoot, "package.json"))("typescript");
  } catch {
    return createRequire(import.meta.url)("typescript");
  }
}

const ts = loadTypeScript();

function scriptKind(filePath) {
  if (filePath.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (filePath.endsWith(".jsx")) return ts.ScriptKind.JSX;
  if (filePath.endsWith(".js") || filePath.endsWith(".mjs") || filePath.endsWith(".cjs")) return ts.ScriptKind.JS;
  return ts.ScriptKind.TS;
}

function lineOf(sourceFile, pos) {
  return sourceFile.getLineAndCharacterOfPosition(pos).line + 1;
}

function textOf(node, sourceFile) {
  return node.getText(sourceFile);
}

function callName(expr, sourceFile) {
  if (ts.isIdentifier(expr)) return expr.text;
  if (ts.isPropertyAccessExpression(expr)) {
    const left = callName(expr.expression, sourceFile);
    return left ? `${left}.${expr.name.text}` : null;
  }
  return null;
}

function bindingNames(name) {
  if (ts.isIdentifier(name)) return [name.text];
  if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
    return name.elements.flatMap((element) => {
      if (ts.isBindingElement(element)) return bindingNames(element.name);
      return [];
    });
  }
  return [];
}

function collectImports(sourceFile) {
  const imports = [];
  for (const statement of sourceFile.statements) {
    if (ts.isImportDeclaration(statement) && ts.isStringLiteral(statement.moduleSpecifier)) {
      const importedNames = [];
      const localNames = [];
      const clause = statement.importClause;
      if (clause?.name) {
        importedNames.push("default");
        localNames.push(clause.name.text);
      }
      if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
        importedNames.push(clause.namedBindings.name.text);
        localNames.push(clause.namedBindings.name.text);
      }
      if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const element of clause.namedBindings.elements) {
          importedNames.push((element.propertyName ?? element.name).text);
          localNames.push(element.name.text);
        }
      }
      imports.push({
        raw_target: statement.moduleSpecifier.text,
        line: lineOf(sourceFile, statement.getStart(sourceFile)),
        imported_names: importedNames,
        local_names: localNames,
        is_type_only: Boolean(clause?.isTypeOnly),
      });
      continue;
    }

    if (ts.isExportDeclaration(statement) && statement.moduleSpecifier && ts.isStringLiteral(statement.moduleSpecifier)) {
      imports.push({
        raw_target: statement.moduleSpecifier.text,
        line: lineOf(sourceFile, statement.getStart(sourceFile)),
        imported_names: [],
        local_names: [],
        is_type_only: Boolean(statement.isTypeOnly),
      });
      continue;
    }

    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        const init = declaration.initializer;
        if (
          init &&
          ts.isCallExpression(init) &&
          ts.isIdentifier(init.expression) &&
          init.expression.text === "require" &&
          init.arguments.length === 1 &&
          ts.isStringLiteral(init.arguments[0])
        ) {
          const names = bindingNames(declaration.name);
          imports.push({
            raw_target: init.arguments[0].text,
            line: lineOf(sourceFile, statement.getStart(sourceFile)),
            imported_names: names,
            local_names: names,
            is_type_only: false,
          });
        }
      }
    }
  }
  return imports;
}

const HTTP_METHODS = new Set(["get", "post", "put", "delete", "patch", "options", "head"]);
const EXPRESS_ROUTE_METHODS = new Set([...HTTP_METHODS, "all"]);

function stringLiteralValue(node) {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  return null;
}

function endpointTargetValue(node) {
  const literal = stringLiteralValue(node);
  if (literal != null) return literal;
  if (!ts.isTemplateExpression(node)) return null;
  let value = node.head.text;
  for (const span of node.templateSpans) {
    value += "{}";
    value += span.literal.text;
  }
  return value;
}

function splitEndpointTarget(rawTarget) {
  const value = rawTarget.trim();
  if (value.startsWith("http://") || value.startsWith("https://")) {
    try {
      const parsed = new URL(value);
      return { path: parsed.pathname || "/", host: parsed.hostname || null };
    } catch {
      return null;
    }
  }
  if (!value.startsWith("/")) return null;
  return { path: value, host: null };
}

function collectExpressFactories(sourceFile) {
  const expressFactories = new Set();
  const routerFactories = new Set();
  for (const statement of sourceFile.statements) {
    if (ts.isImportDeclaration(statement) && ts.isStringLiteral(statement.moduleSpecifier) && statement.moduleSpecifier.text === "express") {
      const clause = statement.importClause;
      if (clause?.name) expressFactories.add(clause.name.text);
      if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) expressFactories.add(clause.namedBindings.name.text);
      if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const element of clause.namedBindings.elements) {
          if ((element.propertyName ?? element.name).text === "Router") routerFactories.add(element.name.text);
        }
      }
      continue;
    }

    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        const init = declaration.initializer;
        if (
          init &&
          ts.isCallExpression(init) &&
          ts.isIdentifier(init.expression) &&
          init.expression.text === "require" &&
          init.arguments.length === 1 &&
          ts.isStringLiteral(init.arguments[0]) &&
          init.arguments[0].text === "express" &&
          ts.isIdentifier(declaration.name)
        ) {
          expressFactories.add(declaration.name.text);
        }
      }
    }
  }
  return { expressFactories, routerFactories };
}

function isRequireCall(node, moduleName) {
  return (
    ts.isCallExpression(node) &&
    ts.isIdentifier(node.expression) &&
    node.expression.text === "require" &&
    node.arguments.length === 1 &&
    ts.isStringLiteral(node.arguments[0]) &&
    node.arguments[0].text === moduleName
  );
}

function isExpressFactoryCall(node, expressFactories) {
  return ts.isCallExpression(node) && ts.isIdentifier(node.expression) && expressFactories.has(node.expression.text);
}

function isInlineExpressFactoryCall(node) {
  return ts.isCallExpression(node) && isRequireCall(node.expression, "express");
}

function isExpressRouterFactoryCall(node, expressFactories, routerFactories) {
  if (!ts.isCallExpression(node)) return false;
  if (ts.isIdentifier(node.expression) && routerFactories.has(node.expression.text)) return true;
  if (!ts.isPropertyAccessExpression(node.expression)) return false;
  return (
    node.expression.name.text === "Router" &&
    ts.isIdentifier(node.expression.expression) &&
    expressFactories.has(node.expression.expression.text)
  );
}

function collectExpressReceivers(sourceFile) {
  const { expressFactories, routerFactories } = collectExpressFactories(sourceFile);
  const receivers = new Set();
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      if (
        isExpressFactoryCall(node.initializer, expressFactories) ||
        isInlineExpressFactoryCall(node.initializer) ||
        isExpressRouterFactoryCall(node.initializer, expressFactories, routerFactories)
      ) {
        receivers.add(node.name.text);
      }
    }
    if (
      ts.isBinaryExpression(node) &&
      node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isIdentifier(node.left) &&
      (isExpressFactoryCall(node.right, expressFactories) ||
        isInlineExpressFactoryCall(node.right) ||
        isExpressRouterFactoryCall(node.right, expressFactories, routerFactories))
    ) {
      receivers.add(node.left.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return receivers;
}

function directExpressRoute(node, sourceFile, receivers) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return null;
  const method = node.expression.name.text;
  if (!EXPRESS_ROUTE_METHODS.has(method)) return null;
  if (!ts.isIdentifier(node.expression.expression) || !receivers.has(node.expression.expression.text)) return null;
  if (node.arguments.length < 1) return null;
  const routePath = stringLiteralValue(node.arguments[0]);
  if (routePath == null) return null;
  return { method, path: routePath, line: lineOf(sourceFile, node.expression.getStart(sourceFile)), source_kind: `express_${method}` };
}

function chainedExpressRoute(node, sourceFile, receivers) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return null;
  const method = node.expression.name.text;
  if (!EXPRESS_ROUTE_METHODS.has(method)) return null;
  const innerCall = node.expression.expression;
  if (!ts.isCallExpression(innerCall) || !ts.isPropertyAccessExpression(innerCall.expression)) return null;
  if (innerCall.expression.name.text !== "route") return null;
  if (!ts.isIdentifier(innerCall.expression.expression) || !receivers.has(innerCall.expression.expression.text)) return null;
  if (innerCall.arguments.length < 1) return null;
  const routePath = stringLiteralValue(innerCall.arguments[0]);
  if (routePath == null) return null;
  return { method, path: routePath, line: lineOf(sourceFile, node.expression.getStart(sourceFile)), source_kind: `express_${method}` };
}

function collectExpressRoutes(sourceFile) {
  const receivers = collectExpressReceivers(sourceFile);
  if (receivers.size === 0) return [];
  const routes = [];
  function visit(node) {
    const route = directExpressRoute(node, sourceFile, receivers) ?? chainedExpressRoute(node, sourceFile, receivers);
    if (route) routes.push(route);
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return routes;
}

function collectAxiosLocals(sourceFile) {
  const locals = new Set();
  for (const statement of sourceFile.statements) {
    if (ts.isImportDeclaration(statement) && ts.isStringLiteral(statement.moduleSpecifier) && statement.moduleSpecifier.text === "axios") {
      const clause = statement.importClause;
      if (clause?.name) locals.add(clause.name.text);
      if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) locals.add(clause.namedBindings.name.text);
      continue;
    }

    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        const init = declaration.initializer;
        if (
          init &&
          ts.isCallExpression(init) &&
          ts.isIdentifier(init.expression) &&
          init.expression.text === "require" &&
          init.arguments.length === 1 &&
          ts.isStringLiteral(init.arguments[0]) &&
          init.arguments[0].text === "axios" &&
          ts.isIdentifier(declaration.name)
        ) {
          locals.add(declaration.name.text);
        }
      }
    }
  }
  return locals;
}

function collectAxiosClients(sourceFile, axiosLocals) {
  const clients = new Set();
  function visit(node) {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      ts.isCallExpression(node.initializer) &&
      ts.isPropertyAccessExpression(node.initializer.expression) &&
      node.initializer.expression.name.text === "create" &&
      ts.isIdentifier(node.initializer.expression.expression) &&
      axiosLocals.has(node.initializer.expression.expression.text)
    ) {
      clients.add(node.name.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return clients;
}

function fetchMethod(node) {
  if (node.arguments.length < 2 || !ts.isObjectLiteralExpression(node.arguments[1])) return "ANY";
  for (const property of node.arguments[1].properties) {
    if (!ts.isPropertyAssignment(property)) continue;
    const name = property.name;
    const isMethod =
      (ts.isIdentifier(name) && name.text === "method") ||
      (ts.isStringLiteral(name) && name.text === "method");
    if (!isMethod) continue;
    const value = stringLiteralValue(property.initializer);
    return value == null ? "ANY" : value.toUpperCase();
  }
  return "ANY";
}

function clientCallFromNode(node, sourceFile, axiosLocals, axiosClients) {
  if (!ts.isCallExpression(node)) return null;
  if (ts.isIdentifier(node.expression) && node.expression.text === "fetch") {
    if (node.arguments.length < 1) return null;
    const rawTarget = endpointTargetValue(node.arguments[0]);
    if (rawTarget == null) return null;
    const target = splitEndpointTarget(rawTarget);
    if (target == null) return null;
    return {
      method: fetchMethod(node),
      path: target.path,
      host: target.host,
      raw_target: rawTarget,
      line: lineOf(sourceFile, node.expression.getStart(sourceFile)),
      source_kind: "fetch_call",
    };
  }

  if (!ts.isPropertyAccessExpression(node.expression)) return null;
  const method = node.expression.name.text;
  if (!HTTP_METHODS.has(method)) return null;
  if (!ts.isIdentifier(node.expression.expression)) return null;
  const receiver = node.expression.expression.text;
  if (!axiosLocals.has(receiver) && !axiosClients.has(receiver)) return null;
  if (node.arguments.length < 1) return null;
  const rawTarget = endpointTargetValue(node.arguments[0]);
  if (rawTarget == null) return null;
  const target = splitEndpointTarget(rawTarget);
  if (target == null) return null;
  return {
    method: method.toUpperCase(),
    path: target.path,
    host: target.host,
    raw_target: rawTarget,
    line: lineOf(sourceFile, node.expression.getStart(sourceFile)),
    source_kind: "axios_call",
  };
}

function collectClientEndpointCalls(sourceFile) {
  const axiosLocals = collectAxiosLocals(sourceFile);
  const axiosClients = collectAxiosClients(sourceFile, axiosLocals);
  const calls = [];
  function visit(node) {
    const call = clientCallFromNode(node, sourceFile, axiosLocals, axiosClients);
    if (call) calls.push(call);
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return calls;
}

function symbolFromStatement(statement, sourceFile) {
  if (ts.isFunctionDeclaration(statement) && statement.name) {
    return { name: statement.name.text, kind: "function", line: lineOf(sourceFile, statement.name.getStart(sourceFile)), end_line: lineOf(sourceFile, statement.end), pos: statement.pos, end: statement.end };
  }
  if (ts.isClassDeclaration(statement) && statement.name) {
    return { name: statement.name.text, kind: "class", line: lineOf(sourceFile, statement.name.getStart(sourceFile)), end_line: lineOf(sourceFile, statement.end), pos: statement.pos, end: statement.end };
  }
  if (ts.isInterfaceDeclaration(statement)) {
    return { name: statement.name.text, kind: "interface", line: lineOf(sourceFile, statement.name.getStart(sourceFile)), end_line: lineOf(sourceFile, statement.end), pos: statement.pos, end: statement.end };
  }
  if (ts.isTypeAliasDeclaration(statement)) {
    return { name: statement.name.text, kind: "type", line: lineOf(sourceFile, statement.name.getStart(sourceFile)), end_line: lineOf(sourceFile, statement.end), pos: statement.pos, end: statement.end };
  }
  if (ts.isEnumDeclaration(statement)) {
    return { name: statement.name.text, kind: "enum", line: lineOf(sourceFile, statement.name.getStart(sourceFile)), end_line: lineOf(sourceFile, statement.end), pos: statement.pos, end: statement.end };
  }
  return null;
}

function collectSymbols(sourceFile) {
  const symbols = [];
  for (const statement of sourceFile.statements) {
    const symbol = symbolFromStatement(statement, sourceFile);
    if (symbol) {
      symbols.push(symbol);
      continue;
    }
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        for (const name of bindingNames(declaration.name)) {
          const kind = declaration.initializer && (ts.isArrowFunction(declaration.initializer) || ts.isFunctionExpression(declaration.initializer)) ? "function" : "value";
          symbols.push({
            name,
            kind,
            line: lineOf(sourceFile, declaration.name.getStart(sourceFile)),
            end_line: lineOf(sourceFile, declaration.end),
            pos: declaration.pos,
            end: declaration.end,
          });
        }
      }
    }
  }
  return symbols;
}

function collectCallsForSymbol(sourceFile, symbol) {
  const calls = [];
  function visit(node) {
    if (node !== sourceFile && (node.pos < symbol.pos || node.end > symbol.end)) return;
    if (ts.isCallExpression(node)) {
      const name = callName(node.expression, sourceFile);
      if (name) {
        calls.push({ name, line: lineOf(sourceFile, node.expression.getStart(sourceFile)) });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return calls;
}

const output = {};
for (const relativePath of files) {
  const absolutePath = path.join(repoRoot, relativePath);
  const sourceText = fs.readFileSync(absolutePath, "utf8");
  const sourceFile = ts.createSourceFile(absolutePath, sourceText, ts.ScriptTarget.Latest, true, scriptKind(relativePath));
  const symbols = collectSymbols(sourceFile);
  output[relativePath] = {
    parse_diagnostics: sourceFile.parseDiagnostics.map((diagnostic) => ({
      message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
      line: diagnostic.start == null ? 1 : lineOf(sourceFile, diagnostic.start),
    })),
    imports: collectImports(sourceFile),
    express_routes: collectExpressRoutes(sourceFile),
    client_endpoint_calls: collectClientEndpointCalls(sourceFile),
    symbols: symbols.map(({ pos, end, ...symbol }) => symbol),
    calls: symbols.flatMap((symbol) =>
      collectCallsForSymbol(sourceFile, symbol).map((call) => ({
        caller: symbol.name,
        name: call.name,
        line: call.line,
      }))
    ),
  };
}

process.stdout.write(JSON.stringify(output));
