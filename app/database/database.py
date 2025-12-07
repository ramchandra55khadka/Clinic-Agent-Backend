from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import DATABASE_URL

# Create a database engine instance
# The engine is the starting point for any SQLAlchemy application
# It manages connection pooling and serves as the source of database connectivity
engine=create_engine(DATABASE_URL)

# Create a SessionLocal class for database sessions
# sessionmaker is a factory for creating Session classes
# autocommit=False: Don't automatically commit after each operation
# autoflush=False: Don't automatically flush changes to the database
# bind=engine: Connect this session maker to our database engine
SessionLocal=sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a base class for declarative class definitions
# This will be used as the base class for all ORM model classes
Base=declarative_base()


# Dependency function to get a database session
# This pattern is commonly used in web frameworks like FastAPI
def get_db():
    # Create a new database session
    db = SessionLocal()
    try:
        # Yield the session to the caller (dependency injection)
        # The session remains open while the caller uses it
        yield db
    finally:
        # Always close the session when done, even if an exception occurs
        # This ensures proper cleanup and return of connection to the pool
        db.close()