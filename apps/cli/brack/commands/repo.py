"""
Brack CLI — Repository commands.
"""
import typer
from rich.console import Console
from rich.table import Table

import httpx

from brack.config import load_config, get_auth_headers, get_api_url

console = Console()
app = typer.Typer()


def _require_auth():
    config = load_config()
    if not config.token:
        console.print("[red]Error:[/red] Not logged in. Run [bold]brack login[/bold].")
        raise typer.Exit(1)
    return config


@app.command("create")
def create(
    name: str = typer.Argument(..., help="Repository name"),
    description: str = typer.Option("", "--description", "-d"),
    private: bool = typer.Option(True, "--private/--public"),
    init: bool = typer.Option(False, "--init", help="Initialize with README"),
):
    """Create a new repository."""
    config = _require_auth()
    try:
        resp = httpx.post(
            f"{config.api_url}/api/v1/repos",
            json={
                "name": name,
                "description": description or None,
                "visibility": "private" if private else "public",
                "init_readme": init,
            },
            headers=get_auth_headers(),
            timeout=15,
        )
    except httpx.ConnectError:
        console.print(f"[red]Error:[/red] Cannot connect to {config.api_url}")
        raise typer.Exit(1)

    if resp.status_code == 201:
        data = resp.json()
        owner = data["owner"]["username"]
        slug = data["slug"]
        clone_url = f"{config.api_url}/{owner}/{slug}.git"
        console.print(f"[green]✓[/green] Created [bold]{owner}/{slug}[/bold]")
        console.print(f"\n  Clone URL: [cyan]{clone_url}[/cyan]")
        console.print(f"\n  [dim]git remote add origin {clone_url}[/dim]")
        console.print(f"  [dim]git push -u origin main[/dim]")
    else:
        try:
            detail = resp.json().get("detail", "Failed to create repository.")
        except Exception:
            detail = "Failed to create repository."
        console.print(f"[red]Error:[/red] {detail}")
        raise typer.Exit(1)


@app.command("list")
def list_repos():
    """List your repositories."""
    config = _require_auth()
    try:
        resp = httpx.get(
            f"{config.api_url}/api/v1/repos",
            headers=get_auth_headers(),
            timeout=10,
        )
    except httpx.ConnectError:
        console.print(f"[red]Error:[/red] Cannot connect to {config.api_url}")
        raise typer.Exit(1)

    if resp.status_code == 200:
        data = resp.json()
        repos = data.get("repos", [])
        if not repos:
            console.print("[dim]No repositories found.[/dim]")
            return

        table = Table(title=f"Your Repositories ({data['total']} total)")
        table.add_column("Name", style="bold cyan")
        table.add_column("Visibility")
        table.add_column("Description")
        table.add_column("Updated")

        for r in repos:
            vis = "[green]public[/green]" if r["visibility"] == "public" else "[yellow]private[/yellow]"
            table.add_row(
                f"{r['owner']['username']}/{r['slug']}",
                vis,
                r.get("description") or "[dim]—[/dim]",
                r["updated_at"][:10],
            )
        console.print(table)
    else:
        console.print("[red]Error:[/red] Failed to list repositories.")
        raise typer.Exit(1)


@app.command("delete")
def delete(
    name: str = typer.Argument(..., help="owner/repo or just repo (uses current user)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a repository (irreversible)."""
    config = _require_auth()

    if "/" in name:
        owner, slug = name.split("/", 1)
    else:
        owner = config.username
        slug = name

    if not yes:
        confirm = typer.confirm(f"Delete {owner}/{slug}? This cannot be undone.")
        if not confirm:
            console.print("Aborted.")
            raise typer.Exit(0)

    try:
        resp = httpx.delete(
            f"{config.api_url}/api/v1/repos/{owner}/{slug}",
            headers=get_auth_headers(),
            timeout=15,
        )
    except httpx.ConnectError:
        console.print(f"[red]Error:[/red] Cannot connect to {config.api_url}")
        raise typer.Exit(1)

    if resp.status_code == 204:
        console.print(f"[green]✓[/green] Deleted [bold]{owner}/{slug}[/bold]")
    else:
        try:
            detail = resp.json().get("detail", "Failed to delete repository.")
        except Exception:
            detail = "Failed to delete repository."
        console.print(f"[red]Error:[/red] {detail}")
        raise typer.Exit(1)


@app.command("clone")
def clone(
    name: str = typer.Argument(..., help="owner/repo"),
    directory: str = typer.Option(None, "--dir", "-d", help="Target directory"),
):
    """Clone a Brack repository using git."""
    import subprocess
    config = _require_auth()

    if "/" in name:
        owner, slug = name.split("/", 1)
    else:
        owner = config.username
        slug = name

    clone_url = f"{config.api_url}/{owner}/{slug}.git"
    target = directory or slug

    console.print(f"Cloning [bold]{owner}/{slug}[/bold]...")
    try:
        result = subprocess.run(
            ["git", "clone", clone_url, target],
            capture_output=False,
        )
        if result.returncode == 0:
            console.print(f"[green]✓[/green] Cloned to [bold]{target}/[/bold]")
        else:
            console.print("[red]Error:[/red] Git clone failed.")
            raise typer.Exit(1)
    except FileNotFoundError:
        console.print("[red]Error:[/red] git is not installed.")
        raise typer.Exit(1)
