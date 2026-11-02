"""Load the sibling wizard module once for the whole toolkit."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('wedding_wizard',Path(__file__).resolve().parents[1]/'wizard.py')
w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)
