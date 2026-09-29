# Research evidence

- `raw/`: public API responses, original timestamps and failures; ignored by Git because collectors append here.
- `evidence/public-market-evidence.tar.gz`: frozen compressed copy of the completed public experiment, committed for offline reproduction.
- `evidence/manifest.json`: SHA-256 of the archive and each original file.
- `derived/`: inventories, per-observation measurements, summaries and quality records produced by the Python scripts.

Restore the archive from the repository root with `tar -xzf data/evidence/public-market-evidence.tar.gz`. It contains only relative `data/raw/` paths. Then run `.venv/bin/python scripts/rebuild.py`.

The source datasets include public market data and published documentation only. `.env`, account credentials, private keys and wallet data are excluded. Failed requests and rejected market matches are preserved where collected. `rh_quote_candles_raw.json` is an additional public quote-unit historical backfill saved beside the history analysis; its source URLs and retrieval times are retained inside the file.

Some manifests include original absolute workspace paths for provenance; reproducible script defaults point to relative repository locations. Snapshot files are not silently refreshed during offline analysis. Separate runs have separate sampling windows; they must not be treated as a continuous, complete market tape.
