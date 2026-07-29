import typer

from app.config import get_settings
from app.database import make_engine, make_session_factory
from app.services.cleanup import ImportCleanupService
from app.services.imagekit import ImageKitService

app = typer.Typer()


@app.command("cleanup-abandoned-imports")
def cleanup_abandoned_imports(dry_run: bool = typer.Option(False, "--dry-run")):
    settings = get_settings()
    service = ImportCleanupService(ImageKitService(settings))
    factory = make_session_factory(make_engine(settings))
    with factory() as session:
        result = service.cleanup(
            session, service.abandoned(session, settings.abandoned_import_retention_days), dry_run
        )
    typer.echo(
        f"deleted={result['deleted']} skipped={result['skipped']} "
        f"failed={result['failed']} dry_run={dry_run}"
    )


if __name__ == "__main__":
    app()
