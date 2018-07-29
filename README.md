# EventHub

**Conference and event ticketing on Django 4.2 LTS: programme, capacity-safe ticket sales, promo codes and QR check-in at the door.**

[![CI](https://github.com/alexgeorghiou/eventhub-django/actions/workflows/ci.yml/badge.svg)](https://github.com/alexgeorghiou/eventhub-django/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-4.2%20LTS-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-3.15-A30000)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.4-37814A?logo=celery&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?logo=bootstrap&logoColor=white)

EventHub is a classic server-rendered Django application with a REST API alongside it. Organisers
build an event in the Django admin (tracks, speakers, sessions, ticket tiers, promo codes),
attendees register on public Bootstrap pages or through the API, receive an email with signed QR
tickets, and door staff scan those codes from a phone browser to check people in.

## Features

- **Events & programme** - events, parallel tracks, speakers and sessions with validation
  (sessions inside event dates, track belongs to event, no double-booked rooms).
- **Ticket tiers with hard capacity** - purchases lock the tier row with `select_for_update()`;
  a database `CHECK (quantity_sold <= capacity)` constraint backs that up.
- **Promo codes** - percentage or fixed discounts, usage limits, validity windows and tier
  restrictions; redemptions are locked and counted in the same transaction as the seats.
- **Orders & cancellation** - cancelling releases seats and promo redemptions; checked-in orders
  cannot be cancelled.
- **QR check-in** - each ticket carries an HMAC-signed token (`django.core.signing`) rendered as
  a QR code (SVG inline, PNG download). Scans are idempotent, row-locked and audit-logged.
- **Door scanner page** - uses the browser `BarcodeDetector` camera API where available, with a
  plain form fallback that works without JavaScript, plus live "checked in / sold" stats.
- **Celery** - order confirmation emails on commit, and a beat-scheduled reminder job that claims
  tickets with `SKIP LOCKED` so overlapping runs never double-send.
- **Django admin customisations** - inline tiers/promos/tracks, sales progress bars, publish and
  reminder actions, attendee CSV export, cancel-and-release action, read-only scan log.
- **REST API (DRF)** - public event/session/speaker endpoints, anonymous order creation with
  throttling, price quotes, staff check-in and stats endpoints.

## Architecture

```mermaid
flowchart LR
    subgraph Clients
        B[Attendee browser<br/>Bootstrap pages]
        API[API clients]
        S[Door scanner<br/>phone browser]
        A[Organiser<br/>Django admin]
    end

    subgraph Django["Django 4.2 (gunicorn)"]
        V[events / ticketing views]
        R[DRF API]
        C[checkin views]
        SVC[[ticketing.services<br/>purchase / cancel]]
        CI[[checkin.services<br/>signed token check-in]]
    end

    PG[(PostgreSQL)]
    RD[(Redis broker)]
    W[Celery worker]
    BT[Celery beat]
    M[SMTP / Mailpit]

    B --> V
    API --> R
    S --> C
    S --> R
    A --> Django
    V --> SVC
    R --> SVC
    R --> CI
    C --> CI
    SVC -- "SELECT ... FOR UPDATE" --> PG
    CI --> PG
    SVC -- "on_commit: confirmation" --> RD
    BT -- "every 15 min: reminders" --> RD
    RD --> W
    W --> PG
    W --> M
```

### Purchase sequence

```mermaid
sequenceDiagram
    participant U as Buyer
    participant S as purchase_tickets()
    participant DB as PostgreSQL
    participant Q as Celery
    U->>S: tier, quantity, promo code
    S->>DB: BEGIN; SELECT tier FOR UPDATE
    S->>DB: SELECT promo FOR UPDATE (if any)
    S->>S: check sales window, remaining seats, promo rules
    S->>DB: UPDATE quantity_sold, times_used; INSERT order + tickets
    S->>DB: COMMIT
    S-->>Q: on_commit -> send_order_confirmation
    S->>U: order + signed ticket links
```

## Quickstart

### Docker (PostgreSQL, Redis, worker, beat, Mailpit)

```bash
docker compose up --build
docker compose exec web python manage.py seed_demo
docker compose exec web python manage.py createsuperuser
```

- Site: http://localhost:8000
- Admin: http://localhost:8000/admin/
- Caught emails (Mailpit): http://localhost:8025
- Scanner: http://localhost:8000/checkin/pycon-riverside/ (staff login)

### Local without Docker

No PostgreSQL or Redis needed: when `DATABASE_URL` is unset the app uses SQLite, and when
`CELERY_BROKER_URL` is unset Celery tasks run eagerly in-process and emails go to the console.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
DJANGO_DEBUG=1 python manage.py runserver
```

### Tests

```bash
pytest                      # SQLite, eager Celery, locmem email
DATABASE_URL=postgres://eventhub:eventhub@localhost:5432/eventhub pytest   # + concurrency tests
ruff check . && ruff format --check .
```

The concurrency tests (`tests/test_concurrency.py`) start a dozen threads racing for five seats
and only run against PostgreSQL, where real row locks exist. CI runs them against a Postgres
service container.

## API overview

| Method | Path | Who | Purpose |
| --- | --- | --- | --- |
| GET | `/api/events/` | public | Upcoming published events (`?past=1` to include past) |
| GET | `/api/events/{slug}/` | public | Event detail with tracks and tiers (remaining seats) |
| GET | `/api/events/{slug}/sessions/` | public | Programme, optionally `?track=<id>` |
| GET | `/api/events/{slug}/speakers/` | public | Speakers for an event |
| POST | `/api/quote/` | public | Price an order and validate a promo code without reserving |
| POST | `/api/orders/` | public (throttled) | Buy tickets; `409` when capacity is exhausted |
| GET | `/api/orders/` | authenticated | Your orders (staff: all) |
| POST | `/api/orders/{reference}/cancel/` | staff | Cancel and release seats |
| POST | `/api/events/{slug}/checkin/` | staff | Submit a scanned QR token |
| GET | `/api/events/{slug}/stats/` | staff | Sold / checked-in counts per tier |

Example purchase:

```bash
curl -X POST localhost:8000/api/orders/ -H 'Content-Type: application/json' -d '{
  "tier": 1, "quantity": 2, "buyer_name": "Ada", "buyer_email": "ada@example.com",
  "promo_code": "COMMUNITY20",
  "attendees": [{"name": "Charles", "email": "charles@example.com"}]
}'
```

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | SQLite file | Any dj-database-url DSN |
| `CELERY_BROKER_URL` | *(empty)* | Empty means tasks run eagerly |
| `DJANGO_SECRET_KEY` | insecure dev key | Also signs QR and order tokens - keep it stable |
| `DJANGO_DEBUG` | `0` | |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma separated |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT` | console backend | SMTP settings |
| `SITE_URL` | `http://localhost:8000` | Used for links in emails |
| `REMINDER_LEAD_HOURS` | `24` | How long before an event reminders go out |
| `MAX_TICKETS_PER_ORDER` | `10` | |

## Project structure

```
config/            settings (env-driven), urls, celery app, API router
events/            Event, Track, Speaker, Session; public pages; read-only API; seed_demo
ticketing/         TicketTier, PromoCode, Order, Ticket; purchase/cancel services; tasks; emails
checkin/           signed tokens, QR rendering, check-in service, ScanLog, scanner page
templates/         Bootstrap 5 pages and HTML/text email templates
static/css/        small stylesheet on top of Bootstrap
tests/             pytest-django suite (models, services, API, views, admin, tasks, concurrency)
```

## Design decisions and trade-offs

- **Denormalised counters under a row lock** instead of `COUNT(*)` on tickets. Reading one
  locked row is cheap and the check constraint makes overselling impossible even if a future code
  path forgets the lock. The cost is that the counters must only be changed via the services.
- **Consistent lock ordering** (tier, then promo code) in both purchase and cancel to avoid
  deadlocks between concurrent transactions.
- **Signed tokens rather than random lookup codes in the QR.** Forged or edited codes are rejected
  before any query, and the embedded event id lets a scanner refuse tickets for another event.
  Tokens do not expire: validity is decided at scan time from the ticket row, so a printed ticket
  stays valid. Rotating `SECRET_KEY` invalidates outstanding QR codes, which is documented above.
- **Order pages behind a signed link** instead of user accounts. Buyers do not need to sign up;
  the trade-off is that anyone with the email link can view the tickets.
- **Emails on `transaction.on_commit`** so a rolled-back purchase never sends a confirmation, and
  reminders use `SKIP LOCKED` so several beat runs or workers can overlap safely.
- **No payment integration.** Orders are confirmed immediately; a real deployment would put a
  payment step between reservation and confirmation (with a short hold expiry). That is out of
  scope for this project.
- **SQLite fallback** keeps the test suite runnable with zero services; PostgreSQL-only behaviour
  is tested separately in CI.

## Roadmap

- Time-limited seat holds for a checkout step
- Waitlist that auto-offers released seats
- Per-session capacity and attendee agenda builder
- iCal feed for the programme
- Offline-capable scanner (pre-downloaded ticket list, sync on reconnect)
- Badge printing from the admin

## License

[MIT](LICENSE) - Copyright (c) 2026 Alex Georghiou
