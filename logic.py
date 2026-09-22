import json
import os
import re
from pathlib import Path, PurePosixPath

PATH_PATTERN = re.compile(r'(?:(?<=\s)|(?<=["\'])|(?<=\x00)|(?<=Model:))(/[^\s"\'<>\x00-\x1f\x7f]+)')
TEXT_EXTENSIONS = {".sii", ".sui", ".mat", ".tobj", ".pmd"}
VARIANT_EXTENSIONS = (".mat", ".tobj", ".dds", ".pmd", ".ppd", ".pmg", ".pmc")
VARIANT_EXCLUDED = {".sii", ".sui"}


def reply(**data):
    print(json.dumps(data, ensure_ascii=False))


def paths_from_file(path):
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1", errors="ignore")
    return {match.group(1).rstrip(".,;:)]}") for match in PATH_PATTERN.finditer(text)}


def storage_root():
    root = Path(os.environ.get("SCS_TOOL_RESOURCES", "")).expanduser()
    if not str(root): root = Path.cwd() / "tools_resources" / "potential_path_finder"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_json(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, type(default)) else default
    except (OSError, json.JSONDecodeError):
        return default


def read_journal(root):
    try:
        lines = (root / "journal.txt").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        parts = line.split("\t", 2)
        if len(parts) >= 2: entries.append({"time": parts[0], "key": parts[1], "value": parts[2] if len(parts) > 2 else None})
    return entries


def append_journal(root, key, value=None):
    timestamp = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    try:
        with (root / "journal.txt").open("a", encoding="utf-8", newline="\n") as journal:
            journal.write(f"{timestamp}\t{key}\t{'' if value is None else str(value).replace(chr(10), ' ')}\n")
    except OSError:
        pass


def error(code, resources=None):
    if resources: append_journal(resources, "scanError", code)
    reply(status="error", code=code)


def read_saved_paths(path):
    if not path.is_file(): return set()
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return set()
    return {line.strip() for line in lines if line.strip().startswith("/") and not any(ord(char) < 32 or ord(char) == 127 for char in line)}


def extension_variants(paths):
    variants = set()
    for value in paths:
        item = PurePosixPath(value); suffix = item.suffix.lower()
        if suffix in VARIANT_EXCLUDED: continue
        stem = value[:-len(item.suffix)] if item.suffix else value
        variants.update(stem + extension for extension in VARIANT_EXTENSIONS)
    return variants


def main():
    try:
        data = json.loads(os.environ.get("SCS_TOOL_INPUT", "{}"))
    except json.JSONDecodeError:
        return error("generic")
    resources = storage_root()
    if data.get("action") == "load_state":
        reply(status="state", settings=read_json(resources / "settings.json", {}), journal=read_journal(resources)[-2:])
        return
    try:
        saved_settings = {key: str(data.get(key, "")) for key in ("log_path", "source_folder", "output_folder", "output_filename")}
        (resources / "settings.json").write_text(json.dumps(saved_settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    source = Path(str(data.get("source_folder", "")).strip()).expanduser()
    output_dir = Path(str(data.get("output_folder", "")).strip()).expanduser()
    log_value = str(data.get("log_path", "")).strip()
    filename = str(data.get("output_filename", "")).strip()
    if not str(source): return error("source_folder_required", resources)
    if not source.is_dir(): return error("source_folder_not_found", resources)
    if log_value and not Path(log_value).expanduser().is_file(): return error("log_not_found", resources)
    if not str(output_dir): return error("output_folder_required", resources)
    if not filename or Path(filename).name != filename: return error("output_name_invalid", resources)

    append_journal(resources, "scanStarted")

    found, log_paths, definition_paths, file_paths = set(), set(), set(), set()
    if log_value:
        log_paths = paths_from_file(Path(log_value).expanduser())
        found.update(log_paths)
    files_scanned = definition_files = 0
    for root, _dirs, names in os.walk(source, onerror=lambda _error: None):
        root_path = Path(root)
        for name in names:
            item = root_path / name
            try:
                relative = item.relative_to(source).as_posix()
                file_paths.add("/" + relative)
                files_scanned += 1
                if item.suffix.lower() in TEXT_EXTENSIONS:
                    definition_files += 1
                    definition_paths.update(paths_from_file(item))
            except (OSError, ValueError):
                continue
    found.update(definition_paths); found.update(file_paths)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / filename
        existing_paths = read_saved_paths(output_file)
        found.update(existing_paths)
        variants = extension_variants(found)
        new_variants = variants - found
        found.update(new_variants)
        output_file.write_text("\n".join(sorted(found, key=str.casefold)) + ("\n" if found else ""), encoding="utf-8", newline="\n")
    except OSError:
        return error("output_write_failed", resources)
    append_journal(resources, "scanDone", len(found - existing_paths))
    reply(status="ok", log_paths=len(log_paths), definition_paths=len(definition_paths), file_paths=len(file_paths), variant_paths=len(new_variants), existing_paths=len(existing_paths), added_paths=len(found - existing_paths), total_paths=len(found), files_scanned=files_scanned, definition_files=definition_files, output_file=str(output_file))


if __name__ == "__main__": main()
