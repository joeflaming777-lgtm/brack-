"""
Brack CLI — Auth commands.
"""
import typer
from rich.console import Console
from rich.prompt import Prompt

import httpx

from brack.config import load_config, save_config, BrackConfig

console = Console()
app = typer.Typer()


@app.command()
def login(
    server: str = typer.Option(None, "--server", "-s", help="Brack server URL"),
):
    """Log in to your Brack server."""
    config = load_config()
    
    if server:
        config.api_url = server.rstrip("/")
    
    console.print(f"[bold cyan]Logging in to {config.api_url}[/bold cyan]")
    
    username = Prompt.ask("Username")
    password = Prompt.ask("Password", password=True)

    try:
        resp = httpx.post(
            f"{config.api_url}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
    except httpx.ConnectError:
        console.print(f"[red]Error:[/red] Cannot connect to {config.api_url}")
        raise typer.Exit(1)

    if resp.status_code == 200:
        data = resp.json()
        config.token = data["access_token"]
        config.username = username
        save_config(config)
        console.print(f"[green]✓[/green] Logged in as [bold]{username}[/bold]")
    else:
        try:
            detail = resp.json().get("detail", "Login failed.")
        except Exception:
            detail = "Login failed."
        console.print(f"[red]Error:[/red] {detail}")
        raise typer.Exit(1)


@app.command()
def logout():
    """Log out of Brack."""
    config = load_config()
    config.token = None
    config.username = None
    save_config(config)
    console.print("[green]✓[/green] Logged out.")


@app.command()
def whoami():
    """Show the current logged-in user."""
    config = load_config()
    if not config.token:
        console.print("[yellow]Not logged in.[/yellow] Run [bold]brack login[/bold].")
        raise typer.Exit(1)

    try:
        resp = httpx.get(
            f"{config.api_url}/api/v1/auth/me",
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=10,
        )
    except httpx.ConnectError:
        console.print(f"[red]Error:[/red] Cannot connect to {config.api_url}")
        raise typer.Exit(1)

    if resp.status_code == 200:
        user = resp.json()
        console.print(f"[bold]{user['username']}[/bold] ({user['email']})")
    else:
        console.print("[red]Session expired.[/red] Please run [bold]brack login[/bold] again.")
        raise typer.Exit(1)
