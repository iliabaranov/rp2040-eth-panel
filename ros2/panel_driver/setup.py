import os
from glob import glob

from setuptools import setup

package_name = "panel_driver"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages",
            ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Ilia",
    maintainer_email="90713890+iliabaranov@users.noreply.github.com",
    description="ROS 2 driver for the RP2040-ETH operator panel (TCP/JSON).",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "panel_driver = panel_driver.panel_node:main",
        ],
    },
)
