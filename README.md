# Pantry Desk

Pantry Desk helps a coordinator reserve an available batch of food for community sites that have reported what they can receive.

The sites in the demo are fictional. This is not a partnership with a food rescue organization, and the app does not measure food waste. See `docs/product-validation.md` for the assumptions and the questions still open.

## Run it

Copy the environment file, then start Postgres, the API, and the web app.

```
cp .env.example .env
docker compose up --build
```

The API listens on port 8000. The web app is served on port 8080.

To run the pieces yourself:

```
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload
```

```
cd frontend
npm install
npm run dev
```

The practice password is `pantry-demo`.

- `coordinator@pantrydesk.example` records batches and reserves food
- `elmwood@pantrydesk.example` confirms a delivery for Elmwood
- `corktown@pantrydesk.example` and `riverside@pantrydesk.example` cover the other sites

`python -m app.seed --reset` replaces the practice data and refreshes the receiving windows.

## Walkthrough

1. Sign in as the coordinator.
2. Open the produce batch. Elmwood and Corktown are suggested. Lafayette is stale, Riverbend has no refrigerated storage, and Clark Park cannot receive before the deadline.
3. Adjust the quantities and reserve. Reserving again with the same idempotency key does not create a second hold.
4. Sign in as the Elmwood steward and confirm the dairy reservation that was already on the books, or cancel a reservation as the coordinator. Canceling releases the quantity once.

## How the data is organized

A food batch has a category, a unit, a storage requirement, and a distribution deadline. Sites file capacity reports: what they need, the unit, the storage they have, and the window when they can receive it. Reports are kept. The newest one is the one the suggestion uses.

An allocation moves through draft, reserved, delivered, or canceled.

- A draft does not hold stock.
- Reserved and delivered quantities cannot add up to more than the batch.
- A reservation also has to fit the room left on the latest report. Room is the reported quantity minus other reservations for that category and unit. Delivered food is not subtracted again, because the next report should already describe what is left.
- Filing a new report does not cancel a reservation. If the new number is lower than what is already reserved, the hold stays and further reservations are refused.
- Canceling a reservation releases it once. Confirming receipt keeps it out of the available quantity.
- Retried reserve, cancel, and receipt calls send an `Idempotency-Key`. The same key returns the original result.

Suggestions are a fixed rule, not a model. Eligible sites are ranked by reported quantity minus the amount reserved or delivered to that site in the last 14 days. The screen states the inputs it used.

## API

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/auth/login` | anyone with a practice account |
| GET | `/api/overview` | signed-in user |
| GET | `/api/sites` | coordinator sees the network, a steward sees assigned sites |
| POST | `/api/sites/{id}/reports` | assigned steward or coordinator |
| POST | `/api/batches` | coordinator |
| GET | `/api/batches/{id}/recommendations` | coordinator |
| POST | `/api/batches/{id}/reserve` | coordinator, requires `Idempotency-Key` |
| POST | `/api/allocations/{id}/deliver` | assigned steward or coordinator |
| POST | `/api/allocations/{id}/cancel` | coordinator |

Interactive documentation is at `/docs` when the API is running.

## Checks

From `backend/`, with `DATABASE_URL` pointing at Postgres:

```
ruff check app tests
pytest
```

The web build is `npm run build` in `frontend/`. GitHub Actions runs both.

## Known limits

- One network.
- No unit conversion between crates, cases, and pounds.
- Receipt is the full reserved quantity. There is no short delivery.
- No map, donor marketplace, or volunteer drivers.
- Demo accounts and the demo password are for local practice only.
