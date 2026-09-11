from setuptools import setup, find_packages

setup(
    name="my_databricks_project",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "databricks-connect==16.4.21",
    ],
)