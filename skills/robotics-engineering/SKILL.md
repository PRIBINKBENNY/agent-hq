---
name: robotics-engineering
description: "Use when the task needs Robotics engineering on a zero budget. Current practice as of 2026-10-21, with sources."
metadata:
  updated: 2026-10-21
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/robotics-engineering.md
---

# Robotics engineering on a zero budget

- Simulation first, hardware second. MuJoCo (Apache-2.0, C/C++ with Python bindings, a JAX build for GPU RL) is the
  default for arms and manipulation; PyBullet for quick prototypes; Webots or Gazebo for mobile robots. All run on a
  laptop CPU for small scenes; keep scenes under ~20 bodies on 8 GB.
- ROS 2: Humble (LTS to May 2027) and Jazzy are the mainstream distributions; yearly LTS cadence. On macOS use the
  RoboStack conda packages or a Linux container; never fight native builds. ros2_control is the hardware interface
  layer; MujocoROS2Control 1.1.0 (May 2026) bridges MuJoCo to it.
- Describe every robot as URDF/MJCF once; derive kinematics (Pinocchio or MuJoCo's own), limits and collision meshes
  from it. Units: SI, radians, right-hand rule. State the frame in every message and plot.
- Control stack, bottom up: joint-level PID in firmware; trajectory interpolation (minimum-jerk or cubic splines) in
  software; inverse kinematics (damped least squares) for Cartesian targets; MPC only when the simple stack fails.
- Benchmarks for claims: RoboSuite (MuJoCo, 8 robots, 12 tasks), ManiSkill, LIBERO. A result without a benchmark and
  seeds is a demo, not a result.
- Safety is code: joint and velocity limits enforced in the lowest layer, an e-stop path that does not go through the
  model, and a sim-only flag that is on by default.
- Every project ships: URDF/MJCF, a reproducible sim script, tests on kinematics, a 20-second video, a README with
  the exact commands. That is what employers and collaborators open first.

simulation survey (2026); RoboSuite and ManiSkill benchmark docs.

## Sources

MuJoCo docs and JOSS paper on MujocoROS2Control (2026); ROS 2 distributions page; Black Coffee Robotics
