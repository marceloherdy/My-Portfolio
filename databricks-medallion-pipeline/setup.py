from setuptools import setup, find_packages

setup(
    name="databricks_medallion_pipeline",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "databricks-connect==16.4.21",
    ],
)