"""Shared project-local layout for generated-image skills."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from pathlib import Path
from typing import Any, Mapping
import unicodedata


PROJECT_MARKERS = (
    ".git",
    ".hg",
    "AGENTS.md",
    "CLAUDE.md",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "composer.json",
    "Gemfile",
    "project.config.json",
)
MAX_SLUG_LENGTH = 48


class ImageOutputLayoutError(RuntimeError):
    """Raised when a default project-local image location cannot be determined."""


def find_project_root(start_dir: Path | None = None, home: Path | None = None) -> Path | None:
    """Prefer the nearest repository root, then a project marker; never use home."""
    current = (Path.cwd() if start_dir is None else start_dir).expanduser().resolve()
    home_dir = (Path.home() if home is None else home).expanduser().resolve()
    candidates = []
    for candidate in (current, *current.parents):
        if candidate == home_dir:
            break
        candidates.append(candidate)
    for candidate in candidates:
        if any((candidate / marker).exists() for marker in (".git", ".hg")):
            return candidate
    for candidate in candidates:
        if candidate == home_dir:
            break
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    return None


def content_slug(value: str) -> str:
    """Convert content to a safe, readable filename slug.

    Prioritizes ASCII characters to avoid encoding issues across systems.
    For non-ASCII text (like Chinese), keeps only alphanumeric chars and converts to ASCII.
    """
    normalized = unicodedata.normalize("NFKC", value or "").strip()

    # Check if the string contains mostly ASCII
    ascii_ratio = sum(1 for c in normalized if ord(c) < 128) / max(len(normalized), 1)

    characters: list[str] = []
    for character in normalized:
        # Keep ASCII alphanumeric and some punctuation
        if character.isascii() and (character.isalnum() or character in "-_"):
            characters.append(character.lower())
        # For non-ASCII alphanumeric (like Chinese), transliterate or skip
        elif character.isalnum():
            # Try to transliterate to ASCII using NFKD decomposition
            decomposed = unicodedata.normalize("NFKD", character)
            ascii_chars = "".join(c for c in decomposed if c.isascii() and c.isalnum())
            if ascii_chars:
                characters.append(ascii_chars.lower())
            # If no ASCII representation, use pinyin-style (just skip for now)
            # A full solution would use a library like pypinyin for Chinese
        elif character.isspace() or character in "-_":
            characters.append("-")

    cleaned = re.sub(r"-+", "-", "".join(characters)).strip("-.")
    result = cleaned[:MAX_SLUG_LENGTH].rstrip("-.")

    # If we end up with nothing (all non-ASCII with no transliteration), use generic name
    return result if result else "image"


def _markdown_value(value: Any) -> str:
    return str(value).replace("\n", " ").strip()


@dataclass(frozen=True)
class ImageOutputLayout:
    images_dir: Path
    prompts_dir: Path
    task_dir: Path
    timestamp: datetime
    managed_root: Path | None = None
    provider: str = ""
    model: str = ""

    @property
    def date_label(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d")

    @property
    def name_prefix(self) -> str:
        base = self.timestamp.strftime("%Y%m%d-%H%M%S")
        parts = [base]

        # Provider abbreviation
        if self.provider:
            provider_map = {
                "rightcode": "rc",
                "right code": "rc",
                "callai": "ca",
            }
            provider_slug = provider_map.get(self.provider.lower(), self.provider.lower()[:3])
            parts.append(provider_slug)

        # Model slug (keep the full distinctive part)
        if self.model:
            # Remove common prefixes to keep it concise but distinctive
            model_slug = self.model.lower()
            # gpt-image-2.5 -> gpt-image-2.5
            # nano-banana-2 -> nano-banana-2
            # Keep the full model name, it's already distinctive
            parts.append(model_slug)

        return "-".join(parts)

    def prepare(self) -> None:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir.mkdir(parents=True, exist_ok=True)
        if self.managed_root is not None:
            ignore = self.managed_root / ".gitignore"
            if not ignore.exists():
                ignore.write_text("# Generated image artifacts; move approved assets into the project manually.\n*\n!.gitignore\n", encoding="utf-8")

    def next_image_path(self, prompt: str, suffix: str) -> Path:
        slug = content_slug(prompt)
        sequence = 1
        while True:
            stem = f"{self.name_prefix}-{sequence:03d}-{slug}"
            image = self.images_dir / f"{stem}{suffix}"
            prompt_file = self.prompts_dir / f"{stem}.md"
            if not image.exists() and not prompt_file.exists():
                return image
            sequence += 1

    def save_image(self, content: bytes, suffix: str, filename_slug: str, metadata: Mapping[str, Any], original_prompt: str = "") -> Path:
        """Save image with separate filename slug and original prompt for metadata.

        Args:
            content: Image binary content
            suffix: File extension (e.g., ".png")
            filename_slug: String to use for generating the filename
            metadata: Metadata dict to save
            original_prompt: Original prompt to save in the .md file (defaults to filename_slug if empty)
        """
        self.prepare()
        image = self.next_image_path(filename_slug, suffix)
        image.write_bytes(content)
        # Use original_prompt for the .md file if provided, otherwise fall back to filename_slug
        prompt_to_save = original_prompt if original_prompt else filename_slug
        self.write_prompt(image, prompt_to_save, metadata)
        return image

    def write_prompt(self, image: Path, prompt: str, metadata: Mapping[str, Any]) -> Path:
        self.prepare()
        prompt_file = self.prompts_dir / f"{image.stem}.md"
        lines = [f"# {image.stem}", ""]
        for label, key in (("服务商", "provider"), ("模型", "model"), ("尺寸", "size"), ("质量", "quality"), ("操作", "operation"), ("生成时间", "generated_at")):
            value = metadata.get(key)
            if value is not None and _markdown_value(value):
                lines.append(f"- {label}: {_markdown_value(value)}")
        lines.extend(["", "## 提示词", "", prompt.strip(), ""])
        prompt_file.write_text("\n".join(lines), encoding="utf-8")
        return prompt_file


def resolve_layout(
    output_dir: Path | None = None,
    *,
    cwd: Path | None = None,
    now: datetime | None = None,
    task_namespace: str,
    provider: str = "",
    model: str = "",
) -> ImageOutputLayout:
    timestamp = now or datetime.now()
    if output_dir is not None:
        images_dir = output_dir.expanduser().resolve()
        return ImageOutputLayout(
            images_dir=images_dir,
            prompts_dir=images_dir / ".prompts",
            task_dir=images_dir / ".tasks" / task_namespace,
            timestamp=timestamp,
            provider=provider,
            model=model,
        )
    project_root = find_project_root(cwd)
    if project_root is None:
        raise ImageOutputLayoutError(
            "No project root was found. Run this command from a project directory or pass --output-dir explicitly."
        )
    root = project_root / "output" / "images"
    return ImageOutputLayout(
        images_dir=root / timestamp.strftime("%Y-%m-%d"),
        prompts_dir=root / ".prompts" / timestamp.strftime("%Y-%m-%d"),
        task_dir=root / ".tasks" / task_namespace,
        timestamp=timestamp,
        managed_root=root,
        provider=provider,
        model=model,
    )
