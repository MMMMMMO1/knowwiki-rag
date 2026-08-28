from sys import prefix
from learn.storage import save_file_content
from fastapi import APIRouter,UploadFile,File,Depends
from learn.storage import save_file_content
from learn.database import get_db
from learn.models import FileRecord
from sqlalchemy.orm import Session
from learn.ingest_service import IngestService
from learn.tasks import  process_rag_document

router=APIRouter(prefix="/admin")

@router.post("/upload")
async def upload_file(
        file:UploadFile=File(...),
        db: Session = Depends(get_db)
                      ):
    content = await file.read()

    saved_path=await save_file_content(
        file.filename,
        content
    )
    file_record=FileRecord(
        filename=file.filename,
        storage_path=str(saved_path),
        size=len(content)
    )
    db.add(file_record)
    db.flush()

    rag_service =IngestService(db)
    rag_document=rag_service.ingest(
        file_id=file_record.id
    )
    db.commit()
    process_rag_document.delay(rag_document.id)

    return {
        "file_id":file_record.id,
        "filename":file.filename,
        "size":len(content),
        "saved_path":str(saved_path),
        "rag_document_id":rag_document.id,
        "rag_status":rag_document.status


            }
@router.get("/files")
async def get_files(
        db:Session=Depends(get_db)
):
    files=db.query(FileRecord).all()
    return files