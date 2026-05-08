# Low Query Rerun: True Loop Parser-Backed TS/JS KG

Status: evaluation rerun  
Date: 2026-05-08  
Snapshot: `data/kg_runs/true_loop`  
Repo: `/Users/maruti/work/true_loop`  
Commit: `df29bbdc9d224a6c7c3e345719498d996509e438`  
Extractors: `python_ast_v0`, `typescript_compiler_api_v0`

## Summary

| Result | Before PR3 | After PR3 |
|---|---:|---:|
| Pass | 7 | 8 |
| Partial | 6 | 6 |
| Fail | 1 | 0 |
| Blocked / not testable | 1 | 1 |

Main finding: parser-backed TS/JS extraction removes the parser-coverage failure from PR2. The remaining gaps are product-query layer gaps, not raw TS/JS parsing: symbol disambiguation, first-class symbol/evidence commands, service URN rendering, and candidate fixtures.

## Snapshot Counts

| Metric | PR2 regex/static | PR3 compiler API | Notes |
|---|---:|---:|---|
| Python files | 1 | 1 | No corpus change. |
| TypeScript/JavaScript files | 185 | 185 | No corpus change. |
| Entities | 1304 | 1338 | Compiler API captures slightly more top-level symbols/packages. |
| Code modules | 186 | 186 | Stable. |
| Code symbols | 1047 | 1059 | Compiler API captures declarations more reliably. |
| External packages | 69 | 91 | Import declarations and re-exports are parsed structurally. |
| Facts | 2958 | 2880 | Call facts are less noisy because regex-only call matches are gone. |
| Evidence rows | 5794 | 5400 | Fewer noisy call facts means fewer evidence rows. |
| Coverage rows | 2 | 2 | TS/JS coverage is now `PARSES` / `instrumented`. |

## Results

| ID | Status | Rerun observation | Finding |
|---|---|---|---|
| Q001 | Pass | React importers still return with citations, e.g. `src/app/(app)/dashboard/page.tsx:3`. | No regression. |
| Q002 | Pass | `@prisma/client` direct imports still return with `category=third_party`. | No regression. |
| Q003 | Partial | `generateResponse -> generateResponseStream` caller still resolves at `src/lib/response-generator.ts:635`. | Correct for the fixture, but still lacks explicit ambiguity response. |
| Q004 | Partial | `generateResponseStream` callees now come from compiler AST call expressions, including `randomUUID`, `createTimer`, `getCompanyPrompt`, `appendSessionLog`, and local helper calls. | Better evidence quality; still static and not type-aware. |
| Q005 | Partial | Symbols in `src/lib/response-generator.ts` are captured from AST declarations, including interfaces, functions, and exported values. | Data exists, but no `symbols-in-file` command yet. |
| Q006 | Pass | TS/JS coverage now reports `PARSES` / `instrumented` from `typescript_compiler_api_v0`. | Parser-backed coverage gap fixed. |
| Q007 | Partial | Evidence for `generateResponse -> generateResponseStream` remains commit-pinned at line 635. | Still needs first-class evidence query / Mode A command. |
| Q008 | Pass | `dependency-info fs` returns `node_builtin`. | No regression. |
| Q009 | Pass | `top-dependencies` excludes Node builtins and returns `next`, `react`, `vitest`, `@prisma/client`, etc. | No regression. |
| Q010 | Partial | Symbol candidates such as `finalizeSession` still exist with file/line evidence. | Still needs dedicated symbol lookup and ambiguity metadata. |
| Q011 | Partial | Service/repo identity unchanged; URN remains hash-based. | Separate identity rendering gap. |
| Q012 | Pass | Scoped package imports still normalize correctly. | No regression. |
| Q013 | Pass | Direct caller of `generateResponseStream` remains `generateResponse`. | No regression. |
| Q014 | Blocked / not testable | Snapshot still has no candidate facts. | Needs candidate/enrichment fixture. |
| Q015 | Pass | Summary reports 186 modules, 1059 symbols, 612 imports, 836 calls, and 2 coverage rows. | KG inventory works with compiler-backed TS/JS. |

## Remaining Limits

| Area | Current behavior | Why not v1-blocking yet |
|---|---|---|
| Type-aware references | Calls are syntax-backed, not resolved through TypeScript type checker. | No low-tier query currently fails specifically because of type-aware resolution. |
| Dynamic imports | Static import declarations and CommonJS require are covered; dynamic `import()` is not canonical yet. | No current fixture/query requires it. |
| Inheritance/dynamic dispatch | Not resolved. | No evidence-driven failure yet. |
| Cross-file symbol resolution | Imported calls resolve to imported module/package, not exact exported symbol. | Good enough for current low queries; exact exported-symbol resolution should be a later measured slice. |

## Decision

PR3 validates the parser-backed TS/JS extraction layer and the new language-folder layout. The next implementation slice should still be shared symbol lookup/disambiguation across Python and TS/JS.
