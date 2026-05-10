# Capstone — 3D Printer Lab Reservation & Consumables System

Final project for Purdue Global IT299 capstone. A reservation, consumables tracking, and maintenance system for a university 3D printer lab, modeled loosely on the Seattle Public Library item-checkout pattern, with a LlamaIndex RAG layer on top of structured PostgreSQL data.

## Stack

- **Backend:** FastAPI + SQLAlchemy
- **Database:** PostgreSQL 16 in Docker
- **RAG layer:** LlamaIndex + Ollama (local inference, no external API calls)
- **Config:** python-dotenv for environment-based secrets
- **Testing:** pytest

## Project Structure

    capstone/
    ├── app/
    │   ├── __init__.py
    │   ├── database.py         # SQLAlchemy engine, session factory, get_db dependency
    │   ├── main.py             # FastAPI application entry point (in progress)
    │   └── query.py            # LlamaIndex query engine integration
    ├── db/
    │   ├── schema.sql          # Table definitions
    │   └── sample_data.sql     # Seed data for development
    ├── test_db.py              # Database connection smoke test
    ├── requirements.txt        # Top-level dependencies (unpinned)
    ├── requirements.lock.txt   # Resolved versions for reproducible builds
    ├── .env.example            # Template for local configuration
    └── .env                    # Local config (not committed)

## Environment Setup

### Prerequisites

- Docker Engine (for PostgreSQL)
- Python 3.10 or later
- `git`

### 1. Database

```bash
docker run -d --name postgres-capstone \
  -e POSTGRES_USER=dave \
  -e POSTGRES_PASSWORD=<your-password> \
  -e POSTGRES_DB=library_db \
  -p 5432:5432 \
  -v postgres_capstone_data:/var/lib/postgresql/data \
  --restart unless-stopped \
  postgres:16

docker exec -i postgres-capstone psql -U dave -d library_db < db/schema.sql
docker exec -i postgres-capstone psql -U dave -d library_db < db/sample_data.sql
```

### 2. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration

Copy `.env.example` to `.env` and fill in your database credentials:

```bash
cp .env.example .env
# edit .env with your values
```

### 4. Verify

```bash
python test_db.py
```

Expected output:

    Connected successfully!
    PostgreSQL 16.x ...

## Dependency Management

This project uses a two-file dependency strategy:

- **`requirements.txt`** — top-level dependencies, unpinned. Human-readable list of libraries the project actually needs. Edit this when adding or removing a dependency.
- **`requirements.lock.txt`** — exact resolved versions from a known-good install, generated with `pip freeze`. Use this for reproducible environments:

```bash
pip install -r requirements.lock.txt
```

### Regenerating the lock file

After changing `requirements.txt`, regenerate the lock file from a clean venv:

```bash
deactivate 2>/dev/null
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python test_db.py                    # smoke test
pip freeze > requirements.lock.txt
```

### Reproducibility note

An earlier version of `requirements.txt` contained pinned dependency versions that did not exist on PyPI (for example, `numpy==2.4.4`, `networkx==3.6.1`). The file had not been tested by a clean install before being committed, so the problem only surfaced when the project was deployed to a new host. The current two-file pattern exists to prevent recurrence: unpinned top-level requirements are validated against a resolved lock file, and any change to either file requires a clean-venv smoke test.

**Principle:** A dependency file is only valid if it has been tested by a clean install.

## Migration History

| Date | Event |
|---|---|
| March 2026 | Project scaffolded on IdeaPad Docker host |
| April 2026 | IdeaPad retired; PostgreSQL container migrated to Threadripper `docker-host` VM (VM 200) |
| April 2026 | Requirements regenerated after discovering hallucinated version pins |

## License

Academic project — Purdue Global IT299.
