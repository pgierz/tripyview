#!/usr/bin/env python
# -*- coding: utf-8 -*-

'''The setup script.'''

from setuptools import setup, find_packages

with open('README.md') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = [
    'cartopy',
    'cmocean',
    'dask',
    'ipython',
    'joblib',
    'jupyter',
    'matplotlib',
    'pickle5'
    'netCDF4',
    'numba',
    'numpy',
    'pandas',
    'geopandas',
    'scipy',
    'seawater',
    'shapely',
    'xarray',
    'pyfesom2',
    'pyresample',
    'pytest',
    'papermill', 
    'jinja2',
    'pyyaml',
    'pyvista'
]

setup_requirements = ['pytest-runner']

test_requirements = ['pytest']

setup(
    author='FESOM team',
    author_email='Patrick.Scholzz@awi.de',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    entry_points={
        'console_scripts': [
            'diagrun=tripyview.sub_diagrun:diagrun',  # command=package.module:function
        ]
    },
    description='FESOM2 tools',
    install_requires=requirements,
    license='MIT license',
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='tripyview',
    name='tripyview',
    packages=['tripyview'],
    package_dir={'tripyview': 'tripyview'},
    #package_data={'': ['*.shp',]},
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/patrickscholz/tripyview',
    #download_url='https://github.com/FESOM/pyfesom2/archive/0.2.0.tar.gz',
    version='0.1.0',
    zip_safe=False,
)
