from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

from push_notification import __version__ as version

setup(
    name="push_notification",
    version=version,
    description="Common FCM push notification app for Techfinite products",
    author="Techfinite Systems",
    author_email="it-support@techfinite.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
