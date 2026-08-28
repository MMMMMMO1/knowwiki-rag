from pathlib import Path

def load_text(file_path:str):
    path = Path(file_path)

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="gbk")

    return content