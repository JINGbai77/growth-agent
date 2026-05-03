from fastapi import FastAPI
from data.generator import generate_data
from service.pipeline import GrowthPipeline

app = FastAPI()
pipeline = GrowthPipeline()

@app.get("/run")
def run_pipeline():
    data = generate_data()
    result = pipeline.run(data)
    return {
        "data": data,
        "result": result
    }
