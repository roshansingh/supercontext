# Three-Way Eval: grep vs Claude Code vs SuperContext

**Generated:** 2026-05-24T13:59:26.792875+00:00
**Target:** github/CodeSearchNet (16 queries)

## Summary

| Metric | grep | Claude Code | SuperContext |
|--------|------|-------------|-------------|
| Wins | 0 | 1 | 15 |
| Avg tool calls | 0.9 | 7.1 | 1.0 |
| Avg latency (ms) | 9.0 | 23.2 | 135.8 |
| Total tool calls | 16 | 114 | 16 |

## Per-Query Results

| ID | Description | grep calls | CC calls | SC calls | grep lat | CC lat | SC lat | Winner |
|----|-------------|-----------|---------|---------|---------|--------|--------|--------|
| DEP-01 | Which modules import tensorflow? | 1 | 13 | 1 | 16ms | 13ms | 158ms | supercontext |
| DEP-02 | Which modules import wandb? | 1 | 5 | 1 | 11ms | 11ms | 123ms | supercontext |
| DEP-03 | Which modules import numpy? | 1 | 9 | 1 | 11ms | 12ms | 130ms | supercontext |
| DEP-04 | What are the top internal module dependencies? | 1 | 1 | 1 | 12ms | 11ms | 131ms | supercontext |
| CALL-01 | Who calls get_shape_list? | 1 | 3 | 1 | 9ms | 19ms | 129ms | supercontext |
| CALL-02 | Who calls create_initializer? | 1 | 3 | 1 | 10ms | 19ms | 122ms | supercontext |
| CALL-03 | Who calls dropout? | 1 | 5 | 1 | 9ms | 19ms | 179ms | supercontext |
| CALL-04 | Who calls train_log? | 1 | 4 | 1 | 10ms | 19ms | 143ms | supercontext |
| CALL-05 | Which symbols have the most callers? | 0 | 31 | 1 | 0ms | 6ms | 125ms | supercontext |
| SYM-01 | Symbols in model.py? | 1 | 1 | 1 | 3ms | 0ms | 135ms | supercontext |
| SYM-02 | Symbols in seq_encoder.py? | 1 | 1 | 1 | 3ms | 0ms | 129ms | supercontext |
| BLAST-01 | Blast radius of get_shape_list? | 1 | 4 | 1 | 10ms | 32ms | 135ms | supercontext |
| BLAST-02 | Blast radius of Model.train? | 1 | 15 | 1 | 9ms | 81ms | 138ms | supercontext |
| BLAST-03 | Blast radius of SeqEncoder? | 1 | 15 | 1 | 9ms | 82ms | 138ms | claude_code |
| STRUCT-01 | Who imports src.models.model? | 1 | 2 | 1 | 11ms | 24ms | 123ms | supercontext |
| STRUCT-02 | Who imports seq_encoder? | 1 | 2 | 1 | 12ms | 23ms | 133ms | supercontext |
