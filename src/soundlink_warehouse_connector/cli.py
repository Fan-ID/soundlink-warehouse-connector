from __future__ import annotations

import logging

import typer

from soundlink_warehouse_connector.client.soundlink import SoundlinkClient
from soundlink_warehouse_connector.config import Settings
from soundlink_warehouse_connector.loaders.factory import build_loader
from soundlink_warehouse_connector.state.store import StateStore
from soundlink_warehouse_connector.sync.runner import SyncEntity, SyncMode, run_sync
from soundlink_warehouse_connector.utils.logging import setup_logging

app = typer.Typer(
    name="soundlink-sync",
    help="Soundlink Public API → warehouse ELT connector",
    no_args_is_help=True,
)


@app.command()
def ping(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging"),
) -> None:
    """Verify API credentials against GET /v1/ping."""
    setup_logging(logging.DEBUG if verbose else logging.INFO)
    settings = Settings()
    with SoundlinkClient(
        api_key=settings.soundlink_api_key,
        base_url=settings.api_root,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
        campaigns_page_size=settings.campaigns_page_size,
        soundlinks_page_size=settings.soundlinks_page_size,
    ) as client:
        data = client.ping()
    typer.echo(f"OK: {data}")


@app.command()
def sync(
    mode: SyncMode = typer.Option("incremental", help="full or incremental sync"),
    entity: SyncEntity = typer.Option(
        "campaigns",
        "--entity",
        help="campaigns or soundlinks (separate warehouse tables and resume state)",
    ),
    campaign_id: str | None = typer.Option(
        None,
        "--campaign-id",
        help="Sync a single campaign (requires --entity campaigns)",
    ),
    soundlink_id: str | None = typer.Option(
        None,
        "--soundlink-id",
        help="Sync a single soundlink (requires --entity soundlinks)",
    ),
    no_resume: bool = typer.Option(
        False,
        "--no-resume",
        help="Ignore in-progress run state and re-sync all entities",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging"),
) -> None:
    """Sync one entity type (campaigns or soundlinks) into the configured warehouse."""
    setup_logging(logging.DEBUG if verbose else logging.INFO)
    settings = Settings()
    loader = build_loader(settings)
    state = StateStore(settings.state_path)
    try:
        with SoundlinkClient(
            api_key=settings.soundlink_api_key,
            base_url=settings.api_root,
            timeout_seconds=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
            campaigns_page_size=settings.campaigns_page_size,
            soundlinks_page_size=settings.soundlinks_page_size,
        ) as client:
            stats = run_sync(
                settings,
                client,
                loader,
                state,
                mode,
                campaign_id,
                soundlink_id,
                entity=entity,
                resume=not no_resume,
            )
    finally:
        loader.close()

    count_label = "campaigns" if entity == "campaigns" else "soundlinks"
    typer.echo(
        f"Done ({mode}, {entity}): destination={settings.destination} "
        f"{count_label}={stats.entities_synced} "
        f"skipped={stats.entities_skipped} "
        f"resumed_skip={stats.entities_resumed_skip} "
        f"breakdown_rows={stats.breakdown_rows} "
        f"engagement_rows={stats.engagement_rows} "
        f"windows={stats.windows_processed}"
    )
    if stats.errors:
        typer.echo(f"Errors ({len(stats.errors)}):", err=True)
        for err in stats.errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
