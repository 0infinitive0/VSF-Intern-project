# Staging — Lần Chạy Đầu Tiên (First Run)

Hướng dẫn chạy app lần đầu trên **box staging** `54.151.243.201` bằng
`docker-compose.staging.yml` (build-based, không GHCR/IMAGE_TAG).

> Sau lần đầu này, các lần sau chỉ cần `git pull origin main` — workflow CI
> `.github/workflows/deploy.yml` tự SSH vào box, build và `up -d`. Xem
> [`docker-cicd.md`](./docker-cicd.md).

## 1. Chuẩn bị (chỉ làm 1 lần)

SSH vào box:

```bash
ssh ubuntu@54.151.243.201
```

Cài Docker + compose plugin (nếu chưa có):

```bash
which docker || (curl -fsSL https://get.docker.com | sh)
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
docker compose version   # cần bản có lệnh 'compose'
```

> **Log out / log in lại** để user `ubuntu` vào đúng nhóm `docker`.

AWS Console — mở **Security Group** inbound TCP **80** (`0.0.0.0/0`) cho box.

## 2. Clone code + tạo `.env`

```bash
cd /home/ubuntu
git clone https://github.com/0infinitive0/VSF-Intern-project.git app   # private repo → cần PAT
cd app && git checkout main
```

Compose đọc `env_file: ./backend/.env` nên file **phải** nằm ở `backend/.env`:

```bash
cd /home/ubuntu/app/backend
cp .env.example .env && nano .env
```

Cách nhanh nhất là copy `.env` đang chạy từ box prod `13.229.93.102`:

```bash
scp ubuntu@13.229.93.102:/path/to/backend/.env /home/ubuntu/app/backend/.env
```

Tối thiểu phải set giá trị **thật** (khớp prod):

```
LLM_PROVIDER=openai
LLM_MODEL=@cf/meta/llama-3.1-8b-instruct
LLM_API_KEY=<Cloudflare token>
LLM_API_BASE=https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=@cf/baai/bge-m3
EMBEDDING_API_KEY=<Cloudflare token>
EMBEDDING_API_BASE=<như trên>
SUPABASE_URL=<url>
SUPABASE_SERVICE_KEY=<service key>
APP_ENV=production
APP_PORT=8000
CORS_ORIGINS=http://54.151.243.201
```

> ⚠️ `CORS_ORIGINS` phải chứa origin trình duyệt (`http://54.151.243.201`),
> nếu không frontend gọi `/api` sẽ bị chặn CORS.

## 3. Build + khởi động

```bash
cd /home/ubuntu/app
docker compose -f docker-compose.staging.yml build
docker compose -f docker-compose.staging.yml up -d
docker compose -f docker-compose.staging.yml ps    # cả 2 container "Running"
```

## 4. Kiểm tra

```bash
curl -s http://localhost:8000/health                # backend
curl -s http://localhost:80/ | head -c 200          # frontend (nginx)
curl -s http://54.151.243.201/ | head -c 200        # từ máy của bạn
```

Mở trình duyệt `http://54.151.243.201` → thấy app = xong.

## 5. Logs nếu lỗi

```bash
docker compose -f docker-compose.staging.yml logs -f backend
```