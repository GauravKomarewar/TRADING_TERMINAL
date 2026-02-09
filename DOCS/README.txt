Shoonya Trading Project
=======================

This project is distributed as a ZIP archive without a virtual environment.
Dependencies are installed using a setup script.

--------------------------------------------------
INSTALLATION STEPS
--------------------------------------------------

1) Unzip the project

   unzip shoonya_v1.2.0.zip

2) Enter the project directory

   cd shoonya

3) Make setup script executable (first time only)

   chmod +x setup.sh

4) Run setup

   ./setup.sh

This will:
- Create a Python virtual environment (venv/)
- Upgrade pip
- Install all required dependencies from requirements/requirements.txt

--------------------------------------------------
ACTIVATING THE ENVIRONMENT
--------------------------------------------------

After setup, activate the virtual environment:

   source venv/bin/activate

--------------------------------------------------
RUNNING THE PROJECT
--------------------------------------------------

Run your main script as usual, for example:

   python main.py

(Replace main.py with the actual entry script.)

--------------------------------------------------
IMPORTANT NOTES
--------------------------------------------------

- The virtual environment (venv/) is NOT included in the ZIP
- Do NOT delete the requirements/ folder
- Do NOT commit or share your .env file
- Python 3.9+ is recommended
- Works on Linux / EC2 / Ubuntu / Amazon Linux

--------------------------------------------------
TROUBLESHOOTING
--------------------------------------------------

If pip install fails:
- Ensure python3 and python3-venv are installed
- Re-run ./setup.sh

--------------------------------------------------
PROJECT METADATA (pyproject.toml)
--------------------------------------------------
### to run this metadata file we use [ pip install -e . ]<< command inside the brackets
This project includes a pyproject.toml file:

   shoonya/pyproject.toml

It defines:
- Project name and version
- Minimum Python version (>= 3.9)
- Internal package layout

IMPORTANT:
- You do NOT need to run any command related to pyproject.toml
- Installation is handled entirely by setup.sh and requirements.txt
- This file is for metadata and future packaging support only

--------------------------------------------------
END
--------------------------------------------------
