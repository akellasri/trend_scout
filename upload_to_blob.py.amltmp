# upload_to_blob.py
import os, sys
from azure.storage.blob import BlobServiceClient
from datetime import datetime

def upload_file(local_path, container='trends-raw', dest_path=None):
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("AZURE_STORAGE_CONNECTION_STRING not set in env")
    svc = BlobServiceClient.from_connection_string(conn_str)
    if not dest_path:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        base = os.path.basename(local_path)
        dest_path = f"raw/site/{today}/{base}"
    blob = svc.get_blob_client(container=container, blob=dest_path)
    with open(local_path, "rb") as f:
        blob.upload_blob(f, overwrite=True)
    print("Uploaded to", dest_path)
    return dest_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_to_blob.py <local_file> [container] [dest_path]")
        sys.exit(1)
    local = sys.argv[1]
    container = sys.argv[2] if len(sys.argv) > 2 else "trends-raw"
    dest = sys.argv[3] if len(sys.argv) > 3 else None
    upload_file(local, container=container, dest_path=dest)
