#!/usr/bin/env python3
"""Generate images through OpenAI-compatible Images APIs."""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import Any, Mapping
from urllib import error, parse, request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from image_output_layout import (
    ImageOutputLayout,
    ImageOutputLayoutError,
    find_project_root,
    resolve_layout,
)


DEFAULT_MODEL = "gpt-image-2.5"
DEFAULT_SIZE = "1536x1024"
DEFAULT_QUALITY = "high"
DEFAULT_OUTPUT_FORMAT = "png"
USER_AGENT = "rightcode-image/3.0"


class ImageApiError(RuntimeError):
    """A safe, user-facing image API client error."""


@dataclass(frozen=True)
class Provider:
    slug: str
    label: str
    base_url: str
    env_var: str
    key_path: Path
    key_hosts: tuple[str, ...]
    default_model: str = DEFAULT_MODEL
    default_size: str = DEFAULT_SIZE
    default_quality: str = DEFAULT_QUALITY


PROVIDERS: dict[str, Provider] = {
    "callai": Provider(
        slug="callai",
        label="CallAI",
        base_url="https://sub.callai.one",
        env_var="CALLAI_API_KEY",
        key_path=Path.home() / ".config/callai/api_key",
        key_hosts=("callai.one",),
        # Tiered by size (2K 0.08, 4K 0.1); 4K costs 25% more for 4x the pixels.
        default_size="4096x4096",
        default_quality="high",
    ),
}
DEFAULT_PROVIDER = "callai"
def resolve_provider(slug: str) -> Provider:
    provider = PROVIDERS.get(slug.strip().lower())
    if provider is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ImageApiError(f"Unknown provider {slug!r}. Known providers: {known}")
    return provider


def read_api_key(
    provider: Provider,
    environ: Mapping[str, str] | None = None,
) -> str:
    environ = os.environ if environ is None else environ
    key = environ.get(provider.env_var, "").strip()
    if key:
        return key
    key_path = provider.key_path.expanduser()
    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        key = ""
    except OSError as exc:
        raise ImageApiError(f"Could not read API key file {key_path}: {exc}") from exc
    if not key:
        raise ImageApiError(
            f"Missing API key for {provider.label}. Set {provider.env_var} or write "
            f"the key to {key_path}. Do not paste the key into chat."
        )
    return key


def _api_url(base_url: str, path: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise ImageApiError("API base URL cannot be empty")
    return f"{base}/{path.lstrip('/')}"


def _safe_provider_message(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "empty response body"
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(body, dict):
        error_value = body.get("error")
        if isinstance(error_value, dict):
            return str(error_value.get("message") or error_value)[:500]
        if error_value:
            return str(error_value)[:500]
        if body.get("message"):
            return str(body["message"])[:500]
    return text[:500]


class UrlLibTransport:
    def __init__(self, timeout: float = 180.0, label: str = "Image API"):
        self.timeout = timeout
        self.label = label

    def request_json(
        self,
        method: str,
        url: str,
        api_key: str,
        payload: dict[str, Any] | None = None,
        stage: str = "request",
    ) -> Any:
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = _safe_provider_message(exc.read())
            endpoint = parse.urlsplit(url).path
            raise ImageApiError(
                f"{self.label} {stage} failed: {method} {endpoint}: "
                f"HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            endpoint = parse.urlsplit(url).path
            raise ImageApiError(
                f"{self.label} {stage} failed: {method} {endpoint}: {exc.reason}"
            ) from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            endpoint = parse.urlsplit(url).path
            raise ImageApiError(
                f"{self.label} {stage} returned invalid JSON from {method} {endpoint}"
            ) from exc

    def download(self, url: str, api_key: str | None = None) -> tuple[bytes, str]:
        headers = {
            "Accept": "image/*",
            "User-Agent": USER_AGENT,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = request.Request(url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.read(), response.headers.get_content_type()
        except error.HTTPError as exc:
            raise ImageApiError(
                f"{self.label} image download failed: HTTP {exc.code}: "
                f"{_safe_provider_message(exc.read())}"
            ) from exc
        except error.URLError as exc:
            raise ImageApiError(
                f"{self.label} image download failed: {exc.reason}"
            ) from exc

    def request_multipart(
        self,
        method: str,
        url: str,
        api_key: str,
        fields: Mapping[str, Any],
        files: list[tuple[str, Path]],
        stage: str = "request",
    ) -> Any:
        boundary = f"rightcode-image-{secrets.token_hex(16)}"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        for field_name, path in files:
            path = path.expanduser().resolve()
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise ImageApiError(f"Could not read input image {path}: {exc}") from exc
            safe_name = path.name.encode("ascii", errors="ignore").decode("ascii") or "image"
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("ascii"),
                    (
                        f'Content-Disposition: form-data; name="{field_name}"; '
                        f'filename="{safe_name}"\r\n'
                    ).encode("ascii"),
                    f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                    content,
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("ascii"))
        req = request.Request(
            url,
            data=b"".join(chunks),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": USER_AGENT,
            },
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = _safe_provider_message(exc.read())
            endpoint = parse.urlsplit(url).path
            raise ImageApiError(
                f"{self.label} {stage} failed: {method} {endpoint}: "
                f"HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            endpoint = parse.urlsplit(url).path
            raise ImageApiError(
                f"{self.label} {stage} failed: {method} {endpoint}: {exc.reason}"
            ) from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            endpoint = parse.urlsplit(url).path
            raise ImageApiError(
                f"{self.label} {stage} returned invalid JSON from {method} {endpoint}"
            ) from exc


def build_payload(
    prompt: str,
    model: str = DEFAULT_MODEL,
    size: str = DEFAULT_SIZE,
    quality: str = DEFAULT_QUALITY,
    count: int = 1,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    background: str | None = None,
    response_format: str | None = None,
    output_compression: int | None = None,
    moderation: str | None = None,
    user: str | None = None,
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise ImageApiError("Prompt cannot be empty")
    if count < 1:
        raise ImageApiError("Count must be at least 1")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": count,
        "output_format": output_format,
    }
    if background:
        payload["background"] = background
    if response_format:
        payload["response_format"] = response_format
    if output_compression is not None:
        if not 0 <= output_compression <= 100:
            raise ImageApiError("Output compression must be between 0 and 100")
        payload["output_compression"] = output_compression
    if moderation:
        payload["moderation"] = moderation
    if user:
        payload["user"] = user
    return payload


def _extract_model_ids(body: Any, label: str = "Image API") -> list[str]:
    values = body.get("data") if isinstance(body, dict) else body
    if not isinstance(values, list):
        raise ImageApiError(f"{label} models response has no data list")
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
        else:
            model_id = None
        if isinstance(model_id, str) and model_id.strip():
            result.append(model_id.strip())
    return result


def list_models(
    api_key: str,
    base_url: str,
    transport: Any | None = None,
) -> list[str]:
    transport = transport or UrlLibTransport()
    body = transport.request_json(
        "GET",
        _api_url(base_url, "/v1/models"),
        api_key,
        stage="models",
    )
    return _extract_model_ids(body, getattr(transport, "label", "Image API"))


def _is_provider_host(url: str, provider: Provider) -> bool:
    hostname = (parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return any(
        hostname == host or hostname.endswith(f".{host}") for host in provider.key_hosts
    )


def _extension(content_type: str | None, image_bytes: bytes, url: str = "") -> str:
    normalized = (content_type or "").split(";", 1)[0].lower()
    known = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if normalized in known:
        return known[normalized]
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return ".webp"
    suffix = Path(parse.urlsplit(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(normalized) if normalized else None
    return ".jpg" if guessed == ".jpe" else (guessed or ".png")


def _decode_image(item: dict[str, Any], label: str = "Image API") -> tuple[bytes, str | None, str]:
    encoded = item.get("b64_json")
    if isinstance(encoded, str) and encoded:
        try:
            return base64.b64decode(encoded, validate=True), None, ""
        except (binascii.Error, ValueError) as exc:
            raise ImageApiError(f"{label} returned invalid base64 image data") from exc
    url = item.get("url")
    if isinstance(url, str) and url:
        return b"", None, url
    raise ImageApiError(f"{label} image item contains neither url nor b64_json")


def _output_stem(provider: Provider, index: int) -> str:
    return f"{provider.slug}-{int(time.time() * 1000)}-{index}"


def _image_items(body: Any) -> list[dict[str, Any]] | None:
    candidates = [body]
    if isinstance(body, dict):
        candidates.extend([body.get("result"), body.get("output")])
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        items = candidate.get("data")
        if isinstance(items, list) and items:
            return items
        images = candidate.get("images")
        if isinstance(images, list) and images:
            return images
    return None


def _save_images(
    body: Any,
    api_key: str,
    output_dir: Path,
    transport: Any,
    provider: Provider,
    layout: ImageOutputLayout | None = None,
    prompt: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> list[str]:
    label = provider.label
    items = _image_items(body)
    if not items:
        raise ImageApiError(f"{label} response has no image data")
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ImageApiError(f"{label} returned an invalid image item")
        image_bytes, content_type, image_url = _decode_image(item, label)
        if image_url:
            download_key = api_key if _is_provider_host(image_url, provider) else None
            image_bytes, content_type = transport.download(image_url, download_key)
        if not image_bytes:
            raise ImageApiError(f"{label} returned an empty image")
        suffix = _extension(content_type, image_bytes, image_url)
        if layout is not None:
            path = layout.save_image(image_bytes, suffix, prompt, metadata or {})
        else:
            path = output_dir / f"{_output_stem(provider, index)}{suffix}"
            path.write_bytes(image_bytes)
        files.append(str(path))
    return files


def _check_model(
    api_key: str,
    model: str,
    base_url: str,
    transport: Any,
    provider: Provider,
) -> None:
    models = list_models(api_key, base_url=base_url, transport=transport)
    if model not in models:
        preview = ", ".join(models[:20]) or "none returned"
        raise ImageApiError(
            f"Model {model!r} is not available on {provider.label} for this API key. "
            f"Available models: {preview}"
        )


def generate(
    api_key: str,
    payload: dict[str, Any],
    output_dir: Path,
    provider: Provider,
    base_url: str | None = None,
    transport: Any | None = None,
    layout: ImageOutputLayout | None = None,
) -> dict[str, Any]:
    transport = transport or UrlLibTransport(label=provider.label)
    base_url = base_url or provider.base_url
    model = str(payload.get("model") or "")
    _check_model(api_key, model, base_url, transport, provider)

    body = transport.request_json(
        "POST",
        _api_url(base_url, "/v1/images/generations"),
        api_key,
        payload=payload,
        stage="generate",
    )
    files = _save_images(
        body, api_key, output_dir, transport, provider, layout,
        str(payload.get("prompt") or ""),
        {"provider": provider.label, "model": model, "size": payload.get("size"), "quality": payload.get("quality"), "operation": "generation", "generated_at": layout.timestamp.isoformat(sep=" ", timespec="seconds") if layout else ""},
    )

    return {
        "provider": provider.slug,
        "base_url": base_url,
        "model": model,
        "size": payload.get("size"),
        "quality": payload.get("quality"),
        "files": files,
        "count": len(files),
        "operation": "generation",
    }


def _edit_files(
    image_paths: list[Path],
    mask_path: Path | None,
) -> list[tuple[str, Path]]:
    if not image_paths:
        raise ImageApiError("At least one --image is required for editing")
    files = [("image", Path(path)) for path in image_paths]
    if mask_path is not None:
        files.append(("mask", Path(mask_path)))
    return files


def edit(
    api_key: str,
    payload: dict[str, Any],
    image_paths: list[Path],
    output_dir: Path,
    provider: Provider,
    mask_path: Path | None = None,
    base_url: str | None = None,
    transport: Any | None = None,
    layout: ImageOutputLayout | None = None,
) -> dict[str, Any]:
    transport = transport or UrlLibTransport(label=provider.label)
    base_url = base_url or provider.base_url
    model = str(payload.get("model") or "")
    _check_model(api_key, model, base_url, transport, provider)
    body = transport.request_multipart(
        "POST",
        _api_url(base_url, "/v1/images/edits"),
        api_key,
        fields=payload,
        files=_edit_files(image_paths, mask_path),
        stage="edit",
    )
    files = _save_images(
        body, api_key, output_dir, transport, provider, layout,
        str(payload.get("prompt") or ""),
        {"provider": provider.label, "model": model, "size": payload.get("size"), "quality": payload.get("quality"), "operation": "edit", "generated_at": layout.timestamp.isoformat(sep=" ", timespec="seconds") if layout else ""},
    )
    return {
        "provider": provider.slug,
        "base_url": base_url,
        "model": model,
        "size": payload.get("size"),
        "quality": payload.get("quality"),
        "files": files,
        "count": len(files),
        "operation": "edit",
    }


def _ratio(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d+)\s*", value)
    if not match:
        raise ImageApiError("Aspect ratio must look like 16:9")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 1 or height < 1:
        raise ImageApiError("Aspect ratio values must be positive")
    return width, height


def _sips_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ImageApiError(f"Could not inspect image dimensions: {result.stderr.strip()}")
    width_match = re.search(r"pixelWidth:\s*(\d+)", result.stdout)
    height_match = re.search(r"pixelHeight:\s*(\d+)", result.stdout)
    if not width_match or not height_match:
        raise ImageApiError("Could not read image dimensions from sips")
    return int(width_match.group(1)), int(height_match.group(1))


def _largest_exact_crop(
    width: int,
    height: int,
    ratio_width: int,
    ratio_height: int,
) -> tuple[int, int]:
    scale = min(width // ratio_width, height // ratio_height)
    if scale < 1:
        raise ImageApiError("Image is too small for the requested aspect ratio")
    return scale * ratio_width, scale * ratio_height


def crop_to_ratio(path: Path, aspect_ratio: str) -> Path:
    ratio_width, ratio_height = _ratio(aspect_ratio)
    width, height = _sips_dimensions(path)
    crop_width, crop_height = _largest_exact_crop(
        width, height, ratio_width, ratio_height
    )
    offset_x = max(0, (width - crop_width) // 2)
    offset_y = max(0, (height - crop_height) // 2)
    suffix = path.suffix
    ratio_label = f"{ratio_width}x{ratio_height}"
    cropped = path.with_name(f"{path.stem}-{ratio_label}{suffix}")
    cropped.write_bytes(path.read_bytes())
    result = subprocess.run(
        [
            "sips",
            "-c",
            str(crop_height),
            str(crop_width),
            "--cropOffset",
            str(offset_y),
            str(offset_x),
            str(cropped),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        cropped.unlink(missing_ok=True)
        raise ImageApiError(f"Could not crop image: {result.stderr.strip()}")
    return cropped.resolve()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate images through an OpenAI-compatible Images API "
        "and save provider originals locally."
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=("callai",),
        help="Which configured provider to call",
    )
    parser.add_argument("--prompt", help="Image prompt")
    parser.add_argument("--model", help=f"Defaults to the provider model ({DEFAULT_MODEL})")
    parser.add_argument("--size", default=None, help="Defaults to the provider default size")
    parser.add_argument("--quality", default=None, help="Defaults to the provider default quality")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument(
        "--output-format", choices=("png", "jpeg", "webp"), default=DEFAULT_OUTPUT_FORMAT
    )
    parser.add_argument("--background", choices=("auto", "transparent", "opaque"))
    parser.add_argument("--response-format", choices=("url", "b64_json"))
    parser.add_argument("--output-compression", type=int)
    parser.add_argument("--moderation", choices=("auto", "low"))
    parser.add_argument("--user", help="Optional upstream end-user identifier")
    parser.add_argument(
        "--image",
        type=Path,
        action="append",
        default=[],
        help="Input image for editing; repeat for multiple images",
    )
    parser.add_argument("--mask", type=Path, help="Optional mask image for editing")
    parser.add_argument(
        "--aspect-ratio",
        help="Optionally create a centered local crop such as 16:9; originals are preserved",
    )
    parser.add_argument("--base-url", help="Override the provider base URL")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Directory for generated files (default: "
            "<project>/generated_images/images/YYYY-MM-DD; without a project, "
            "pass --output-dir explicitly)"
        ),
    )
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="Print configured providers without calling the network",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.list_providers:
            print(
                json.dumps(
                    {
                        "providers": [
                            {
                                "slug": item.slug,
                                "label": item.label,
                                "base_url": item.base_url,
                                "env_var": item.env_var,
                                "key_path": str(item.key_path),
                                "key_configured": bool(
                                    os.environ.get(item.env_var, "").strip()
                                    or item.key_path.expanduser().is_file()
                                ),
                            }
                            for item in PROVIDERS.values()
                        ],
                        "default": DEFAULT_PROVIDER,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        provider = resolve_provider(args.provider)
        base_url = args.base_url or provider.base_url

        if args.list_models:
            api_key = read_api_key(provider)
            transport = UrlLibTransport(timeout=args.timeout, label=provider.label)
            print(
                json.dumps(
                    {
                        "provider": provider.slug,
                        "base_url": base_url,
                        "models": list_models(api_key, base_url, transport),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not args.prompt:
            raise ImageApiError("--prompt is required unless --list-models is used")
        if args.mask and not args.image:
            raise ImageApiError("--mask requires at least one --image")
        try:
            layout = resolve_layout(args.output_dir, task_namespace="relay", provider="callai", model=args.model or provider.default_model)
        except ImageOutputLayoutError as exc:
            raise ImageApiError(str(exc)) from exc
        layout.prepare()
        output_dir = layout.images_dir
        api_key = read_api_key(provider)
        transport = UrlLibTransport(timeout=args.timeout, label=provider.label)
        payload = build_payload(
            prompt=args.prompt,
            model=args.model or provider.default_model,
            size=args.size or provider.default_size,
            quality=args.quality or provider.default_quality,
            count=args.count,
            output_format=args.output_format,
            background=args.background,
            response_format=args.response_format,
            output_compression=args.output_compression,
            moderation=args.moderation,
            user=args.user,
        )
        if args.image:
            result = edit(
                api_key=api_key,
                payload=payload,
                image_paths=args.image,
                mask_path=args.mask,
                output_dir=output_dir,
                provider=provider,
                base_url=base_url,
                transport=transport,
                layout=layout,
            )
        else:
            result = generate(
                api_key=api_key,
                payload=payload,
                output_dir=output_dir,
                provider=provider,
                base_url=base_url,
                transport=transport,
                layout=layout,
            )
        if args.aspect_ratio:
            cropped_files = []
            for path in result["files"]:
                cropped = crop_to_ratio(Path(path), args.aspect_ratio)
                layout.write_prompt(
                    cropped,
                    args.prompt,
                    {"provider": provider.label, "model": result["model"], "size": result["size"], "quality": result["quality"], "operation": f"{result['operation']} crop {args.aspect_ratio}", "generated_at": layout.timestamp.isoformat(sep=" ", timespec="seconds")},
                )
                cropped_files.append(str(cropped))
            result["cropped_files"] = cropped_files
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ImageApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# Unified-entry adapter used by rightcode-image.
def run(args):
    import subprocess, json
    command=[sys.executable, str(Path(__file__)), '--provider','callai']
    for flag, value in (('--list-models', args.list_models), ('--quote', args.quote)):
        if value: command.append(flag)
    for flag, value in (('--prompt', args.prompt),('--model', args.model),('--size', args.size),('--quality', args.quality),('--output-dir', str(args.output_dir) if args.output_dir else None),('--timeout', str(args.timeout))):
        if value is not None: command.extend([flag,value])
    command.extend(['--count',str(args.count),'--output-format','png'])
    command.extend(sum((['--image',str(p)] for p in args.reference), []))
    proc=subprocess.run(command,capture_output=True,text=True)
    if proc.returncode:
        raise ImageApiError(proc.stderr.strip() or 'CallAI request failed')
    try: return json.loads(proc.stdout)
    except json.JSONDecodeError as exc: raise ImageApiError('CallAI returned invalid JSON') from exc
