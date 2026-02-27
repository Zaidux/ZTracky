"""ZTracky CLI — Terminal Location Tracker"""

from setuptools import setup, find_packages

setup(
    name="ztracky-cli",
    version="2.0.0",
    description="Terminal-based location tracking client for ZTracky",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Zaidux",
    url="https://github.com/Zaidux/ZTracky",
    py_modules=["ztracky"],
    install_requires=[
        "requests>=2.28.0",
        "rich>=13.0.0",
        "click>=8.0.0",
        "websocket-client>=1.5.0",
    ],
    entry_points={
        "console_scripts": [
            "ztracky=ztracky:cli",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Communications",
    ],
    python_requires=">=3.8",
)
