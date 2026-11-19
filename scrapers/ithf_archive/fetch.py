"""One-off: download every archived page of an ITHF event folder from the Wayback Machine into the raw cache.

    python -m scrapers.ithf_archive.fetch [--prefix ithf.info/stiga/turnaje2017/ms/] [--out data/ithf_archive/raw]

The Wayback CDX index lists every URL archived under the prefix; for each one the latest 200 snapshot is fetched
raw (``id_`` mode, no Wayback toolbar or rewritten links). Then every page's links inside the folder are checked
against what was fetched, and links with no snapshot are written to ``missing.csv``. Not part of the nightly run.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..common.http import PoliteClient

log = logging.getLogger(__name__)
CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK = "https://web.archive.org/web/{ts}id_/{url}"
HREF = re.compile(rb"""(?:href|src)\s*=\s*["']([^"'#]+)""", re.I)


def norm_key(url: str, prefix_path: str) -> str | None:
    """Folder-relative key of a URL ('open_list.aspx', 'open_kriz.aspx_id_3'); None when outside the folder."""
    parts = urlsplit(url)
    path = parts.path
    i = path.lower().find(prefix_path.lower())
    if i < 0:
        return None
    rel = path[i + len(prefix_path):] or "_dir"
    if parts.query:
        rel += "_" + re.sub(r"[^A-Za-z0-9]+", "_", parts.query)
    return rel.lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="ithf.info/stiga/turnaje2017/ms/")
    ap.add_argument("--out", default="data/ithf_archive/wc2017/raw")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    prefix_path = "/" + args.prefix.split("/", 1)[1]
    client = PoliteClient(min_interval=1.5, timeout=120, retries=6, backoff=5)

    resp = client.get(CDX, params={"url": args.prefix, "matchType": "prefix", "output": "json",
                                   "fl": "urlkey,timestamp,original,statuscode,mimetype"}, check_robots=False)
    resp.raise_for_status()
    rows = resp.json()[1:]
    log.info("CDX: %d captures", len(rows))
    best: dict[str, tuple[str, str]] = {}
    for urlkey, ts, original, status, mime in rows:
        if status != "200":
            continue
        key = norm_key(original, prefix_path)
        if key is None:
            continue
        if key not in best or ts > best[key][0]:
            best[key] = (ts, original)

    manifest = []
    links: dict[str, set[str]] = {}
    for key, (ts, original) in sorted(best.items()):
        path = out / (key + ".gz")
        if path.exists() and path.stat().st_size:
            body = gzip.decompress(path.read_bytes())
        else:
            try:
                r = client.get(WAYBACK.format(ts=ts, url=original), check_robots=False)
            except Exception as exc:  # noqa: BLE001 - log and carry on, reported as missing
                log.warning("%s: %s", original, exc)
                manifest.append((key, original, ts, "error", 0))
                continue
            if r.status_code != 200:
                log.warning("%s @%s -> %s", original, ts, r.status_code)
                manifest.append((key, original, ts, r.status_code, 0))
                continue
            body = r.content
            path.write_bytes(gzip.compress(body, mtime=0))
        manifest.append((key, original, ts, 200, len(body)))
        for href in HREF.findall(body):
            target = urljoin(original, href.decode("latin-1").strip())
            k = norm_key(target, prefix_path)
            if k and not k.endswith((".css", ".js", ".gif", ".png", ".jpg", ".ico")):
                links.setdefault(k, set()).add(key)

    with open(out.parent / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "original_url", "timestamp", "status", "bytes"])
        w.writerows(manifest)
    fetched = {m[0] for m in manifest if m[3] == 200}
    missing = sorted(k for k in links if k not in fetched)
    with open(out.parent / "missing.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "linked_from"])
        for k in missing:
            w.writerow([k, " ".join(sorted(links[k]))])
    log.info("fetched %d pages, %d linked pages have no snapshot", len(fetched), len(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
