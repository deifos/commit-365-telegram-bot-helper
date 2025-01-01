# Create a virtual environment

python3 -m venv venv

# Activate the virtual environment

source venv/bin/activate

- Windows
  .\venv\Scripts\activate

# Install the required packages

pip install -r requirements.txt

# Optional: Generate a requirements.txt file from current packages:

pip freeze > requirements.txt
