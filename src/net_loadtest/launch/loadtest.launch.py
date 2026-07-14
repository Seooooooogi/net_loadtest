"""One launch file, three roles. iface has NO default -- it is per-host and the
reporter refuses to guess. Find yours with:  ip -br link   (then confirm 2.5G:
ethtool <iface> | grep Speed).

  agent host  : ros2 launch net_loadtest loadtest.launch.py role:=agent iface:=enp3s0
  sink host   : ros2 launch net_loadtest loadtest.launch.py role:=sink  iface:=enp3s0
  coordinator : ros2 launch net_loadtest loadtest.launch.py role:=coordinator
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.descriptions import ParameterValue


def generate_launch_description():
    role = LaunchConfiguration("role")
    iface = LaunchConfiguration("iface")
    topic = LaunchConfiguration("topic")
    source = LaunchConfiguration("source")
    source_cmd = LaunchConfiguration("source_cmd")

    is_sink = IfCondition(PythonExpression(["'", role, "' == 'sink'"]))
    is_coord = IfCondition(PythonExpression(["'", role, "' == 'coordinator'"]))
    # nic_reporter runs on any port we want in the switch aggregate (agent OR sink)
    is_port = IfCondition(PythonExpression(["'", role, "' in ('agent', 'sink')"]))
    # agent source = our load_gen OR an external generator (perf_test/iperf3/...)
    is_gen = IfCondition(PythonExpression(
        ["'", role, "' == 'agent' and '", source, "' == 'load_gen'"]))
    is_ext = IfCondition(PythonExpression(
        ["'", role, "' == 'agent' and '", source, "' == 'ext'"]))

    return LaunchDescription([
        DeclareLaunchArgument("role", description="agent | sink | coordinator"),
        DeclareLaunchArgument("iface", default_value="",
                              description="host NIC for the switch port (required for agent/sink)"),
        DeclareLaunchArgument("topic", default_value="/loadtest/traffic"),
        DeclareLaunchArgument("source", default_value="load_gen",
                              description="agent traffic source: load_gen | ext"),
        DeclareLaunchArgument("source_cmd", default_value="",
                              description="ext source command template (see ext_source docs)"),
        DeclareLaunchArgument("web_port", default_value="8088",
                              description="coordinator dashboard port"),

        Node(package="net_loadtest", executable="nic_reporter", condition=is_port,
             parameters=[{"iface": iface}]),
        Node(package="net_loadtest", executable="load_gen", condition=is_gen,
             parameters=[{"mode": "source", "topic": topic}]),
        Node(package="net_loadtest", executable="ext_source", condition=is_ext,
             parameters=[{"source_cmd": source_cmd}]),
        Node(package="net_loadtest", executable="load_gen", condition=is_sink,
             parameters=[{"mode": "sink", "topic": topic}]),
        Node(package="net_loadtest", executable="ramp_controller", condition=is_coord),
        Node(package="net_loadtest", executable="aggregator", condition=is_coord),
        Node(package="net_loadtest", executable="web_monitor", condition=is_coord,
             parameters=[{"port": ParameterValue(LaunchConfiguration("web_port"),
                                                  value_type=int)}]),
    ])
