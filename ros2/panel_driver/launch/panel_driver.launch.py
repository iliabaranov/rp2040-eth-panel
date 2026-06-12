"""Launch the panel driver. The device IP is DHCP-assigned, so host is
REQUIRED (no sensible default):

    ros2 launch panel_driver panel_driver.launch.py host:=<device-ip>
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    host = LaunchConfiguration("host")
    port = LaunchConfiguration("port")

    return LaunchDescription([
        DeclareLaunchArgument(
            "host", default_value="",
            description="Panel device IP (DHCP-assigned; REQUIRED — the node "
                        "exits with an error if left empty)."),
        DeclareLaunchArgument(
            "port", default_value="5005",
            description="Panel device TCP port."),
        Node(
            package="panel_driver",
            executable="panel_driver",
            name="panel_driver",
            output="screen",
            parameters=[{
                "host": ParameterValue(host, value_type=str),
                "port": ParameterValue(port, value_type=int),
            }],
        ),
    ])
