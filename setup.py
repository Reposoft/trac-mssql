#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

version = '0.1'

setup(
    name='MSSQLBackend',
    version=version,
    classifiers=[
                  "Programming Language :: Python",
                  "Programming Language :: Python :: 2.7",
                  "Framework :: Trac",
                  "Operating System :: OS Independent",
                  "Development Status :: 3 - Alpha",
                  "Intended Audience :: Developers",
                  "Intended Audience :: Information Technology",
                  "License :: OSI Approved :: BSD License",
                  "Natural Language :: Japanese",
                  "Topic :: Software Development :: Bug Tracking",
                  ],
    license='Modified BSD',
    author='MATOBA Akihiro',
    author_email='matobaa+trac-hacks@gmail.com',
    url='http://trac-hacks.org/wiki/matobaa',
    description='Database connector for Microsoft SQL Server via ODBC.',
    requires=['pyodbc'],
    zip_safe=True,
    packages=find_packages(exclude=['*.tests']),
#    package_data={'odbcbackend': ['htdocs/*/*']},
    entry_points={
        'trac.plugins': [
            'MSSQLBackend = mssql_backend.mssql_backend',
        ],
    },
)
