from fastapi import FastAPI
from learn.router import router
from learn.database import Base,engine
from learn import models

Base.metadata.create_all(bind=engine)

app=FastAPI()
app.include_router(router,prefix="/api/v1")
@app.get("/")
async  def root():
    return {"messages":"hello"}