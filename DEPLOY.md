# 🚀 ZTracky — Deployment Guide

This guide covers deploying ZTracky on **Render**, **AWS**, **Google Cloud**, and **Vercel**.

ZTracky has three services:

| Service | Language | Port |
|---|---|---|
| REST API | Python / FastAPI | 8000 |
| WebSocket Hub | Go | 8001 |
| Frontend | Static HTML/JS | 3001 (nginx) |

---

## 1️⃣ Render

Render is the easiest platform for ZTracky — it supports Docker, static sites, and managed Postgres.

### Prerequisites
- A Render account at [render.com](https://render.com)
- A GitHub fork of this repository

### Step 1 — Create a Postgres database

1. Dashboard → **New** → **PostgreSQL**
2. Name: `ztracky-db`, Region: closest to you
3. Copy the **Internal Database URL** (e.g. `postgresql://…`)

### Step 2 — Deploy the Python API

1. **New** → **Web Service** → connect your GitHub repo
2. **Root Directory**: `backend`
3. **Runtime**: Docker (uses `backend/Dockerfile`)
4. **Environment variables**:
   ```
   DATABASE_URL        = <postgres internal URL from step 1>
   JWT_SECRET          = <random 64-char string>
   ADMIN_KEY           = <your secret admin key>
   GO_SERVICE_URL      = https://<go-service>.onrender.com
   APP_URL             = https://<api>.onrender.com
   STRIPE_SECRET_KEY   = sk_live_…
   STRIPE_WEBHOOK_SECRET = whsec_…
   TWILIO_SID          = AC…
   TWILIO_TOKEN        = …
   TWILIO_FROM         = +1…
   ```
5. **Health check path**: `/docs`

### Step 3 — Deploy the Go WebSocket Hub

1. **New** → **Web Service** → same repo
2. **Root Directory**: `location-service`
3. **Runtime**: Docker (uses `location-service/Dockerfile`)
4. **Environment variables**:
   ```
   JWT_SECRET = <same value as API>
   PORT       = 8001
   ```
5. Render assigns a public URL — paste it into `GO_SERVICE_URL` above

### Step 4 — Deploy the Frontend

1. **New** → **Static Site** → same repo
2. **Root Directory**: `frontend`
3. **Build command**: *(leave empty — it's plain HTML/JS)*
4. **Publish directory**: `.`
5. In `frontend/app.js` and `frontend/admin.js`, update `API_BASE` constants to point to your Render API URL, or set it via a build-time environment variable injection.

### Step 5 — Configure Twilio webhook

Set your Twilio number's **Messaging** webhook URL to:
```
https://<api>.onrender.com/api/sms/webhook
```

---

## 2️⃣ AWS (Elastic Beanstalk + ECS)

### Option A — Elastic Beanstalk (simplest)

```bash
# Install EB CLI
pip install awsebcli

# From the backend directory
cd backend
eb init ztracky-api --platform docker --region us-east-1
eb create ztracky-api-prod

# Set environment variables
eb setenv \
  DATABASE_URL="postgresql://user:pass@host:5432/ztracky" \
  JWT_SECRET="<secret>" \
  ADMIN_KEY="<admin-key>" \
  STRIPE_SECRET_KEY="sk_live_…" \
  TWILIO_SID="AC…" \
  TWILIO_TOKEN="…" \
  TWILIO_FROM="+1…" \
  APP_URL="https://api.yourdomain.com"
```

Repeat from the `location-service` directory for the Go hub.

### Option B — ECS Fargate (production-grade)

1. **Create ECR repositories** for `ztracky-api` and `ztracky-ws`

```bash
aws ecr create-repository --repository-name ztracky-api
aws ecr create-repository --repository-name ztracky-ws

# Build and push
docker build -t ztracky-api ./backend
docker tag ztracky-api:latest <account>.dkr.ecr.<region>.amazonaws.com/ztracky-api:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/ztracky-api:latest

docker build -t ztracky-ws ./location-service
docker tag ztracky-ws:latest <account>.dkr.ecr.<region>.amazonaws.com/ztracky-ws:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/ztracky-ws:latest
```

2. **Create ECS Cluster** → Fargate launch type
3. **Task definitions**: one per service, map the environment variables as container environment entries
4. **Services**: set desired count, attach ALB (Application Load Balancer)
5. **RDS**: Create a PostgreSQL instance, set `DATABASE_URL` in the task definition
6. **Frontend**: Upload the `frontend/` directory to an **S3 bucket** with static website hosting enabled, then add a **CloudFront** distribution pointing at it

### Route 53 + ACM
- Register your domain in Route 53
- Request an ACM certificate
- Attach it to the CloudFront distribution and ALB

---

## 3️⃣ Google Cloud (Cloud Run + Cloud SQL)

### Step 1 — Create Cloud SQL (Postgres)

```bash
gcloud sql instances create ztracky-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=us-central1

gcloud sql databases create ztracky --instance=ztracky-db
gcloud sql users set-password postgres --instance=ztracky-db --password=<password>
```

### Step 2 — Build and push Docker images

```bash
# Enable Artifact Registry
gcloud services enable artifactregistry.googleapis.com

gcloud artifacts repositories create ztracky \
  --repository-format=docker --location=us-central1

docker build -t us-central1-docker.pkg.dev/<project>/ztracky/api ./backend
docker push us-central1-docker.pkg.dev/<project>/ztracky/api

docker build -t us-central1-docker.pkg.dev/<project>/ztracky/ws ./location-service
docker push us-central1-docker.pkg.dev/<project>/ztracky/ws
```

### Step 3 — Deploy to Cloud Run

```bash
# Python API
gcloud run deploy ztracky-api \
  --image us-central1-docker.pkg.dev/<project>/ztracky/api \
  --platform managed --region us-central1 --allow-unauthenticated \
  --add-cloudsql-instances <project>:us-central1:ztracky-db \
  --set-env-vars "DATABASE_URL=postgresql+pg8000://postgres:<password>@/ztracky?unix_sock=/cloudsql/<project>:us-central1:ztracky-db/.s.PGSQL.5432,JWT_SECRET=<secret>,ADMIN_KEY=<key>"

# Go WebSocket Hub
gcloud run deploy ztracky-ws \
  --image us-central1-docker.pkg.dev/<project>/ztracky/ws \
  --platform managed --region us-central1 --allow-unauthenticated \
  --set-env-vars "JWT_SECRET=<secret>"
```

> **Note**: Cloud Run scales to zero. For the WebSocket hub this means connections are dropped during cold starts. Use **minimum instances = 1** for production:
> ```bash
> gcloud run services update ztracky-ws --min-instances=1 --region=us-central1
> ```

### Step 4 — Frontend on Cloud Storage + Cloud CDN

```bash
gsutil mb gs://ztracky-frontend
gsutil -m cp -r frontend/* gs://ztracky-frontend/
gsutil iam ch allUsers:objectViewer gs://ztracky-frontend

# Enable website serving
gsutil web set -m index.html -e index.html gs://ztracky-frontend
```

Create a **Cloud CDN**-backed HTTPS Load Balancer pointing at the bucket.

---

## 4️⃣ Vercel

Vercel is ideal for the **frontend** only (static HTML/JS). The Python and Go services must be hosted elsewhere (Render, Railway, Fly.io, etc.).

### Step 1 — Deploy the frontend

```bash
npm install -g vercel
cd frontend
vercel --prod
```

Or connect via the Vercel Dashboard → **Import Git Repository** → set **Root Directory** to `frontend`.

Vercel will auto-detect it as a static site.

### Step 2 — Environment variable injection

Vercel does not natively inject env vars into plain HTML. Use one of:

**Option A** — Build-time replacement (add a `build` script):
```json
// frontend/package.json
{
  "scripts": {
    "build": "sed -i 's|http://localhost:8000|'$API_URL'|g' app.js admin.js"
  }
}
```
Set `API_URL` in Vercel project settings.

**Option B** — Hardcode your production API URL directly in `app.js`:
```js
const API_BASE = 'https://api.yourdomain.com';
```

### Step 3 — Deploy Python API and Go Hub

Use any container-friendly platform alongside Vercel:

| Platform | Free tier | Notes |
|---|---|---|
| [Render](https://render.com) | ✅ | Easiest Docker support |
| [Fly.io](https://fly.io) | ✅ | Great for WebSocket services |
| [Railway](https://railway.app) | ✅ | One-click GitHub deploy |

### Step 4 — CORS
After deploying, update the `allow_origins` list in `backend/main.py`:
```python
allow_origins=["https://your-vercel-app.vercel.app", "https://yourdomain.com"],
```

---

## 🔐 Production Checklist

- [ ] Change `JWT_SECRET` to a random 64-character string
- [ ] Change `ADMIN_KEY` to a strong secret
- [ ] Set `CORS allow_origins` to your specific domain(s)
- [ ] Enable HTTPS on all services (all platforms above do this automatically)
- [ ] Set `RP_ID` to your actual domain for WebAuthn to work
- [ ] Configure Twilio webhook URL
- [ ] Configure Stripe webhook URL and `STRIPE_WEBHOOK_SECRET`
- [ ] Deploy `ZTrackySubscription.sol` with Hardhat/Foundry and set contract addresses in `app.js`
- [ ] Set up database backups (RDS snapshots / Cloud SQL automatic backups)
- [ ] Set minimum 1 instance for the Go WebSocket hub (it maintains persistent connections)
