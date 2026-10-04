from setuptools import setup, find_packages

# Only makes `src/` importable (pip install -e .). Dependencies are not declared here:
# pip reads the metadata from pyproject.toml, which ignores install_requires in this file.
# Install them explicitly (see README.md, "Installation").
setup(
    name="databricks_medallion_pipeline",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
)
