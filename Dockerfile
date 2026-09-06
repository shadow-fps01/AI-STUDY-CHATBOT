# Use an official lightweight Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy your requirements list first to optimize caching
COPY requirements.txt .

# Install all the packages directly into the global system path
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your project files (database.py, main.py, AGENTIC, etc.)
COPY . .

# Expose the standard web traffic port
EXPOSE 8080

# The definitive command to run your FastAPI application cleanly
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
