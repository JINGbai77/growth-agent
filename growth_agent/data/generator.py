import random
from datetime import datetime, timedelta

def generate_data(days=14):
    data = []
    base = 1000

    for i in range(days):
        fluctuation = random.randint(-100, 100)

        if i == 10:
            fluctuation -= 400

        users = base + fluctuation
        date = (datetime.now() - timedelta(days=days - i)).strftime("%Y-%m-%d")

        data.append({
            "date": date,
            "new_users": users,
            "channel": random.choice(["ads", "organic", "referral"])
        })

    return data
