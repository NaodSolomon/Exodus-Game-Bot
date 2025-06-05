# Use an appropriate Python version available on Render
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV POETRY_VERSION=1.7.1

# Install poetry
RUN pip install "poetry==$POETRY_VERSION"

# Set working directory
WORKDIR /app

# Copy only dependency definition files first
COPY pyproject.toml poetry.lock* ./

# Install project dependencies
# --no-root: Don\t install the project itself as editable
# --no-interaction: Do not ask any interactive questions
# --no-ansi: Disable ANSI output
RUN poetry install --no-root --no-interaction --no-ansi --only main

# Create the instance directory for databases and sessions
# Ensure the directory has the correct permissions
RUN mkdir -p instance && chmod 755 instance

# Copy the entire project source code
COPY . .

# Expose the port the app runs on (Render sets PORT env var)
# Gunicorn will bind to 0.0.0.0:$PORT automatically
# EXPOSE 10000 # Or Render\s default, Gunicorn uses $PORT

# Command to run the application using Gunicorn
# Render sets the PORT environment variable, Gunicorn uses it by default.
# Use the virtual environment created by Poetry
CMD ["poetry", "run", "gunicorn", "wsgi:app"]
