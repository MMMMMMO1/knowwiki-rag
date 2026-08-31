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
     #
    if not chunks:
        return []
     

    vectors=[]
    async with httpx.AsyncClient() as client:
          # 分批处理
        for batch_idx in range(
            0,
            len(chunks),
            EMBEDDING_BATCH_SIZE
        ):

            # 当前这一批 chunk
            batch = chunks[
                batch_idx:
                batch_idx + EMBEDDING_BATCH_SIZE
            ]

            print(
                f"正在处理 embedding："
                f"{batch_idx} ~ {batch_idx + len(batch) - 1}"
            )

            response = await client.post(
                f"{EMBEDDING_API_URL}/embeddings",

                headers={
                    "Authorization": f"Bearer {EMBEDDING_API_KEY}",
                    "Content-Type": "application/json",
                },

                json={
                    "model": EMBEDDING_MODEL,
                    "input": batch,
                },

                timeout=60.0,
            )