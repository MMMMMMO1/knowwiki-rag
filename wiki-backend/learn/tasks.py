import asyncio
from learn.celery_app import celery_app
from learn.database import SessionLocal
from learn.models import RagDocument,FileRecord
from learn.loader import load_text
from learn.splitter import split_text
from learn.embedding import embed_chunks
from learn.vector_store import VectorStore


@celery_app.task
def process_rag_document(rag_document_id:int):
    db=SessionLocal()

    try:

        #1.找到这个rag任务
        rag_document=(
            db.query(RagDocument)
            .filter(RagDocument.id == rag_document_id)
            .first()
        )
       #2.修改状态
        rag_document.status="processing"
        db.commit()

        #3.根据file_id找到真正的文件记录
        file_record=(
            db.query(FileRecord)
            .filter(FileRecord.id==rag_document_id)
            .first()
        )



        #4.根据路径读文件
        content= load_text(
        file_record.storage_path
        )


       #5.把整篇文章切成chunk
        chunks = split_text(
            content,
            chunk_size=50,
            chunk_overlap=10
        )
        #6.看看切出来的结果
        print("===chunks===")
        for index,chunk in enumerate(chunks):
            print(
                f"\nchunk{index}:"
            )
        #7.embedding:chunks->vectors
        vectors = asyncio.run(
            embed_chunks(chunks)
        )

        print("===vectors===")

        for index,vector in enumerate(vectors):
            print(
            f"vector{index}:{vector}"
            )

         #8.vector_store:
        #chunks+vectors->数据库
        store = VectorStore(db)

        records=store.insert(
            document_id=rag_document_id,
            chunks=chunks,
            vectors=vectors
        )

        #7.处理完成
        rag_document.status="completed"
        db.commit()
        print(f"f保存了{len(records)}个chunk")

        print(f"处理完成RAG文档，id={rag_document_id}")


    finally:
        db.close( )
