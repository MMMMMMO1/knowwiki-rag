from pathlib import Path

async def save_file_content(filename:str,content:bytes):
     upload_dir =Path("learn/uploads")
     upload_dir.mkdir(parents=True,exist_ok=True)
     file_path=upload_dir/filename
     file_path.write_bytes(content)
     return file_path