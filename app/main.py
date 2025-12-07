from fastapi import FastAPI,HTTPException
from .schemas import  QueryRequest,QueryResponse
from app.router import router
from app.database.database import Base,engine

from app.ai.workflows import run_rag

# Create tables if not exist
Base.metadata.create_all(bind=engine)
##Fastapi app
app=FastAPI(title="Clinic Assistant")


# Include API routes
app.include_router(router)


@app.get("/")
async def root():
    return {"message": "Clinic assistant agent API is running", "status": "healthy"}


@app.post("/chat",response_model=QueryResponse)
async def chat(request:QueryRequest):
    try:
        response=run_rag(request)
        return response
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))