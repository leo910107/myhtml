import json
import os
from pathlib import Path
from urllib.parse import quote

from flask import redirect, send_from_directory


R2_ENV_KEYS = (
    "R2_ACCOUNT_ID",
    "R2_ENDPOINT_URL",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
)
METADATA_DIR = "_site_meta"
METADATA_FILENAME = "categories.json"


def is_safe_path_part(value):
    return bool(value) and value not in {".", "..", METADATA_DIR} and "/" not in value and "\\" not in value


def create_storage(local_download_folder, default_categories=()):
    if not any(os.environ.get(key) for key in R2_ENV_KEYS):
        return LocalFileStorage(local_download_folder, default_categories)

    missing = []
    if not os.environ.get("R2_BUCKET"):
        missing.append("R2_BUCKET")
    if not os.environ.get("R2_ACCESS_KEY_ID"):
        missing.append("R2_ACCESS_KEY_ID")
    if not os.environ.get("R2_SECRET_ACCESS_KEY"):
        missing.append("R2_SECRET_ACCESS_KEY")
    if not os.environ.get("R2_ENDPOINT_URL") and not os.environ.get("R2_ACCOUNT_ID"):
        missing.append("R2_ACCOUNT_ID or R2_ENDPOINT_URL")

    if missing:
        missing_values = ", ".join(missing)
        raise RuntimeError(f"Cloudflare R2 is partially configured. Missing: {missing_values}")

    return R2Storage(default_categories)


class LocalFileStorage:
    name = "local"

    def __init__(self, download_folder, default_categories=()):
        self.download_folder = Path(download_folder).resolve()
        self.default_categories = tuple(default_categories)
        self.metadata_path = self.download_folder / METADATA_DIR / METADATA_FILENAME

    def list_categories(self):
        files_by_category = self.list_files()
        categories = self.read_categories()

        if categories is None:
            categories = [*self.default_categories, *files_by_category.keys()]
            self.write_categories(categories)
        else:
            categories = [*categories, *files_by_category.keys()]

        return sorted(set(categories))

    def list_files(self):
        self.download_folder.mkdir(parents=True, exist_ok=True)
        categorized_files = {}

        for category_path in sorted(self.download_folder.iterdir(), key=lambda path: path.name):
            if not category_path.is_dir() or category_path.name.startswith(".") or category_path.name == METADATA_DIR:
                continue

            files = sorted(path.name for path in category_path.iterdir() if path.is_file())
            if files:
                categorized_files[category_path.name] = files

        return categorized_files

    def usage_stats(self):
        self.download_folder.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        file_count = 0

        for category_path in self.download_folder.iterdir():
            if not category_path.is_dir() or category_path.name.startswith(".") or category_path.name == METADATA_DIR:
                continue

            for file_path in category_path.iterdir():
                if file_path.is_file():
                    file_count += 1
                    total_bytes += file_path.stat().st_size

        return {"file_count": file_count, "total_bytes": total_bytes}

    def add_category(self, category):
        categories = set(self.list_categories())
        categories.add(category)
        self.write_categories(categories)
        (self.download_folder / category).mkdir(parents=True, exist_ok=True)

    def delete_category(self, category):
        if self.list_files().get(category):
            raise ValueError("分類裡還有檔案，請先刪除檔案。")

        categories = set(self.list_categories())
        categories.discard(category)
        self.write_categories(categories)

        category_path = self.download_folder / category
        if category_path.exists() and category_path.is_dir() and not any(category_path.iterdir()):
            category_path.rmdir()

    def save(self, file_storage, category, filename):
        category_path = self.download_folder / category
        category_path.mkdir(parents=True, exist_ok=True)
        file_storage.save(category_path / filename)

    def delete(self, category, filename):
        file_path = (self.download_folder / category / filename).resolve()

        if file_path.is_relative_to(self.download_folder) and file_path.is_file():
            file_path.unlink()

            category_path = file_path.parent
            if not any(category_path.iterdir()):
                category_path.rmdir()

    def download_response(self, category, filename):
        return send_from_directory(
            self.download_folder,
            f"{category}/{filename}",
            as_attachment=True,
        )

    def read_categories(self):
        if not self.metadata_path.exists():
            return None

        with self.metadata_path.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)

        return [category for category in data.get("categories", []) if is_safe_path_part(category)]

    def write_categories(self, categories):
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_categories = sorted({category for category in categories if is_safe_path_part(category)})

        with self.metadata_path.open("w", encoding="utf-8") as file_obj:
            json.dump({"categories": cleaned_categories}, file_obj, ensure_ascii=False, indent=2)


class R2Storage:
    name = "r2"

    def __init__(self, default_categories=()):
        import boto3
        from botocore.config import Config

        self.bucket = os.environ["R2_BUCKET"]
        self.prefix = os.environ.get("R2_PREFIX", "").strip("/")
        self.default_categories = tuple(default_categories)
        self.presigned_url_expires = int(os.environ.get("R2_PRESIGNED_URL_EXPIRES", "600"))

        endpoint_url = os.environ.get("R2_ENDPOINT_URL")
        if not endpoint_url:
            account_id = os.environ["R2_ACCOUNT_ID"]
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        self.client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name=os.environ.get("R2_REGION", "auto"),
            config=Config(signature_version="s3v4"),
        )

    def list_categories(self):
        files_by_category = self.list_files()
        categories = self.read_categories()

        if categories is None:
            categories = [*self.default_categories, *files_by_category.keys()]
            self.write_categories(categories)
        else:
            categories = [*categories, *files_by_category.keys()]

        return sorted(set(categories))

    def list_files(self):
        categorized_files = {}
        paginator = self.client.get_paginator("list_objects_v2")
        list_prefix = f"{self.prefix}/" if self.prefix else ""

        for page in paginator.paginate(Bucket=self.bucket, Prefix=list_prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                relative_key = key[len(list_prefix) :] if list_prefix else key

                if "/" not in relative_key or relative_key.startswith(f"{METADATA_DIR}/"):
                    continue

                category, filename = relative_key.split("/", 1)
                if not is_safe_path_part(category) or not is_safe_path_part(filename):
                    continue

                categorized_files.setdefault(category, []).append(filename)

        return {
            category: sorted(files)
            for category, files in sorted(categorized_files.items(), key=lambda item: item[0])
        }

    def usage_stats(self):
        total_bytes = 0
        file_count = 0
        paginator = self.client.get_paginator("list_objects_v2")
        list_prefix = f"{self.prefix}/" if self.prefix else ""

        for page in paginator.paginate(Bucket=self.bucket, Prefix=list_prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                relative_key = key[len(list_prefix) :] if list_prefix else key

                if "/" not in relative_key or relative_key.startswith(f"{METADATA_DIR}/"):
                    continue

                category, filename = relative_key.split("/", 1)
                if not is_safe_path_part(category) or not is_safe_path_part(filename):
                    continue

                file_count += 1
                total_bytes += item.get("Size", 0)

        return {"file_count": file_count, "total_bytes": total_bytes}

    def add_category(self, category):
        categories = set(self.list_categories())
        categories.add(category)
        self.write_categories(categories)

    def delete_category(self, category):
        if self.list_files().get(category):
            raise ValueError("分類裡還有檔案，請先刪除檔案。")

        categories = set(self.list_categories())
        categories.discard(category)
        self.write_categories(categories)

    def save(self, file_storage, category, filename):
        file_storage.stream.seek(0)
        extra_args = {}
        if file_storage.mimetype:
            extra_args["ContentType"] = file_storage.mimetype

        self.client.upload_fileobj(
            file_storage.stream,
            self.bucket,
            self.object_key(category, filename),
            ExtraArgs=extra_args,
        )

    def delete(self, category, filename):
        self.client.delete_object(
            Bucket=self.bucket,
            Key=self.object_key(category, filename),
        )

    def download_response(self, category, filename):
        content_disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": self.object_key(category, filename),
                "ResponseContentDisposition": content_disposition,
            },
            ExpiresIn=self.presigned_url_expires,
        )

        return redirect(url)

    def object_key(self, category, filename):
        key = f"{category}/{filename}"
        if self.prefix:
            return f"{self.prefix}/{key}"

        return key

    def metadata_key(self):
        return self.object_key(METADATA_DIR, METADATA_FILENAME)

    def read_categories(self):
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self.metadata_key())
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise

        data = json.loads(response["Body"].read().decode("utf-8"))
        return [category for category in data.get("categories", []) if is_safe_path_part(category)]

    def write_categories(self, categories):
        cleaned_categories = sorted({category for category in categories if is_safe_path_part(category)})
        body = json.dumps({"categories": cleaned_categories}, ensure_ascii=False, indent=2).encode("utf-8")

        self.client.put_object(
            Bucket=self.bucket,
            Key=self.metadata_key(),
            Body=body,
            ContentType="application/json; charset=utf-8",
        )
