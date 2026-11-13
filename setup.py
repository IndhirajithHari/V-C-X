from setuptools import setup, find_packages

setup(
    name="vcx",
    version="0.1.0",
    description="VCX: Version Control for Everything - Multi-domain version control system with Semantic Differ Agent",
    author="VCX Developers",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
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
