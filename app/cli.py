import asyncio

import typer

from app.config import get_settings
from app.database import close_mongo, create_mongo, ensure_indexes, verify_database
from app.main import configure_services
from app.services.storage import ImageKitStorage

app = typer.Typer()


async def _database_task(action):
    settings = get_settings()
    client, database = create_mongo(settings)
    try:
        return await action(database)
    finally:
        await close_mongo(client)


@app.command("init-db")
def init_db():
    async def initialize(database):
        await database.command("ping")
        await ensure_indexes(database)
        return await verify_database(database)

    result = asyncio.run(_database_task(initialize))
    typer.echo(f"MongoDB initialized: {result}")


@app.command("check-db")
def check_db():
    result = asyncio.run(_database_task(verify_database))
    typer.echo(result)
    if not result["ok"]:
        raise typer.Exit(1)


@app.command("cleanup-abandoned-imports")
def cleanup_abandoned_imports(dry_run: bool = typer.Option(False, "--dry-run")):
    async def cleanup(database):
        settings = get_settings()
        state = type("State", (), {"settings": settings})()
        holder = type("Holder", (), {"state": state})()
        configure_services(holder, database, ImageKitStorage(settings))
        return await holder.state.cleanup.cleanup_abandoned(
            settings.abandoned_import_retention_days, dry_run
        )

    result = asyncio.run(_database_task(cleanup))
    typer.echo(
        f"deleted={result['deleted']} skipped={result['skipped']} "
        f"failed={result['failed']} dry_run={dry_run}"
    )


if __name__ == "__main__":
    app()
