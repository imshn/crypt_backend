# Backend - Crypto Portfolio Tracker

Built with FastAPI + SQLModel.

## Setup

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Environment Variables**:
    - Copy `.env.example` to `.env.local` (or `.env`):
        ```bash
        cp .env.example .env.local
        ```
    - Fill in values for Clerk and CoinGecko keys.
    - Set **only** the Turso variables:
        ```env
        TURSO_DATABASE_URL=libsql://...
        TURSO_AUTH_TOKEN=...
        ```
      leaving them blank will default to a local SQLite file (`database.db`)
      for development.
    - The `requirements.txt` already includes `libsql` so the Turso client is
      installed automatically.

## Running Locally

Run the development server with hot-reload:

```bash
uvicorn main:app --reload
```

The API will be available at: http://127.0.0.1:8000
API Documentation (Swagger UI): http://127.0.0.1:8000/docs

---

## Deploying on Render (or other PaaS)

Render supports both direct Python deployments and container-based
service definitions.  Using a Docker image gives you full control over the
runtime and makes local testing exactly mirror production.

### Docker setup

1.  **Build the image locally**:
    ```bash
    docker build -t crpt-backend .
    ```

2.  **Run locally** (pass env vars or mount a `.env.local`):
    ```bash
    docker run --rm -it \
      -p 8000:8000 \
      -e DATABASE_URL=sqlite:///database.db \
      -e NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_xxx \
      crpt-backend
    ```
    If you're testing against Turso in the container you could provide
    `-e TURSO_DATABASE_URL=libsql://... -e TURSO_AUTH_TOKEN=...` instead of
    `DATABASE_URL`.
3.  The service will listen on `0.0.0.0:8000` and pick up `$PORT` if set.

### Render configuration

1.  In the Render dashboard create a **New Web Service** and choose the
    repository containing this project.

2.  For the **Environment** select **Docker**.  Render will build the
    image using the `Dockerfile` in the repo.

3.  **Environment Variables**
    - `TURSO_DATABASE_URL` (provided by Vercel/Turso upon deployment).
      Include `TURSO_AUTH_TOKEN` for protected databases.
    - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and other Clerk keys.
    - `COINGECKO_API_KEY` if desired.

4.  No custom start command is required; the `CMD` in `Dockerfile` uses
    `$PORT`.  You can optionally override it with
    `uvicorn main:app --host 0.0.0.0 --port $PORT` if you prefer.

5.  **Migrations:** same note as above – `create_all()` runs on startup,
    but for production consider adding Alembic and invoking `alembic
    upgrade head` in a deploy hook or Docker entrypoint.

> ⚠️ **SQLite warning:** the underlying disk in Render containers is
> ephemeral.  Don't rely on a local SQLite file in production – always
> point `DATABASE_URL` at a networked database.
