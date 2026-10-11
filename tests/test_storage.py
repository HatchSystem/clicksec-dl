import pytest

from clicksec_dl.storage import InvalidZipError, UnsafeZipEntryError, extract_zip, save_zip
from conftest import make_zip


def test_save_zip_writes_valid_zip_and_removes_part(tmp_path):
    target = tmp_path / "x" / "a.zip"
    save_zip(target, make_zip({"a.csv": b"1"}))
    assert target.is_file()
    assert not target.with_name("a.zip.part").exists()


def test_save_zip_rejects_non_zip_and_leaves_nothing(tmp_path):
    target = tmp_path / "a.zip"
    with pytest.raises(InvalidZipError):
        save_zip(target, b"<html>error</html>")
    assert list(tmp_path.iterdir()) == []


def test_extract_zip_writes_members_and_skips_existing(tmp_path):
    zip_path = tmp_path / "a.zip"
    zip_path.write_bytes(make_zip({"a.csv": b"new", "sub/b.csv": b"b"}))
    (tmp_path / "a.csv").write_bytes(b"old")

    written = extract_zip(zip_path, tmp_path)

    assert written == [tmp_path / "sub" / "b.csv"]
    assert (tmp_path / "a.csv").read_bytes() == b"old"

    written = extract_zip(zip_path, tmp_path, force=True)
    assert (tmp_path / "a.csv").read_bytes() == b"new"
    assert len(written) == 2


@pytest.mark.parametrize("name", ["../evil.csv", "/abs.csv", "sub/../../evil.csv", "C:/x.csv"])
def test_extract_zip_rejects_unsafe_entries(tmp_path, name):
    zip_path = tmp_path / "a.zip"
    zip_path.write_bytes(make_zip({name: b"x"}))
    with pytest.raises(UnsafeZipEntryError):
        extract_zip(zip_path, tmp_path / "out")
