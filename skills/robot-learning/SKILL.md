---
name: robot-learning
description: "Use when the task needs Robot learning: imitation, RL and foundation models. Current practice as of 2026-10-21, with sources."
metadata:
  updated: 2026-10-21
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/robot-learning.md
---

# Robot learning: imitation, RL and foundation models

- Order of attack for a new task: scripted policy -> behaviour cloning from 50-200 demonstrations -> RL fine-tuning in
  simulation -> only then a foundation model. Each step must beat the previous on the same benchmark.
- Imitation learning (ACT, Diffusion Policy, LeRobot's implementations) works with teleoperated demos; collect demos
  in simulation first with a keyboard or gamepad teleop, then on hardware.
- RL: PPO and SAC in MuJoCo via Gymnasium-style environments; reward shaping is where projects die, so start from a
  sparse success reward plus one shaping term, and log the success rate per 10k steps.
- Sim-to-real: domain randomisation of friction, mass, camera pose and lighting; validate on 20 real trials before any
  claim. Report the sim and real success rates side by side.
- Foundation models: open VLAs (OpenVLA, pi0 family, GR00T N1 and successors) are trained on Open X-Embodiment-scale
  data. Zero-shot on a new robot is weak; the useful contribution from a laptop is a clean dataset in the LeRobot
  format, an evaluation harness, and ablations others can rerun.
- Every experiment: fixed seeds, 3 runs minimum, mean and standard deviation, config file committed, results.json
  written by the code (the research lab's results_check reads it).
- Compute reality: an 8 GB laptop trains small policies in MuJoCo overnight; anything bigger goes to a free tier
  (Kaggle 30 GPU-hours a week, Google Colab) with checkpoints saved to Drive.

Gymnasium and MuJoCo RL examples (2026).

## Sources

LeRobot docs (Hugging Face); Diffusion Policy and ACT papers; Open X-Embodiment; OpenVLA and pi0 reports;
