from data.generator import generate_data
from service.pipeline import GrowthPipeline

if __name__ == "__main__":
    data = generate_data()
    pipeline = GrowthPipeline()

    result = pipeline.run(data)

    print("📊 数据:")
    for d in data:
        print(d)

    print("\n📈 分析结果:")
    print(result)
