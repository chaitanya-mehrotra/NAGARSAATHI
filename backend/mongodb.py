from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MONGODB_URI = os.getenv("MONGODB_URI")

client = MongoClient(MONGODB_URI)

db = client["NAGARSAATHI"]

users_collection = db["users"]

client.admin.command("ping")

print("MongoDB connected successfully!")