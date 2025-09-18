# upload_to_blob.py
import os, sys
import re
from azure.storage.blob import BlobServiceClient
from datetime import datetime

# simple sanitizer for blob path
def sanitize_blob_path(p: str) -> str:
    # replace control chars, backslashes, and problematic punctuation with '-'
    # allow common safe chars (alphanum, ., -, _, /)
    p = re.sub(r'[\\\x00-\x1f]', '-', p)
    p = re.sub(r'[\s\(\)\$]+', '-', p)
    # collapse multiple dashes
    p = re.sub(r'-{2,}', '-', p)
    # strip leading/trailing hyphens
    return p.strip('-')

def upload_file(local_path, container='trends-raw', dest_path=None, overwrite=True):
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING not set in env")
    svc = BlobServiceClient.from_connection_string(conn_str)


    if not dest_path:
        today = datetime.utcnow().strftime("%Y-%m-%d")
    base = os.path.basename(local_path)
    dest_path = f"raw/site/{today}/{base}"


    # sanitize destination
    dest_path = sanitize_blob_path(dest_path)


    blob = svc.get_blob_client(container=container, blob=dest_path)
    with open(local_path, "rb") as f:
        blob.upload_blob(f, overwrite=overwrite)
    print("Uploaded to", f"{container}/{dest_path}")
    return dest_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_to_blob.py <local_file> [container] [dest_path]")
        sys.exit(1)
    local = sys.argv[1]
    container = sys.argv[2] if len(sys.argv) > 2 else "trends-raw"
    dest = sys.argv[3] if len(sys.argv) > 3 else None
    upload_file(local, container=container, dest_path=dest)
