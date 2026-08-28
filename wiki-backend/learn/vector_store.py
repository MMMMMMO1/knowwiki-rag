import json
from sqlalchemy.orm import Session
from learn.models import RagChunk

class VectorStore:
    def __init__(self,db:Session):
        self.db=db



    def insert(
            self,
            document_id:int,
            chunks:list[str],
            vectors:list[list[float]]
    ):
        if len(chunks)!=len(vectors):
            raise ValueError(
                "chunks和Vectors数量不一致"
            )
        records=[]

        for index,(chunk,vector)in enumerate(
            zip(chunks,vectors)
        ):
            record=RagChunk(
                document_id=document_id,
                chunk_index=index,
                text=chunk,
                embedding=json.dumps(vector)
            )
            self.db.add(record)

            records.append(record)

        self.db.flush()
        return  records