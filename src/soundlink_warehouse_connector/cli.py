from __future__ import annotations

import logging

import typer

from soundlink_warehouse_connector.client.soundlink import SoundlinkClient
from soundlink_warehouse_connector.config import Settings
from soundlink_warehouse_connector.loaders.factory import build_loader
from soundlink_warehouse_connector.state.store import StateStore
from soundlink_warehouse_connector.sync.runner import SyncMode, run_sync
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
    ) as client:
        data = client.ping()
    typer.echo(f"OK: {data}")


@app.command()
def sync(
    mode: SyncMode = typer.Option("incremental", help="full or incremental sync"),
    campaign_id: str | None = typer.Option(
        None,
        "--campaign-id",
        help="Sync a single campaign instead of all",
    ),
    no_resume: bool = typer.Option(
        False,
        "--no-resume",
        help="Ignore in-progress run state and re-sync all campaigns",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging"),
) -> None:
    """Sync campaigns and metrics into the configured warehouse."""
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
        ) as client:
            stats = run_sync(
                settings,
                client,
                loader,
                state,
                mode,
                campaign_id,
                resume=not no_resume,
            )
    finally:
        loader.close()

    typer.echo(
        f"Done ({mode}): destination={settings.destination} "
        f"campaigns={stats.campaigns_synced} "
        f"skipped={stats.campaigns_skipped} "
        f"resumed_skip={stats.campaigns_resumed_skip} "
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
