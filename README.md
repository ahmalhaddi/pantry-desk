# Pantry Desk

Pantry Desk helps a coordinator send an available batch of food to community sites that have reported what they can take.

The sites in the demo are fictional. This is not a partnership with a food rescue organization, and it does not measure food waste.

Postgres is defined in `docker-compose.yml`. Copy `.env.example` to `.env` before starting the API. From `backend/`:

```
alembic upgrade head
uvicorn app.main:app --reload
```
