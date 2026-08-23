import json
from pathlib import Path

SKIP_DIRS = {".git", ".gradle", ".idea", ".venv", "venv", "node_modules", "build", "dist", "target", "__pycache__"}
TEXT_SUFFIXES = {".css", ".env", ".example", ".gradle", ".html", ".java", ".js", ".json", ".md", ".properties", ".ps1", ".py", ".sh", ".txt", ".xml", ".yaml", ".yml"}
TEXT_NAMES = {"Dockerfile", ".dockerignore", ".editorconfig", ".gitattributes", ".gitignore", "requirements.txt"}
MOJIBAKE_MARKERS = ("\ufffd", "\u00c3", "\u00c2", "\u00ec", "\u00eb", "\u00ea", "\u00ed", "\u00db")


def is_text_file(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def main() -> None:
    errors = []
    for path in Path(".").rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts) or not is_text_file(path):
            continue
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"{path}: UTF-8 BOM is not allowed")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"{path}: invalid UTF-8 ({exc})")
            continue
        if any(marker in text for marker in MOJIBAKE_MARKERS):
            errors.append(f"{path}: possible mojibake detected")
        if path.suffix.lower() == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}: invalid JSON ({exc})")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Text integrity check passed")


if __name__ == "__main__":
    main()
