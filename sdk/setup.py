from setuptools import setup, find_packages

setup(
    name="equihax",
    version="0.1.0",
    description="Equihax tenant and environment management SDK",
    packages=find_packages(),
    package_data={"equihax": ["migrations/*.sql"]},
    python_requires=">=3.9",
    install_requires=[
        "PyMySQL>=1.1.0",
        "boto3>=1.28.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-mock>=3.0.0",
            "moto>=4.0.0",   # AWS mocking for tests
            "twine>=4.0.0",  # publishing to CodeArtifact
        ]
    }
)
