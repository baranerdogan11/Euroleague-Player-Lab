"""Writing warehouse tables: shared by warehouse.py, events.py and lineups.py so every table is written the same way."""
import json
import os


def write_parquet(con, folder, name, rows, schema):
    """Write rows (a list of dicts) to <folder>/<name>.parquet with the given schema, a list of (column, duckdb type),
    going through a temporary JSON-lines file so DuckDB applies the types. Returns the number of rows."""
    tmp = os.path.join(folder, f"{name}.jsonl")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps({k: r.get(k) for k, _ in schema}) + "\n")
    cols = ", ".join(f"'{k}': '{t}'" for k, t in schema)
    con.execute(f"copy (select * from read_json('{tmp}', format='newline_delimited', columns={{{cols}}})) to '{os.path.join(folder, name + '.parquet')}' (format parquet, compression zstd)")
    os.remove(tmp)
    return len(rows)


def add_to_manifest(folder, season, counts):
    """Record table row counts in <folder>/manifest.json, keeping the counts other scripts wrote."""
    path = os.path.join(folder, "manifest.json")
    manifest = json.load(open(path)) if os.path.exists(path) else {"season": season, "tables": {}}
    manifest["tables"].update(counts)
    json.dump(manifest, open(path, "w"), indent=1)
