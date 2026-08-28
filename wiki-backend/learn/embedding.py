import os
from itertools import batched

import httpx
EMBEDDING_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBEDDING_API_KEY = (
    os.getenv("EMBEDDING_API_KEY", "")
    .strip()
    .replace("\r", "")
    .replace("\n", "")
)
EMBEDDING_MODEL = "text-embedding-v3"



async def embed_chunks(chunks:list[str]):
    batch_size = 8
    vectors=[]
    async with httpx.AsyncClient() as client:
        for start in range(0,len(chunks),batch_size):
            batch=chunks[start:start+batch_size]
            response = await client.post(
                f"{EMBEDDING_API_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {EMBEDDING_API_KEY}",
                    "Content-Type": "application/json",

                },
                json={
                    "model": EMBEDDING_MODEL,
                    "input": chunks
                },
                timeout=60.0,
            )
            print("状态码：", response.status_code)
            print("返回内容：", response.text)

            response.raise_for_status()
            result = response.json()


            data=sorted(
                result["data"],
                key=lambda item:item["index"]
            )
            batch_vectors=[
                item["embedding"]
                for item in data
            ]

            vectors.extend(batch_vectors)







    return vectors