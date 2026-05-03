from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def hello():
    return {"message": "shopkeeper backend is running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}