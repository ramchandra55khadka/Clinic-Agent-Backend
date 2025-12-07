import os
from dotenv import load_dotenv
load_dotenv()

GOOGLE_API_KEY=os.getenv("GOOGLE_API_KEY")

if GOOGLE_API_KEY is None:
    raise ValueError("GOOGLE_API_KEY is not set in .env")

else:
    print("Google API key loaded successfully")


CHUNK_SIZE=os.getenv("CHUNK_SIZE")
CHUNK_OVERLAP=os.getenv("CHUNK_OVERLAP")



#Database:
DATABASE_URL = os.getenv("DATABASE_URL")
