from clicksec_dl.env import load_dotenv, parse_dotenv


def test_parse_dotenv_handles_comments_quotes_and_export():
    text = """
# comment
CLICKSEC_J_USERNAME=user1
CLICKSEC_J_PASSWORD="p=ss#word"
export OTHER='single'
INVALID LINE
EMPTY=
"""
    assert parse_dotenv(text) == {
        "CLICKSEC_J_USERNAME": "user1",
        "CLICKSEC_J_PASSWORD": "p=ss#word",
        "OTHER": "single",
        "EMPTY": "",
    }


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("A=from_file\nB=from_file\n", encoding="utf-8")
    monkeypatch.setenv("A", "from_env")
    monkeypatch.delenv("B", raising=False)

    load_dotenv(env_file)

    import os

    assert os.environ["A"] == "from_env"
    assert os.environ["B"] == "from_file"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path / "missing.env") == {}
