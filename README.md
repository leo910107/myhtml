# Cheng-Ho Wang Flask Website

這是一個 Flask 個人網站，包含首頁、筆記、學習紀錄、關於我、站內搜尋，以及登入後的檔案上傳/刪除功能。

## Current Simple Deployment

目前先使用 GitHub Pages 靜態網站版本。根目錄的這些檔案會直接被 GitHub Pages 發佈：

```text
index.html
note.html
learning_record.html
file.html
about.html
static/
downloads/
```

GitHub Pages 上線方式：

1. 到 GitHub repo `leo910107/myhtml`。
2. 進入 `Settings` -> `Pages`。
3. Source 選 `Deploy from a branch`。
4. Branch 選 `main`，Folder 選 `/root`。
5. 儲存後，網站會在 `https://leo910107.github.io/myhtml/`。

這個版本沒有後台登入、站內搜尋、網頁上傳或刪除檔案。要新增或刪除檔案時，請在 VS Code 修改 `file.html`，並把 PDF 放進或移出 `downloads/`，再 commit/push 到 GitHub。

下面的 Flask + Cloudflare R2 說明先保留，之後如果要恢復後台上傳功能可以接著用。

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app page run --debug
```

本機啟動後開啟：

```text
http://127.0.0.1:5000
```

## Environment Variables

正式部署前請在平台後台設定這些環境變數：

```text
SECRET_KEY
ADMIN_USERNAME
ADMIN_PASSWORD
MAX_CONTENT_LENGTH
MAX_TOTAL_STORAGE_BYTES
MAX_FILE_COUNT
MAX_DOWNLOADS_PER_HOUR_PER_IP
```

本機開發時，如果沒有設定 R2，網站會繼續使用 `downloads/` 資料夾。正式長期使用建議設定 Cloudflare R2：

```text
R2_ACCOUNT_ID
R2_BUCKET
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_REGION=auto
R2_PREFIX=downloads
R2_PRESIGNED_URL_EXPIRES=600
```

如果你的 R2 bucket 使用 EU jurisdiction，或 Cloudflare 顯示了不同的 S3 endpoint，可以另外設定 `R2_ENDPOINT_URL`，例如：

```text
R2_ENDPOINT_URL=https://<ACCOUNT_ID>.eu.r2.cloudflarestorage.com
```

## Deployment

Render / Railway / DigitalOcean App Platform 都可以部署這個專案。常見設定如下：

```text
Build command: pip install -r requirements.txt
Start command: gunicorn page:app
```

Render 可以直接使用 `render.yaml` 建立服務。

## Important Note About Uploads

這個網站支援兩種檔案儲存方式：

- 沒有設定 R2：使用本機 `downloads/`，適合開發測試。
- 有設定 R2：上傳、刪除、列表和下載都走 Cloudflare R2，適合長期部署。

下載 R2 檔案時，Flask 會產生短效 presigned URL，bucket 不需要設成公開。

## Usage Limits

為了避免 Cloudflare R2 產生意外費用，網站預設有這些限制：

```text
MAX_CONTENT_LENGTH=52428800
MAX_TOTAL_STORAGE_BYTES=2147483648
MAX_FILE_COUNT=200
MAX_DOWNLOADS_PER_HOUR_PER_IP=120
```

意思是：

- 單一上傳檔案最多 50 MB。
- 整個網站最多存 2 GB。
- 最多 200 個檔案。
- 同一 IP 每小時最多下載 120 次。

如果要調整，只要在 `.env` 或部署平台的 Environment Variables 修改數字即可。把某個限制設成 `0` 代表不啟用該限制。

## Managing Categories and Files

登入管理員後，進入「常用檔案」頁面即可管理分類與檔案：

1. 新增分類：在「新增分類」輸入分類名稱，按「新增分類」。
2. 上傳檔案：選擇檔案，再選擇分類，按「上傳檔案」。
3. 刪除檔案：在檔案右側按「刪除」。
4. 刪除分類：在分類標題右側按「刪除分類」。

分類裡還有檔案時，系統不會刪除該分類。請先刪掉分類裡的檔案，再刪分類。

分類清單會存在：

```text
Local: downloads/_site_meta/categories.json
R2: <R2_PREFIX>/_site_meta/categories.json
```

Cloudflare R2 沒有真正的空資料夾，所以這個 metadata 檔用來記住空分類。

## Cloudflare R2 Setup

1. 到 Cloudflare Dashboard 建立一個 R2 bucket，例如 `cheng-ho-wang-files`。
2. 在 R2 的 API Tokens 頁面建立 S3 API token，權限選 Object Read and Write，並盡量限制到指定 bucket。
3. 把 Access Key ID、Secret Access Key、Account ID 和 Bucket name 設到部署平台的環境變數。
4. 部署後，登入網站的「常用檔案」頁，上傳和刪除就會直接操作 R2。

既有 `downloads/` 裡的 PDF 需要搬到 R2 後，正式部署才不會依賴 repo 裡的檔案。

先檢查會上傳哪些檔案：

```bash
python scripts/upload_downloads_to_r2.py --dry-run
```

確認無誤後執行：

```bash
python scripts/upload_downloads_to_r2.py
```
