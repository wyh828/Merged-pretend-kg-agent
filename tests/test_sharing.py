import json
import zipfile

import pytest

from techtrend.sharing import (copy_public_file, package_component, portable_path,
                              reserve_export, transform_record, verify_archive)


@pytest.mark.parametrize("name", ["../data", "C:\\secret", "/etc/passwd", "\\\\host\\share", "a/../../b"])
def test_rejects_nonportable_or_escaping_paths(name):
    with pytest.raises(ValueError):
        portable_path(name)


def test_public_copy_keeps_original_and_records_removed_abstract(tmp_path):
    source = tmp_path / "original.jsonl"
    source.write_text(json.dumps({"source": "crossref", "abstract": "publisher text", "raw_snapshot": "raw\\crossref\\r.jsonl"}) + "\n", encoding="utf-8")
    original = source.read_bytes()
    target = tmp_path / "shared.jsonl"
    manifest = copy_public_file(source, target)
    row = json.loads(target.read_text(encoding="utf-8"))
    assert "abstract" not in row
    assert row["raw_snapshot"] == "raw/crossref/r.jsonl"
    assert source.read_bytes() == original
    assert "crossref_abstract_removed" in manifest["transformations"]
    with pytest.raises(FileExistsError):
        copy_public_file(source, target)


def test_transform_preserves_openalex_and_rejects_accidental_credentials():
    value, changes = transform_record({"source": "openalex", "abstract": "CC0 metadata"})
    assert value["abstract"] == "CC0 metadata" and not changes
    with pytest.raises(ValueError):
        transform_record({"api_key": "synthetic-private-key"})


def test_packages_are_immutable_and_tampering_fails(tmp_path):
    first = reserve_export(tmp_path, "research_share")
    second = reserve_export(tmp_path, "research_share")
    assert first.name == "research_share_00" and second.name == "research_share_01"
    data = first / "A"
    data.mkdir()
    (data / "works.jsonl").write_text('{"id":"W1"}\n', encoding="utf-8")
    archive = first / "data_share_00.zip"
    result = package_component(data, archive, {"component": "A"}, level=6, max_bytes=10000)
    assert result["files_checked"] == 1
    assert verify_archive(archive)["status"] == "passed"
    corrupt = second / "corrupt.zip"
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(corrupt, "w") as changed:
        for name in original.namelist():
            changed.writestr(name, b'{}' if name == "works.jsonl" else original.read(name))
    with pytest.raises(ValueError, match="Checksum mismatch"):
        verify_archive(corrupt)


def test_archive_rejects_traversal_even_with_manifest(tmp_path):
    archive = tmp_path / "escaping.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape", "value")
        bundle.writestr("manifest_00.json", '{"files": {}, "component": "A"}')
    with pytest.raises(ValueError):
        verify_archive(archive)


def test_empty_crossref_abstract_removal_is_recorded():
    value, changes = transform_record({"source": "crossref", "abstract": ""})
    assert "abstract" not in value
    assert changes == ["crossref_abstract_removed"]
