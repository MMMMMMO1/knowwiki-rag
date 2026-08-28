from uuid import uuid4
from sqlalchemy.orm import Session
from learn.models import RagDocument


class IngestService:
    def __init__(self,db:Session):
        self.db=db


    def ingest(self,file_id:int):
        rag_document=RagDocument(
            file_id=file_id,
            doc_id=str(uuid4()),
            status="pending"
        )


        self.db.add(rag_document)
        self.db.flush()

        return rag_document