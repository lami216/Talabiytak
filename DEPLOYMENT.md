# Deployment

1. Install Python 3.12 and the project (`pip install -e .`).
2. Copy `env.example` to `.env`, set mode `600`, configure MongoDB Atlas, a 32+ character random secret, strong admin credentials, ImageKit credentials, and `TRUSTED_HOSTS`.
3. Allow the application host in Atlas network access and grant its database user least-privilege access to the configured database.
4. Run `python -m app.cli init-db` once per environment and `python -m app.cli check-db` as a deployment check.
5. Start the ASGI application with `uvicorn app.main:app` or the supplied PM2 configuration.

MongoDB owns durable catalog metadata; ImageKit owns image bytes. Back up MongoDB through Atlas. No SQLite or Alembic deployment step exists.

## Re-importing images uploaded before the binary-upload fix

Deploy the fixed application before accepting another workbook import. Images that already arrived
corrupted in ImageKit cannot be repaired by this code change: delete those ImageKit files, remove
their related test/import records where appropriate, and upload the original XLSX again. The exact
original bytes cannot be recovered from a corrupted ImageKit object without the original workbook.
