# Deployment Guide

NextRound is designed to deploy inside Docker containers for both local development and production cloud environments.

---

## 1. Local Development (Docker Compose)

### Prerequisite: Set Environment Variables
Create a `.env` file at the root of the workspace directory:
```bash
cp .env.example .env
```
Ensure database credentials and the JWT secret are configured.

### Boot containers
Spin up the local container orchestration (PostgreSQL database, FastAPI backend, Next.js frontend):
```bash
docker compose up --build
```
* **Frontend**: Accessible at `http://localhost:3000` with hot-reloading active.
* **Backend**: Accessible at `http://localhost:8000` with Swagger API docs at `http://localhost:8000/api/v1/docs`.
* **PostgreSQL**: Bound to `localhost:5432`.

### Run DB Migrations
To upgrade the database to the latest schema using Alembic:
```bash
docker compose exec backend alembic upgrade head
```

---

## 2. Production Deployment

In production, run the pre-built standalone container configurations.

### 2.1 Database Setup (PostgreSQL)
* Use a fully managed PostgreSQL database instance (such as **Neon PostgreSQL** or **AWS RDS**).
* Update the backend's environment variables to override `DATABASE_URL` with the target host connection string.

### 2.2 Backend Hosting (FastAPI)
* **Platforms**: Deploy on container platforms like **Render**, **Railway**, or **AWS ECS**.
* **Deployment steps**:
  1. Set the build context to the `./backend` directory.
  2. Map the environment variables (`DATABASE_URL`, `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `ENVIRONMENT=production`).
  3. Expose port `8000` and start the server using:
     ```bash
     uvicorn main:app --host 0.0.0.0 --port 8000
     ```

### 2.3 Frontend Hosting (Next.js)
* **Standalone Deployment**: The frontend [Dockerfile](file:///D:/NextRound/frontend/Dockerfile) builds Next.js in `standalone` mode, copying the minimal package layout required to run without full node_modules. This is ideal for container hosting on Render, Railway, or AWS.
* **Vercel Deployment**: Alternatively, Next.js can be deployed directly to Vercel:
  1. Connect your git repository to Vercel.
  2. Set the root directory configuration to `frontend`.
  3. Configure the environment variables (`NEXT_PUBLIC_API_URL` pointing to your deployed backend domain).
  4. Vercel will build and host the static pages and API routes automatically.
