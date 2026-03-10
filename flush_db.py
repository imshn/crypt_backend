from database import engine
from sqlmodel import SQLModel
from models import * # Ensure all models are imported so metadata knows about them

def flush_database():
    print("Dropping all tables...")
    SQLModel.metadata.drop_all(engine)
    print("Creating all tables...")
    SQLModel.metadata.create_all(engine)
    print("Database flushed successfully.")

if __name__ == "__main__":
    flush_database()
