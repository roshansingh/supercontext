# Low Query Run: True Loop TS/JS v0 KG

Status: evaluation run  
Date: 2026-05-07  
Snapshot: `data/kg_runs/true_loop`  
Repo: `/Users/maruti/work/true_loop`  
Commit: `df29bbdc9d224a6c7c3e345719498d996509e438`  
Extractors: `python_ast_v0`, `typescript_static_v0`

## Summary

| Result | Count |
|---|---:|
| Pass | 7 |
| Partial | 6 |
| Fail | 1 |
| Blocked / not testable | 1 |

Main finding: the modular extractor split works. The repo no longer produces a fake Python-only KG; it now indexes `185` TS/JS files, `538` import facts, and `1000` call facts. The biggest remaining risk is that `typescript_static_v0` is regex/static-text based, not a real TypeScript AST extractor.

## Snapshot Counts

| Metric | Value |
|---|---:|
| Python files | 1 |
| TypeScript/JavaScript files | 185 |
| Entities | 1304 |
| Code modules | 186 |
| Code symbols | 1047 |
| External packages | 69 |
| Facts | 2958 |
| Evidence rows | 5794 |
| Coverage rows | 2 |

## Results

| ID | Status | True Loop query used | What we observed | Finding |
|---|---|---|---|---|
| Q001 | Pass | What modules import `react`? | Returned React importers with citations, e.g. `src/app/(app)/dashboard/page.tsx:3`, `feedback/[id]/page.tsx:3`, `history/page.tsx:3`. | Third-party import extraction works for TS/JS. |
| Q002 | Pass | What modules import `@prisma/client` directly? | Returned direct package imports with `category=third_party`, including `src/lib/db.ts:1` and `src/lib/session-finalizer.ts:6`. | Scoped package normalization works. |
| Q003 | Partial | Who calls `generateResponseStream`? | Returned `src.lib.response-generator.generateResponse -> generateResponseStream` at `src/lib/response-generator.ts:635`. | Works for unambiguous same-file symbols, but general symbol ambiguity handling is still missing. |
| Q004 | Partial | What does `generateResponseStream` call directly? | Returned calls to local functions and imported modules, e.g. `normalizeSimpleModeReplayContent`, `getCompanyPrompt`, `appendSessionLog`, `crypto.randomUUID`. | Useful, but heuristic; no TS compiler/tree-sitter validation yet. |
| Q005 | Partial | Which symbols are defined in `src/lib/response-generator.ts`? | Symbol facts exist, including `GenerateResponseParams`, `generateResponseStream`, and `generateResponse`. | Data exists, but no first-class `symbols-in-file` command yet. |
| Q006 | Fail | Which files could not be parsed or indexed? | TS/JS extractor reports `IMPORTS` coverage as instrumented but does not parse with a real parser, so parse-failure coverage is not meaningful. | Need parser-backed coverage before claiming TS parse health. |
| Q007 | Partial | Show evidence for `generateResponse -> generateResponseStream`. | Evidence exists at `src/lib/response-generator.ts:635` with commit-pinned bytes. | Evidence exists, but no first-class evidence query / Mode A command yet. |
| Q008 | Pass | Is `fs` or `path` third-party or builtin usage? | `dependency-info fs` and `dependency-info path` return `category=node_builtin`. | Node builtin classification works. |
| Q009 | Pass | What are top third-party dependencies by importer count? | `top-dependencies` excludes Node builtins by default. Top results include `next`, `react`, `vitest`, `@prisma/client`, `lucide-react`, and `zod`. | Dependency ranking works for TS/JS package metadata. |
| Q010 | Partial | Find all symbols matching `finalizeSession`. | Returned `finalizeSession` plus related types/interfaces with file/line evidence. | Candidate data exists, but no dedicated symbol lookup / ambiguity metadata. |
| Q011 | Partial | What service identity and URN did this repo produce? | Service slug is `true-loop`; repo is `true_loop`; URN remains opaque hash-based. | Same human-readable URN gap as Mercury. |
| Q012 | Pass | Which modules import `@prisma/client`? | Scoped package import root and distribution name remain `@prisma/client`, with direct citations. | JS package normalization works for scoped packages. |
| Q013 | Pass | What are direct callers of `generateResponseStream`? | Direct caller is `generateResponse` at `src/lib/response-generator.ts:635`. | Reverse call lookup works for this unambiguous TS case. |
| Q014 | Blocked / not testable | Does candidate-only fact appear in default query? | Snapshot has no candidate facts. | Need candidate/enrichment fixture. |
| Q015 | Pass | Compact summary of repo KG. | Summary reports 186 code modules, 1047 code symbols, 538 imports, 1000 calls, 2 coverage rows. | KG inventory works across languages. |

## What Broke Or Looks Weak

| Area | Finding | Impact |
|---|---|---|
| Parser fidelity | TS/JS extractor is regex-based. | Cannot safely claim full parse coverage, exact syntax handling, JSX semantics, or all import/call shapes. |
| Multiline imports | v0 only handles single-line imports/requires. | Some real imports may be missed. |
| Symbol scope | v0 now emits top-level declarations only. | Reduces noise but misses nested/local functions and React component internals. |
| Calls | Calls are heuristic and mostly useful within top-level symbol ranges. | Good for smoke tests; not enough for production impact analysis. |
| Framework semantics | Next.js routes, React components, Prisma schema, and API endpoints are not modeled as product entities yet. | Product-level questions still need graph-building modules beyond source KG. |

## Next Build Recommendation

| Priority | Build slice | Why |
|---|---|---|
| 1 | Parser-backed TS/JS extractor via tree-sitter or TypeScript compiler API | Converts this from heuristic smoke-test support into reliable multi-language extraction. |
| 2 | Shared language extractor interface | The pipeline dispatch exists, but extractors should conform to an explicit interface before adding more languages. |
| 3 | Symbol lookup/disambiguation across Python and TS/JS | Still the biggest low-tier query gap across both Mercury and True Loop. |
| 4 | First-class evidence/symbol query commands | Existing evidence is usable but not surfaced cleanly. |

## Decision

The modular direction is correct. Keep Python and TS/JS extractors separate, avoid forcing all languages through one abstraction too early, and use True Loop as the first non-Python regression fixture.
