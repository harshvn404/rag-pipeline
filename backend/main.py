import logging

from fastapi import FastAPI, File, UploadFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    content = await file.read()
    logger.info(
        "Received PDF: filename=%s content_type=%s size=%s",
        file.filename,
        file.content_type,
        len(content),
    )
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
    }
