from pathlib import Path
from string import Template

_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Load a prompt template from prompts/<name>.md"""
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def render(name: str, **kwargs: str) -> str:
    """Load and render a prompt template, substituting $PLACEHOLDER tokens."""
    return Template(load(name)).safe_substitute(**kwargs)
