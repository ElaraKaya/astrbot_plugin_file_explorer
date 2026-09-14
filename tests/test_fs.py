import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fs import FileSandbox, FSError, is_within, safe_filename  # noqa: E402


def test_is_within(tmp_path: Path):
    root = tmp_path / "data"
    root.mkdir()
    inside = root / "a" / "b.txt"
    inside.parent.mkdir()
    inside.write_text("x", encoding="utf-8")
    assert is_within(inside, root)
    assert is_within(root, root)
    assert not is_within(tmp_path, root)


def test_escape_rejected(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    box = FileSandbox(data_path=data)
    try:
        box.resolve(str(tmp_path / "outside.txt"))
        assert False, "should reject path outside root"
    except FSError as exc:
        assert exc.status == 403


def test_safe_filename():
    assert safe_filename("a.txt") == "a.txt"
    try:
        safe_filename("../x")
        assert False
    except FSError:
        pass


def test_mkdir_and_list(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    box = FileSandbox(data_path=data)
    box.mkdir(str(data), "hello")
    listing = box.list_dir(str(data))
    names = [item["name"] for item in listing["items"]]
    assert "hello" in names
    assert os.path.isdir(data / "hello")


def test_archive_dir_to_zip(tmp_path: Path):
    import zipfile
    data = tmp_path / "data"
    data.mkdir()
    folder = data / "my_project"
    folder.mkdir()
    (folder / "file1.txt").write_text("hello 1", encoding="utf-8")
    sub = folder / "sub"
    sub.mkdir()
    (sub / "file2.txt").write_text("hello 2", encoding="utf-8")

    box = FileSandbox(data_path=data)
    zip_dest = tmp_path / "out.zip"
    box.archive_dir_to_zip(str(folder), zip_dest)

    assert zip_dest.exists()
    with zipfile.ZipFile(zip_dest, "r") as zf:
        namelist = zf.namelist()
        assert "my_project/file1.txt" in namelist
        assert "my_project/sub/file2.txt" in namelist
        assert zf.read("my_project/file1.txt").decode("utf-8") == "hello 1"
        assert zf.read("my_project/sub/file2.txt").decode("utf-8") == "hello 2"
