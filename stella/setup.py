from setuptools import setup, find_packages

setup(
    name="stella",
    version="0.1.0",
    author="Deborah Dahl",
    author_email="dahl@conversational-technologies.com",
    description="Conversational agent framework based on OpenFloor",
    packages=find_packages(),  # Finds all packages under stella/
    include_package_data=True,
    package_data={
        "stella": ["assistant_config.json"],  # Include config file
    },
    install_requires=[
        # List your dependencies here
        "openai",
        "flask",
        "requests",
        "flask_cors",
        "gunicorn"
        # Add others as needed
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
