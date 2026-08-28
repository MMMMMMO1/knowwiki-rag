from collections import defaultdict

from sqlalchemy import Column,Integer,String,ForeignKey
from learn.database import Base

class FileRecord(Base):
    __tablename__="files"

    id=Column(Integer,primary_key=True)
    filename=Column(String,nullable=False)
    storage_path=Column(String,nullable=False)
    size=Column(Integer,nullable=False)

class RagDocument(Base):
    __tablename__="rag_documents"
    id = Column(Integer,primary_key=True)
    file_id = Column(Integer,ForeignKey("files.id"),nullable=False)
    doc_id = Column(String,unique=True,nullable=False)
    status = Column(String,nullable=False,default="pending")



class RagChunk(Base):
    __tablename__="rag_chunks"
    id=Column(Integer,primary_key=True)

    document_id=Column(
        Integer,
        ForeignKey("rag_documents.id"),
        nullable=False
    )
    chunk_index=Column(
        Integer,
        nullable=False
    )
    text=Column(
        String,
        nullable=False
    )
    embedding = Column(
        String,
        nullable=False
    )
    

