from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import os
import shutil
import uuid
from datetime import date
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from celery import Celery
import pytesseract
from PIL import Image

app = FastAPI(
    title="Document Processor API",
    description="API for uploading, analyzing and managing documents",
    version="1.0.0"
)

# Database setup
DATABASE_URL = "postgresql://elenacuprova:root@db:5432/postgres"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Models
class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, index=True)
    psth = Column(String)
    date = Column(Date)


class DocumentText(Base):
    __tablename__ = "documents_text"
    id = Column(Integer, primary_key=True, index=True)
    id_doc = Column(Integer, ForeignKey('documents.id'))
    text = Column(String)


Base.metadata.create_all(bind=engine)

# Celery setup
celery = Celery(
    'tasks',
    broker='amqp://guest:guest@rabbitmq:5672//',
    backend='rpc://'
)


@celery.task
def process_document(doc_id: int, image_path: str):
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        db = SessionLocal()
        doc_text = DocumentText(id_doc=doc_id, text=text)
        db.add(doc_text)
        db.commit()
        db.close()
        return {"status": "success", "doc_id": doc_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# API Endpoints
@app.post("/upload_doc", summary="Upload a document", response_model=dict)
async def upload_document(file: UploadFile = File(...)):
    try:
        os.makedirs("documents", exist_ok=True)
        file_name = f"{uuid.uuid4()}.jpg"
        file_path = os.path.join("documents", file_name)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        db = SessionLocal()
        doc = Document(psth=file_path, date=date.today())
        db.add(doc)
        db.commit()
        db.refresh(doc)
        db.close()

        return {"id": doc.id, "path": file_path, "date": doc.date}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/doc_delete/{doc_id}", summary="Delete a document")
async def delete_document(doc_id: int):
    try:
        db = SessionLocal()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        if os.path.exists(doc.psth):
            os.remove(doc.psth)

        db.query(DocumentText).filter(DocumentText.id_doc == doc_id).delete()
        db.delete(doc)
        db.commit()
        db.close()

        return {"message": "Document deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/doc_analyse/{doc_id}", summary="Analyze document text")
async def analyze_document(doc_id: int):
    try:
        db = SessionLocal()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        task = process_document.delay(doc_id, doc.psth)
        return {"message": "Analysis started", "task_id": task.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/get_text/{doc_id}", summary="Get extracted text")
async def get_text(doc_id: int):
    try:
        db = SessionLocal()
        doc_text = db.query(DocumentText).filter(DocumentText.id_doc == doc_id).first()
        if not doc_text:
            raise HTTPException(status_code=404, detail="Text not found")

        return {"text": doc_text.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))