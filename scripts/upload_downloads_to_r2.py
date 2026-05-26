import argparse
import mimetypes
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


BASE_DIR = Path(__file__).resolve().parents[1]


def build_client():
    import boto3
    from botocore.config import Config

    endpoint_url = os.environ.get("R2_ENDPOINT_URL")
    if not endpoint_url:
        account_id = os.environ["R2_ACCOUNT_ID"]
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

    return boto3.client(
        service_name="s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("R2_REGION", "auto"),
        config=Config(signature_version="s3v4"),
    )


def require_env():
    required = ("R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
    missing = [key for key in required if not os.environ.get(key)]

    if not os.environ.get("R2_ENDPOINT_URL") and not os.environ.get("R2_ACCOUNT_ID"):
        missing.append("R2_ACCOUNT_ID or R2_ENDPOINT_URL")

    if missing:
        raise SystemExit(f"Missing required environment values: {', '.join(missing)}")


def iter_local_files(source_dir):
    for category_dir in sorted(source_dir.iterdir(), key=lambda path: path.name):
        if not category_dir.is_dir():
            continue

        for file_path in sorted(category_dir.iterdir(), key=lambda path: path.name):
            if file_path.is_file():
                yield category_dir.name, file_path


def object_key(prefix, category, filename):
    key = f"{category}/{filename}"
    return f"{prefix}/{key}" if prefix else key


def main():
    parser = argparse.ArgumentParser(description="Upload local downloads/ files to Cloudflare R2.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned uploads without sending files.")
    args = parser.parse_args()

    require_env()

    source_dir = Path(os.environ.get("DOWNLOAD_FOLDER", BASE_DIR / "downloads")).resolve()
    if not source_dir.exists():
        raise SystemExit(f"Download folder does not exist: {source_dir}")

    bucket = os.environ["R2_BUCKET"]
    prefix = os.environ.get("R2_PREFIX", "downloads").strip("/")
    client = None if args.dry_run else build_client()

    for category, file_path in iter_local_files(source_dir):
        key = object_key(prefix, category, file_path.name)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        print(f"{file_path} -> s3://{bucket}/{key}")

        if args.dry_run:
            continue

        with file_path.open("rb") as file_obj:
            client.upload_fileobj(
                file_obj,
                bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )


if __name__ == "__main__":
    main()
