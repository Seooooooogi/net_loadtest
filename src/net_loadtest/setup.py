import os
from glob import glob

from setuptools import find_packages, setup

package_name = "net_loadtest"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages",
         ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Seooooooogi",
    maintainer_email="dlwotjraks@gmail.com",
    description="Staged ROS2/DDS network load test with per-port NIC-counter metering.",
    license="MIT",
    entry_points={
        "console_scripts": [
            "nic_reporter = net_loadtest.nic_reporter:main",
            "load_gen = net_loadtest.load_gen:main",
            "ext_source = net_loadtest.ext_source:main",
            "ramp_controller = net_loadtest.ramp_controller:main",
            "aggregator = net_loadtest.aggregator:main",
            "web_monitor = net_loadtest.web_monitor:main",
        ],
    },
)
