# Perception and vision for robots and products (updated 2026-10-21)
- Pick the smallest model that meets the metric: YOLO-family detectors for real-time boxes, SAM-style segmenters for
  masks, DINO-style features for retrieval, monocular depth models when a depth camera is absent. State mAP, FPS and
  the hardware with every number.
- Data beats architecture: 200 well-labelled frames from the real camera beat 20,000 web images. Label with a free
  tool (CVAT, Label Studio), version the dataset, keep a held-out set the model never sees.
- Camera pipeline: calibrate intrinsics once (OpenCV chessboard), undistort, then detect. Hand-eye calibration before
  any grasp claim. Timestamps on every frame; drop late frames rather than queue them.
- Vision-language models (open weights) answer "what is this and where" for open-vocabulary tasks; they are slow
  and non-deterministic, so use them to label or to plan, not inside a control loop.
- Vision-language-action models (OpenVLA, pi0, GR00T N1 and successors) map images and language to actions. On a
  laptop they are for evaluation on benchmarks, not live control; fine-tuning needs GPU hours you do not have, so
  write the evaluation harness and the data pipeline instead, which is the part employers lack.
- Evaluate honestly: confusion matrix, failure gallery, per-class recall, a held-out video. Never report training-set
  numbers. Report latency at the deployment resolution.
- Privacy: faces and plates blurred before storage unless the user consented; no cloud upload of raw frames.
Sources: Ultralytics and OpenCV docs; Open X-Embodiment and VLA benchmark summaries (2026); MediaPipe docs.
