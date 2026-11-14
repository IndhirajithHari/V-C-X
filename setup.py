from setuptools import setup, find_packages

setup(
    name="vcx",
    version="2.0.0",
    description="VCX: Version Control for Everything (v2.0) - High-performance CDC, Zstandard, and SQLite Merkle DAG",
    author="VCX Developers",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "zstandard>=0.22.0",
        "fastcdc>=1.5.0",
        "watchdog>=4.0.0",
        "rich>=13.0.0",
        "pyinotify>=0.9.6; sys_platform == 'linux'",
        "trimesh>=4.0.0",
        "numpy>=1.24.0",
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "vcx = vcx.cli.main:main",
        ],
    },
)
