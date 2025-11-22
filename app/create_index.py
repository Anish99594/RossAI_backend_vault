import os
from pinecone import Pinecone
from dotenv import load_dotenv

# Load from .env
load_dotenv()

API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX")

if not API_KEY or not INDEX_NAME:
    raise ValueError("PINECONE_API_KEY or PINECONE_INDEX missing in .env file!")

pc = Pinecone(api_key=API_KEY)

# Check if index exists, otherwise create it
if not pc.has_index(INDEX_NAME):
    pc.create_index(
        name=INDEX_NAME,
        dimension=1536,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}}  # serverless mode
    )
    print(f"Index '{INDEX_NAME}' created successfully!")
else:
    print(f"Index '{INDEX_NAME}' already exists.")

print("Available indexes:", pc.list_indexes())
