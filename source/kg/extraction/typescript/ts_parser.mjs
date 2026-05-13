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
const ASSIGNMENT_OPERATORS = new Set([
  ts.SyntaxKind.EqualsToken,
  ts.SyntaxKind.PlusEqualsToken,
  ts.SyntaxKind.MinusEqualsToken,
  ts.SyntaxKind.AsteriskEqualsToken,
  ts.SyntaxKind.AsteriskAsteriskEqualsToken,
  ts.SyntaxKind.SlashEqualsToken,
  ts.SyntaxKind.PercentEqualsToken,
  ts.SyntaxKind.LessThanLessThanEqualsToken,
  ts.SyntaxKind.GreaterThanGreaterThanEqualsToken,
  ts.SyntaxKind.GreaterThanGreaterThanGreaterThanEqualsToken,
  ts.SyntaxKind.AmpersandEqualsToken,
  ts.SyntaxKind.BarEqualsToken,
  ts.SyntaxKind.CaretEqualsToken,
  ts.SyntaxKind.AmpersandAmpersandEqualsToken,
  ts.SyntaxKind.BarBarEqualsToken,
  ts.SyntaxKind.QuestionQuestionEqualsToken,
]);
const EXPRESS_ROUTE_METHODS = new Set([...HTTP_METHODS, "all"]);

function stringLiteralValue(node) {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  return null;
}

function rawNodeText(node, sourceFile) {
  const text = node.getText(sourceFile);
  return text.length > 80 ? `${text.slice(0, 77)}...` : text;
}

function collectTopLevelLiteralBindings(sourceFile) {
  const bindings = new Map();
  const invalid = new Set();
  for (const statement of sourceFile.statements) {
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name)) continue;
        const name = declaration.name.text;
        if (bindings.has(name)) invalid.add(name);
        const literal = declaration.initializer ? stringLiteralValue(declaration.initializer) : null;
        if (literal == null) {
          invalid.add(name);
          continue;
        }
        bindings.set(name, literal);
      }
      continue;
    }
    if (
      ts.isExpressionStatement(statement) &&
      ts.isBinaryExpression(statement.expression) &&
      ASSIGNMENT_OPERATORS.has(statement.expression.operatorToken.kind) &&
      ts.isIdentifier(statement.expression.left)
    ) {
      invalid.add(statement.expression.left.text);
    }
  }
  for (const name of invalid) bindings.delete(name);
  return bindings;
}

function declaresNameInBindingName(nameNode, targetName) {
  return bindingNames(nameNode).includes(targetName);
}

function parametersDeclareName(node, targetName) {
  return node.parameters?.some((param) => declaresNameInBindingName(param.name, targetName)) ?? false;
}

function variableStatementDeclaresName(statement, targetName) {
  if (!ts.isVariableStatement(statement)) return false;
  return statement.declarationList.declarations.some((declaration) => declaresNameInBindingName(declaration.name, targetName));
}

function forInitializerDeclaresName(initializer, targetName) {
  if (!initializer || !ts.isVariableDeclarationList(initializer)) return false;
  return initializer.declarations.some((declaration) => declaresNameInBindingName(declaration.name, targetName));
}

function forInOfInitializerDeclaresName(initializer, targetName) {
  if (ts.isVariableDeclarationList(initializer)) {
    return initializer.declarations.some((declaration) => declaresNameInBindingName(declaration.name, targetName));
  }
  return declaresNameInBindingName(initializer, targetName);
}

function sourceFileImportDeclaresName(sourceFile, targetName) {
  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement)) continue;
    const clause = statement.importClause;
    if (!clause) continue;
    if (clause.name?.text === targetName) return true;
    const bindings = clause.namedBindings;
    if (bindings && ts.isNamespaceImport(bindings) && bindings.name.text === targetName) return true;
    if (bindings && ts.isNamedImports(bindings)) {
      for (const element of bindings.elements) {
        if (element.name.text === targetName) return true;
      }
    }
  }
  return false;
}

function blockDeclaresNameBeforeUse(block, targetName, useNode, sourceFile) {
  for (const statement of block.statements ?? []) {
    if (statement.getStart(sourceFile) > useNode.getStart(sourceFile)) break;
    if (variableStatementDeclaresName(statement, targetName)) return true;
    if (
      ts.isFunctionDeclaration(statement) &&
      statement.name?.text === targetName &&
      statement.getStart(sourceFile) < useNode.getStart(sourceFile)
    ) {
      return true;
    }
  }
  return false;
}

function identifierIsLocallyShadowed(useNode, targetName, sourceFile) {
  let current = useNode.parent;
  while (current && current !== sourceFile) {
    if (
      (ts.isFunctionDeclaration(current) ||
        ts.isFunctionExpression(current) ||
        ts.isArrowFunction(current) ||
        ts.isMethodDeclaration(current) ||
        ts.isConstructorDeclaration(current)) &&
      parametersDeclareName(current, targetName)
    ) {
      return true;
    }
    if (ts.isBlock(current) && blockDeclaresNameBeforeUse(current, targetName, useNode, sourceFile)) return true;
    if (ts.isForStatement(current) && forInitializerDeclaresName(current.initializer, targetName)) return true;
    if ((ts.isForOfStatement(current) || ts.isForInStatement(current)) && forInOfInitializerDeclaresName(current.initializer, targetName)) return true;
    if (ts.isCatchClause(current) && current.variableDeclaration && declaresNameInBindingName(current.variableDeclaration.name, targetName)) return true;
    if (ts.isWithStatement(current)) return true;
    current = current.parent;
  }
  return false;
}

function identifierIsShadowed(useNode, targetName, sourceFile) {
  return sourceFileImportDeclaresName(sourceFile, targetName) || identifierIsLocallyShadowed(useNode, targetName, sourceFile);
}

function envPlaceholderFromAccess(node) {
  function isProcessEnv(expr) {
    return (
      ts.isPropertyAccessExpression(expr) &&
      expr.name.text === "env" &&
      ts.isIdentifier(expr.expression) &&
      expr.expression.text === "process"
    );
  }
  function isImportMetaEnv(expr) {
    return (
      ts.isPropertyAccessExpression(expr) &&
      expr.name.text === "env" &&
      ts.isMetaProperty(expr.expression) &&
      expr.expression.keywordToken === ts.SyntaxKind.ImportKeyword &&
      expr.expression.name.text === "meta"
    );
  }
  if (ts.isPropertyAccessExpression(node) && (isProcessEnv(node.expression) || isImportMetaEnv(node.expression))) {
    return `\${env:${node.name.text}}`;
  }
  if (
    ts.isElementAccessExpression(node) &&
    (isProcessEnv(node.expression) || isImportMetaEnv(node.expression)) &&
    ts.isStringLiteral(node.argumentExpression)
  ) {
    return `\${env:${node.argumentExpression.text}}`;
  }
  return null;
}

function resolveEndpointExpression(node, sourceFile, bindings) {
  const literal = stringLiteralValue(node);
  if (literal != null) return { kind: "resolved", value: literal, raw: literal };
  const env = envPlaceholderFromAccess(node);
  if (env != null) return { kind: "env", value: env, raw: rawNodeText(node, sourceFile) };
  if (ts.isIdentifier(node)) {
    if (!bindings.has(node.text) || identifierIsShadowed(node, node.text, sourceFile)) {
      return { kind: "unresolved", value: null, raw: rawNodeText(node, sourceFile) };
    }
    return { kind: "resolved", value: bindings.get(node.text), raw: node.text };
  }
  if (ts.isTemplateExpression(node)) {
    let value = node.head.text;
    let hostUnresolved = false;
    for (const span of node.templateSpans) {
      const resolved = resolveEndpointExpression(span.expression, sourceFile, bindings);
      if (resolved.kind === "env") {
        value += resolved.value;
        hostUnresolved = true;
      } else if (resolved.kind === "resolved") {
        value += resolved.value;
      } else {
        value += "{}";
      }
      value += span.literal.text;
    }
    return { kind: hostUnresolved ? "env" : "resolved", value, raw: rawNodeText(node, sourceFile) };
  }
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const left = resolveEndpointExpression(node.left, sourceFile, bindings);
    const right = resolveEndpointExpression(node.right, sourceFile, bindings);
    if ((left.kind === "resolved" || left.kind === "env") && (right.kind === "resolved" || right.kind === "env")) {
      return {
        kind: left.kind === "env" || right.kind === "env" ? "env" : "resolved",
        value: `${left.value}${right.value}`,
        raw: rawNodeText(node, sourceFile),
      };
    }
  }
  return { kind: "unresolved", value: null, raw: rawNodeText(node, sourceFile) };
}

function splitResolvedEndpointTarget(value) {
  const trimmed = value.trim();
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    try {
      const parsed = new URL(trimmed);
      const host = parsed.hostname || null;
      const external = host != null && host !== "localhost" && host !== "127.0.0.1";
      return { kind: external ? "external" : "resolved", path: parsed.pathname || "/", host, raw_target: trimmed };
    } catch {
      return { kind: "unresolved", path: null, host: null, raw_target: trimmed };
    }
  }
  if (trimmed.startsWith("${env:")) {
    const hostEnd = trimmed.indexOf("}");
    if (hostEnd >= 0) {
      const pathStart = trimmed.indexOf("/", hostEnd + 1);
      if (pathStart === hostEnd + 1 && !trimmed.slice(pathStart).includes("${env:")) {
        return {
          kind: "host_unresolved",
          path: trimmed.slice(pathStart) || "/",
          host: trimmed.slice(0, hostEnd + 1),
          raw_target: trimmed,
        };
      }
    }
    return { kind: "unresolved", path: null, host: null, raw_target: trimmed };
  }
  if (!trimmed.startsWith("/")) return { kind: "unresolved", path: null, host: null, raw_target: trimmed };
  return { kind: "resolved", path: trimmed, host: null, raw_target: trimmed };
}

function resolveEndpointTarget(node, sourceFile, bindings) {
  const expression = resolveEndpointExpression(node, sourceFile, bindings);
  if (expression.kind === "unresolved" || expression.value == null) {
    return { kind: "unresolved", path: null, host: null, raw_target: expression.raw };
  }
  const target = splitResolvedEndpointTarget(expression.value);
  if (target.kind === "host_unresolved" || target.kind === "resolved" || target.kind === "external") return target;
  return { kind: "unresolved", path: null, host: null, raw_target: expression.raw };
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

function requireCallModule(node) {
  if (
    ts.isCallExpression(node) &&
    ts.isIdentifier(node.expression) &&
    node.expression.text === "require" &&
    node.arguments.length === 1 &&
    ts.isStringLiteral(node.arguments[0])
  ) {
    return node.arguments[0].text;
  }
  return null;
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

function collectFastifyFactories(sourceFile) {
  const factories = new Set();
  for (const statement of sourceFile.statements) {
    if (ts.isImportDeclaration(statement) && ts.isStringLiteral(statement.moduleSpecifier) && statement.moduleSpecifier.text === "fastify") {
      const clause = statement.importClause;
      if (clause?.name) factories.add(clause.name.text);
      if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const element of clause.namedBindings.elements) {
          if ((element.propertyName ?? element.name).text === "fastify") factories.add(element.name.text);
        }
      }
      continue;
    }
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name) && declaration.initializer && isRequireCall(declaration.initializer, "fastify")) {
          factories.add(declaration.name.text);
        }
      }
    }
  }
  return factories;
}

function collectFastifyReceivers(sourceFile) {
  const factories = collectFastifyFactories(sourceFile);
  const receivers = new Set();
  function visit(node) {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      ts.isCallExpression(node.initializer) &&
      ts.isIdentifier(node.initializer.expression) &&
      factories.has(node.initializer.expression.text)
    ) {
      receivers.add(node.name.text);
    }
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer &&
      ts.isCallExpression(node.initializer) &&
      isRequireCall(node.initializer.expression, "fastify")
    ) {
      receivers.add(node.name.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return receivers;
}

function directFastifyRoute(node, sourceFile, receivers) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return null;
  const method = node.expression.name.text;
  if (!EXPRESS_ROUTE_METHODS.has(method)) return null;
  if (!ts.isIdentifier(node.expression.expression) || !receivers.has(node.expression.expression.text)) return null;
  if (node.arguments.length < 1) return null;
  const routePath = stringLiteralValue(node.arguments[0]);
  if (routePath == null) return null;
  return { method, path: routePath, line: lineOf(sourceFile, node.expression.getStart(sourceFile)), source_kind: `fastify_${method}` };
}

function fastifyRouteObject(node, sourceFile, receivers) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return null;
  if (node.expression.name.text !== "route") return null;
  if (!ts.isIdentifier(node.expression.expression) || !receivers.has(node.expression.expression.text)) return null;
  if (node.arguments.length < 1 || !ts.isObjectLiteralExpression(node.arguments[0])) return null;
  const routeObject = node.arguments[0];
  if (objectLiteralHasDynamicProperty(routeObject)) return null;
  const pathNode = objectLiteralProperty(routeObject, "url") ?? objectLiteralProperty(routeObject, "path");
  const hasMethodProperty = objectLiteralHasProperty(routeObject, "method");
  const methodNode = objectLiteralProperty(routeObject, "method");
  const routePath = pathNode ? stringLiteralValue(pathNode) : null;
  if (routePath == null) return null;
  const method = methodNode ? stringLiteralValue(methodNode) : null;
  if (hasMethodProperty && method == null) return null;
  return {
    method: method ? method.toLowerCase() : "all",
    path: routePath,
    line: lineOf(sourceFile, node.expression.getStart(sourceFile)),
    source_kind: "fastify_route",
  };
}

function collectFastifyRoutes(sourceFile) {
  const receivers = collectFastifyReceivers(sourceFile);
  if (receivers.size === 0) return [];
  const routes = [];
  function visit(node) {
    const route = directFastifyRoute(node, sourceFile, receivers) ?? fastifyRouteObject(node, sourceFile, receivers);
    if (route) routes.push(route);
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return routes;
}

function collectKoaRouterFactories(sourceFile) {
  const factories = new Set();
  for (const statement of sourceFile.statements) {
    if (
      ts.isImportDeclaration(statement) &&
      ts.isStringLiteral(statement.moduleSpecifier) &&
      (statement.moduleSpecifier.text === "@koa/router" || statement.moduleSpecifier.text === "koa-router")
    ) {
      const clause = statement.importClause;
      if (clause?.name) factories.add(clause.name.text);
      if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) factories.add(clause.namedBindings.name.text);
      if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const element of clause.namedBindings.elements) {
          const importedName = (element.propertyName ?? element.name).text;
          if (importedName === "Router" || importedName === "default") factories.add(element.name.text);
        }
      }
      continue;
    }
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue;
        const moduleName = requireCallModule(declaration.initializer);
        if (moduleName === "@koa/router" || moduleName === "koa-router") factories.add(declaration.name.text);
      }
    }
  }
  return factories;
}

function isKoaRouterInstance(node, factories) {
  if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && factories.has(node.expression.text)) return true;
  if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && factories.has(node.expression.text)) return true;
  if (ts.isCallExpression(node) && (isRequireCall(node.expression, "@koa/router") || isRequireCall(node.expression, "koa-router"))) return true;
  return false;
}

function collectKoaReceivers(sourceFile) {
  const factories = collectKoaRouterFactories(sourceFile);
  const receivers = new Set();
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && isKoaRouterInstance(node.initializer, factories)) {
      receivers.add(node.name.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return receivers;
}

function directKoaRoute(node, sourceFile, receivers) {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return null;
  const method = node.expression.name.text;
  if (!EXPRESS_ROUTE_METHODS.has(method)) return null;
  if (!ts.isIdentifier(node.expression.expression) || !receivers.has(node.expression.expression.text)) return null;
  if (node.arguments.length < 1) return null;
  const routePath = stringLiteralValue(node.arguments[0]);
  if (routePath == null) return null;
  return { method, path: routePath, line: lineOf(sourceFile, node.expression.getStart(sourceFile)), source_kind: `koa_${method}` };
}

function collectKoaRoutes(sourceFile) {
  const receivers = collectKoaReceivers(sourceFile);
  if (receivers.size === 0) return [];
  const routes = [];
  function visit(node) {
    const route = directKoaRoute(node, sourceFile, receivers);
    if (route) routes.push(route);
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return routes;
}

function collectServerRoutes(sourceFile) {
  return [...collectExpressRoutes(sourceFile), ...collectFastifyRoutes(sourceFile), ...collectKoaRoutes(sourceFile)];
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

function propertyNameText(name) {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text;
  return null;
}

function objectLiteralProperty(objectNode, propertyName) {
  if (!ts.isObjectLiteralExpression(objectNode)) return null;
  for (const property of objectNode.properties) {
    if (!ts.isPropertyAssignment(property)) continue;
    if (propertyNameText(property.name) === propertyName) return property.initializer;
  }
  return null;
}

function objectLiteralHasProperty(objectNode, propertyName) {
  if (!ts.isObjectLiteralExpression(objectNode)) return false;
  for (const property of objectNode.properties) {
    if (ts.isPropertyAssignment(property) || ts.isShorthandPropertyAssignment(property) || ts.isMethodDeclaration(property)) {
      if (propertyNameText(property.name) === propertyName) return true;
    }
  }
  return false;
}

function objectLiteralHasDynamicProperty(objectNode) {
  if (!ts.isObjectLiteralExpression(objectNode)) return false;
  return objectNode.properties.some(
    (property) =>
      ts.isSpreadAssignment(property) ||
      ((ts.isPropertyAssignment(property) || ts.isShorthandPropertyAssignment(property) || ts.isMethodDeclaration(property)) &&
        property.name != null &&
        ts.isComputedPropertyName(property.name))
  );
}

function axiosCreateClientInfo(name, initializer, sourceFile, axiosLocals, bindings) {
  if (
    !initializer ||
    !ts.isCallExpression(initializer) ||
    !ts.isPropertyAccessExpression(initializer.expression) ||
    initializer.expression.name.text !== "create" ||
    !ts.isIdentifier(initializer.expression.expression) ||
    !axiosLocals.has(initializer.expression.expression.text)
  ) {
    return null;
  }
  let baseUrl = null;
  if (initializer.arguments.length >= 1 && ts.isObjectLiteralExpression(initializer.arguments[0])) {
    const baseUrlNode = objectLiteralProperty(initializer.arguments[0], "baseURL");
    if (baseUrlNode) baseUrl = resolveEndpointExpression(baseUrlNode, sourceFile, bindings);
  }
  return {
    local_name: name,
    base_url: baseUrl,
    defining_line: lineOf(sourceFile, initializer.getStart(sourceFile)),
  };
}

function collectAxiosClients(sourceFile, axiosLocals, bindings) {
  const clients = new Set();
  const baseUrls = new Map();
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
      const clientInfo = axiosCreateClientInfo(node.name.text, node.initializer, sourceFile, axiosLocals, bindings);
      if (clientInfo) {
        clients.add(node.name.text);
        if (clientInfo.base_url) baseUrls.set(node.name.text, clientInfo.base_url);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return { clients, baseUrls };
}

function statementHasExportModifier(statement) {
  return statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword) ?? false;
}

function collectTopLevelAxiosClientInfos(sourceFile, axiosLocals, bindings) {
  const clients = new Map();
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name)) continue;
      const clientInfo = axiosCreateClientInfo(declaration.name.text, declaration.initializer, sourceFile, axiosLocals, bindings);
      if (clientInfo) clients.set(declaration.name.text, clientInfo);
    }
  }
  return clients;
}

function collectModuleClients(sourceFile, axiosLocals, bindings) {
  const localClients = collectTopLevelAxiosClientInfos(sourceFile, axiosLocals, bindings);
  const moduleClients = { default: null, named: {} };

  for (const statement of sourceFile.statements) {
    if (ts.isVariableStatement(statement) && statementHasExportModifier(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name)) continue;
        const clientInfo = localClients.get(declaration.name.text);
        if (clientInfo) moduleClients.named[declaration.name.text] = clientInfo;
      }
      continue;
    }

    if (ts.isExportAssignment(statement) && ts.isIdentifier(statement.expression)) {
      const clientInfo = localClients.get(statement.expression.text);
      if (clientInfo) moduleClients.default = clientInfo;
      continue;
    }
    if (ts.isExportAssignment(statement)) {
      const clientInfo = axiosCreateClientInfo("default", statement.expression, sourceFile, axiosLocals, bindings);
      if (clientInfo) moduleClients.default = clientInfo;
      continue;
    }

    if (ts.isExportDeclaration(statement) && !statement.moduleSpecifier && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
      for (const element of statement.exportClause.elements) {
        const localName = (element.propertyName ?? element.name).text;
        const exportName = element.name.text;
        const clientInfo = localClients.get(localName);
        if (!clientInfo) continue;
        if (exportName === "default") {
          moduleClients.default = clientInfo;
        } else {
          moduleClients.named[exportName] = clientInfo;
        }
      }
    }
  }

  return moduleClients;
}

function methodFromOptionsLike(node) {
  const methodNode = objectLiteralProperty(node, "method");
  if (!methodNode) return null;
  const value = stringLiteralValue(methodNode);
  return value == null ? null : value.toUpperCase();
}

function composedTargetWithBaseUrl(targetNode, sourceFile, bindings, baseUrlExpression) {
  const target = resolveEndpointExpression(targetNode, sourceFile, bindings);
  if (!baseUrlExpression || target.kind === "unresolved" || target.value == null) return resolveEndpointTarget(targetNode, sourceFile, bindings);
  const targetValue = target.value.trim();
  if (targetValue.startsWith("http://") || targetValue.startsWith("https://") || targetValue.startsWith("${env:")) {
    return resolveEndpointTarget(targetNode, sourceFile, bindings);
  }
  if (baseUrlExpression.kind !== "resolved" && baseUrlExpression.kind !== "env") return { kind: "unresolved", path: null, host: null, raw_target: target.raw };
  const baseValue = String(baseUrlExpression.value).trim();
  const combined = `${baseValue.replace(/\/+$/, "")}/${targetValue.replace(/^\/+/, "")}`;
  const resolved = splitResolvedEndpointTarget(combined);
  return resolved.kind === "unresolved" ? { kind: "unresolved", path: null, host: null, raw_target: target.raw } : resolved;
}

function rowFromTarget(target, method, line, sourceKind) {
  if (target.kind === "external") {
    return { external: true, host: target.host, path: target.path, raw_target: target.raw_target, line, source_kind: sourceKind };
  }
  if (target.kind === "unresolved") {
    return { unresolved: true, raw_target: target.raw_target, line, source_kind: sourceKind };
  }
  return {
    method: method ?? "ANY",
    path: target.path,
    host: target.host,
    raw_target: target.raw_target,
    line,
    source_kind: sourceKind,
    confidence: target.kind === "host_unresolved" ? "host_unresolved_path_resolved" : null,
  };
}

function axiosConfigTarget(configNode, sourceFile, bindings, baseUrlExpression) {
  if (!ts.isObjectLiteralExpression(configNode)) return { target: { kind: "unresolved", path: null, host: null, raw_target: rawNodeText(configNode, sourceFile) }, method: null };
  const urlNode = objectLiteralProperty(configNode, "url");
  if (!urlNode) return { target: { kind: "unresolved", path: null, host: null, raw_target: rawNodeText(configNode, sourceFile) }, method: null };
  const baseUrlNode = objectLiteralProperty(configNode, "baseURL");
  const effectiveBaseUrl = baseUrlNode ? resolveEndpointExpression(baseUrlNode, sourceFile, bindings) : baseUrlExpression;
  return {
    target: composedTargetWithBaseUrl(urlNode, sourceFile, bindings, effectiveBaseUrl),
    method: methodFromOptionsLike(configNode),
  };
}

function importedBindingsByLocal(sourceFile) {
  const bindings = new Map();
  const duplicateLocals = new Set();
  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    if (statement.moduleSpecifier.text === "axios") continue;
    const clause = statement.importClause;
    if (!clause || clause.isTypeOnly) continue;

    function addBinding(localName, importedName) {
      if (bindings.has(localName)) duplicateLocals.add(localName);
      bindings.set(localName, { import_source: statement.moduleSpecifier.text, imported_name: importedName });
    }

    if (clause.name) addBinding(clause.name.text, "default");
    if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
      for (const element of clause.namedBindings.elements) {
        addBinding(element.name.text, (element.propertyName ?? element.name).text);
      }
    }
    if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
      addBinding(clause.namedBindings.name.text, clause.namedBindings.name.text);
    }
  }
  for (const localName of duplicateLocals) bindings.delete(localName);
  return bindings;
}

function targetExpressionFromConfig(configNode, sourceFile, bindings) {
  if (!ts.isObjectLiteralExpression(configNode)) return { target: { kind: "unresolved", value: null, raw: rawNodeText(configNode, sourceFile) }, method: null };
  const urlNode = objectLiteralProperty(configNode, "url");
  if (!urlNode) return { target: { kind: "unresolved", value: null, raw: rawNodeText(configNode, sourceFile) }, method: null };
  const baseUrlNode = objectLiteralProperty(configNode, "baseURL");
  return {
    target: resolveEndpointExpression(urlNode, sourceFile, bindings),
    method: methodFromOptionsLike(configNode),
    base_url: baseUrlNode ? resolveEndpointExpression(baseUrlNode, sourceFile, bindings) : null,
  };
}

function importedClientCallFromNode(node, sourceFile, importedBindings, bindings) {
  if (!ts.isCallExpression(node)) return null;

  if (ts.isIdentifier(node.expression) && importedBindings.has(node.expression.text)) {
    const receiver = node.expression.text;
    if (identifierIsLocallyShadowed(node.expression, receiver, sourceFile) || node.arguments.length < 1) return null;
    const binding = importedBindings.get(receiver);
    const firstArg = node.arguments[0];
    const target = ts.isObjectLiteralExpression(firstArg)
      ? targetExpressionFromConfig(firstArg, sourceFile, bindings)
      : { target: resolveEndpointExpression(firstArg, sourceFile, bindings), method: "GET" };
    return {
      source_kind: "imported_axios_call",
      receiver_local: receiver,
      imported_name: binding.imported_name,
      import_source: binding.import_source,
      method: target.method ?? (ts.isObjectLiteralExpression(firstArg) ? "ANY" : "GET"),
      target: target.target,
      base_url: target.base_url ?? null,
      raw_target: target.target.raw,
      line: lineOf(sourceFile, node.expression.getStart(sourceFile)),
    };
  }

  if (!ts.isPropertyAccessExpression(node.expression) || !ts.isIdentifier(node.expression.expression)) return null;
  const receiver = node.expression.expression.text;
  if (!importedBindings.has(receiver) || identifierIsLocallyShadowed(node.expression.expression, receiver, sourceFile)) return null;

  const property = node.expression.name.text;
  if (property === "request") {
    if (node.arguments.length < 1) return null;
    const target = targetExpressionFromConfig(node.arguments[0], sourceFile, bindings);
    const binding = importedBindings.get(receiver);
    return {
      source_kind: "imported_axios_call",
      receiver_local: receiver,
      imported_name: binding.imported_name,
      import_source: binding.import_source,
      method: target.method ?? "ANY",
      target: target.target,
      base_url: target.base_url ?? null,
      raw_target: target.target.raw,
      line: lineOf(sourceFile, node.expression.getStart(sourceFile)),
    };
  }
  if (!HTTP_METHODS.has(property) || node.arguments.length < 1) return null;

  const binding = importedBindings.get(receiver);
  const target = resolveEndpointExpression(node.arguments[0], sourceFile, bindings);
  return {
    source_kind: "imported_axios_call",
    receiver_local: receiver,
    imported_name: binding.imported_name,
    import_source: binding.import_source,
    method: property.toUpperCase(),
    target,
    raw_target: target.raw,
    line: lineOf(sourceFile, node.expression.getStart(sourceFile)),
  };
}

function clientCallFromNode(node, sourceFile, axiosLocals, axiosClients, axiosClientBaseUrls, bindings) {
  if (!ts.isCallExpression(node)) return null;
  if (ts.isIdentifier(node.expression) && node.expression.text === "fetch") {
    if (node.arguments.length < 1) return null;
    const target = resolveEndpointTarget(node.arguments[0], sourceFile, bindings);
    const method = node.arguments.length >= 2 ? methodFromOptionsLike(node.arguments[1]) : null;
    return rowFromTarget(target, method, lineOf(sourceFile, node.expression.getStart(sourceFile)), "fetch_call");
  }

  if (ts.isIdentifier(node.expression) && axiosLocals.has(node.expression.text)) {
    if (node.arguments.length < 1) return null;
    const firstArg = node.arguments[0];
    if (!ts.isObjectLiteralExpression(firstArg)) {
      const target = resolveEndpointTarget(firstArg, sourceFile, bindings);
      return rowFromTarget(target, "GET", lineOf(sourceFile, node.expression.getStart(sourceFile)), "axios_call");
    }
    const { target, method } = axiosConfigTarget(firstArg, sourceFile, bindings, null);
    return rowFromTarget(target, method, lineOf(sourceFile, node.expression.getStart(sourceFile)), "axios_call");
  }

  if (ts.isIdentifier(node.expression) && axiosClients.has(node.expression.text)) {
    if (node.arguments.length < 1) return null;
    const firstArg = node.arguments[0];
    const baseUrl = axiosClientBaseUrls.get(node.expression.text);
    if (!ts.isObjectLiteralExpression(firstArg)) {
      const target = composedTargetWithBaseUrl(firstArg, sourceFile, bindings, baseUrl);
      return rowFromTarget(target, "GET", lineOf(sourceFile, node.expression.getStart(sourceFile)), "axios_call");
    }
    const { target, method } = axiosConfigTarget(firstArg, sourceFile, bindings, baseUrl);
    return rowFromTarget(target, method, lineOf(sourceFile, node.expression.getStart(sourceFile)), "axios_call");
  }

  if (!ts.isPropertyAccessExpression(node.expression) || !ts.isIdentifier(node.expression.expression)) return null;
  const receiver = node.expression.expression.text;
  if (!axiosLocals.has(receiver) && !axiosClients.has(receiver)) return null;
  const property = node.expression.name.text;
  if (property === "request") {
    if (node.arguments.length < 1) return null;
    const baseUrl = axiosClients.has(receiver) ? axiosClientBaseUrls.get(receiver) : null;
    const { target, method } = axiosConfigTarget(node.arguments[0], sourceFile, bindings, baseUrl);
    return rowFromTarget(target, method, lineOf(sourceFile, node.expression.getStart(sourceFile)), "axios_call");
  }
  if (!HTTP_METHODS.has(property) || node.arguments.length < 1) return null;
  const baseUrl = axiosClients.has(receiver) ? axiosClientBaseUrls.get(receiver) : null;
  const target = composedTargetWithBaseUrl(node.arguments[0], sourceFile, bindings, baseUrl);
  return rowFromTarget(target, property.toUpperCase(), lineOf(sourceFile, node.expression.getStart(sourceFile)), "axios_call");
}

function collectClientEndpointCalls(sourceFile) {
  const axiosLocals = collectAxiosLocals(sourceFile);
  const bindings = collectTopLevelLiteralBindings(sourceFile);
  const { clients: axiosClients, baseUrls: axiosClientBaseUrls } = collectAxiosClients(sourceFile, axiosLocals, bindings);
  const importedBindings = importedBindingsByLocal(sourceFile);
  const calls = [];
  function visit(node) {
    const call = clientCallFromNode(node, sourceFile, axiosLocals, axiosClients, axiosClientBaseUrls, bindings);
    if (call) calls.push(call);
    const importedCall = importedClientCallFromNode(node, sourceFile, importedBindings, bindings);
    if (importedCall) calls.push(importedCall);
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
  const axiosLocals = collectAxiosLocals(sourceFile);
  const literalBindings = collectTopLevelLiteralBindings(sourceFile);
  const serverRoutes = collectServerRoutes(sourceFile);
  output[relativePath] = {
    parse_diagnostics: sourceFile.parseDiagnostics.map((diagnostic) => ({
      message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
      line: diagnostic.start == null ? 1 : lineOf(sourceFile, diagnostic.start),
    })),
    imports: collectImports(sourceFile),
    server_routes: serverRoutes,
    express_routes: serverRoutes,
    client_endpoint_calls: collectClientEndpointCalls(sourceFile),
    module_clients: collectModuleClients(sourceFile, axiosLocals, literalBindings),
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
