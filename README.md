# RADA AI — Café Intelligence

Local-first system that compares products handed over (seen by camera) with sales recorded in the POS,
and flags divergences for **human review**. A divergence is a signal, never automatic proof of theft.

## Layout
- `edge/` — camera ingestion, detection (YOLO), tracking, handover events (runs at the café)
- `backend/` — FastAPI + PostgreSQL: POS import, reconciliation engine, alerts, analytics
- `frontend/` — Next.js dashboard
- `contracts/` — JSON schemas shared by edge and backend (visual_event, pos_sale)
- `deploy/` — docker-compose files per deployment mode (dev, local, edge, cloud)
- `simulator/` — fake detector and scenario replay, to test without a camera
- `training/` — dataset prep, fine-tuning, ONNX export
- `docs/` — architecture, business rules, POS integration, CNDP, pilot checklist

## Quick start (dev)
```
cp .env.example .env
make dev
```
Backend: http://localhost:8000/api/v1/health — Frontend: http://localhost:3000

Repo: https://github.com/kingbsm18/RADA_Coffee
