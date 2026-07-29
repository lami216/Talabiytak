# Linux deployment

1. Install Python 3.12, SQLite CLI, Nginx, Node/PM2, and clone to a fixed path. Create a dedicated Unix user.
2. Run `python3.12 -m venv .venv`, `source .venv/bin/activate`, `pip install -e .`, `sudo mkdir -p /var/lib/product-image-manager`, and grant the service user access.
3. Copy `env.example` to `.env`, set mode `600`, set `DATABASE_URL=sqlite:////var/lib/product-image-manager/app.db`, a 32+ character random secret, strong admin credentials, all ImageKit credentials, and the real domain in `TRUSTED_HOSTS`.
4. Run `alembic upgrade head`, then `APP_DIR=/actual/repository/path pm2 start ecosystem.config.js`, `pm2 save`, and `pm2 startup` (execute the command PM2 prints). One process is mandatory for SQLite and the login limiter.
5. Copy `deploy/nginx.conf.example` to `/etc/nginx/sites-available/product-image-manager`, replace the domain and absolute static path, enable it, run `nginx -t`, reload Nginx, then `certbot --nginx -d YOUR_DOMAIN`. Keep port 8000 private.
6. Verify `/health`, `/ready`, login, upload, naming and search. Inspect with `pm2 logs product-image-manager`.

## Update
`git pull --ff-only`, activate the venv, `pip install -e .`, `alembic upgrade head`, then `pm2 restart product-image-manager --update-env`.

## Backup and restore
Use SQLite's online backup API, never filesystem-copy a live WAL database:
```bash
DATABASE_PATH=/var/lib/product-image-manager/app.db BACKUP_DIR=/secure/backups ./scripts/backup.sh
pm2 stop product-image-manager
DATABASE_PATH=/var/lib/product-image-manager/app.db ./scripts/restore.sh /secure/backups/app-TIMESTAMP.db
pm2 start product-image-manager
```
Keep encrypted off-server backups and test restores. For credential rotation, update `.env`, restart with `--update-env`, and verify readiness. ImageKit keys require no database change.
