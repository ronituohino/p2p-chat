import sys
import os

project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.append(project_root)
from client.nds.nds import main

if __name__ == "__main__":
	main()
