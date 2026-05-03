# V2 Worker

The worker entrypoint is intentionally separate from the API process.

The first implementation preserves the V1 normalization semantics by delegating to the existing background job logic until the PostgreSQL-native job system is completed.

## Run

```bash
../scripts/run_worker.sh
```
