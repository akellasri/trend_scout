#!/usr/bin/env python3
import os
import sys
import re
import argparse
from azure.storage.blob import BlobServiceClient
from datetime import datetime

def sanitize_segment(seg: str) -> str:
    if seg is None:
        return ""
    seg = re.sub(r'[^A-Za-z0-9\-\._]', '-', seg)
    seg = re.sub(r'-{2,}', '-', seg)
    seg = seg.strip('-.')
    return seg or "item"

def sanitize_blob_path(p: str) -> str:
    if not p:
        return p
    parts = [sanitize_segment(part) for part in p.split('/')]
    parts = [part for part in parts if part]
    return '/'.join(parts)

def upload_file(local_path, container='trends-raw', dest_path=None, overwrite=True):
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING not set in env")
    svc = BlobServiceClient.from_connection_string(conn_str)

    if not dest_path:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        base = os.path.basename(local_path)
        dest_path = f"raw/site/{today}/{base}"

    safe_dest = sanitize_blob_path(dest_path)

    print(f"[upload_to_blob] local='{local_path}' -> container='{container}' blob='{safe_dest}' (raw dest='{dest_path}')")

    blob = svc.get_blob_client(container=container, blob=safe_dest)
    with open(local_path, "rb") as f:
        blob.upload_blob(f, overwrite=overwrite)
    print("Uploaded to", f"{container}/{safe_dest}")
    return safe_dest

def parse_args():
    p = argparse.ArgumentParser(description="Upload a local file to Azure Blob Storage.")
    p.add_argument("local_file", help="local file path to upload")
    p.add_argument("--container", "-c", help="blob container name (default: trends-raw)", default="trends-raw")
    p.add_argument("--dest-path", "-d", help="destination blob path (optional). If omitted a dated path is used.")
    p.add_argument("--no-overwrite", action="store_true", help="do not overwrite existing blob")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    local = args.local_file
    container = args.container
    dest = args.dest_path
    overwrite = not args.no_overwrite
    try:
        upload_file(local, container=container, dest_path=dest, overwrite=overwrite)
    except Exception as e:
        print("ERROR uploading:", str(e))
        raise