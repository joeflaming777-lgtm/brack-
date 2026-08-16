"""
Brack CLI — Main entry point.
"""
import typer
from rich.console import Console

from brack.commands import auth, repo

console = Console()

app = typer.Typer(
    name="brack",
    help="[bold cyan]BRACK[/bold cyan] — Personal Git Hosting & AI Coding Platform",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Auth commands at top level
app.command("login")(auth.login)
app.command("logout")(auth.logout)
app.command("whoami")(auth.whoami)

# Repo subcommand group
app.add_typer(repo.app, name="repo", help="Manage repositories")


def main():
    app()


if __name__ == "__main__":
    main()
