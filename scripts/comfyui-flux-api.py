#!/usr/bin/env python3
"""Submit a FLUX.1-dev generation to ComfyUI and download its first image."""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path


def request_json(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def workflow(prompt: str, width: int, height: int, steps: int, seed: int) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-dev-fp8.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": 3.5}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "flux1-dev-api", "images": ["8", 0]}},
        "10": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "12": {"class_type": "BasicScheduler", "inputs": {"model": ["4", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "13": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["14", 0], "guider": ["15", 0], "sampler": ["11", 0], "sigmas": ["12", 0], "latent_image": ["10", 0]}},
        "14": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "15": {"class_type": "BasicGuider", "inputs": {"model": ["4", 0], "conditioning": ["7", 0]}},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("-o", "--output", type=Path, default=Path("flux1-dev.png"))
    parser.add_argument("--url", default="http://localhost:8188")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--seed", type=int, default=random.randrange(2**63))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    queued = request_json(f"{base_url}/prompt", {"prompt": workflow(args.prompt, args.width, args.height, args.steps, args.seed)})
    prompt_id = queued["prompt_id"]
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        history = request_json(f"{base_url}/history/{prompt_id}").get(prompt_id)
        if history:
            images = history.get("outputs", {}).get("9", {}).get("images", [])
            if not images:
                raise RuntimeError(f"generation finished without an image: {history}")
            image = images[0]
            query = urllib.parse.urlencode({key: image[key] for key in ("filename", "subfolder", "type")})
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(f"{base_url}/view?{query}", timeout=30) as response:
                args.output.write_bytes(response.read())
            print(f"Saved {args.output} (prompt_id={prompt_id}, seed={args.seed})")
            return
        time.sleep(2)
    raise TimeoutError(f"generation {prompt_id} did not finish in {args.timeout}s")


if __name__ == "__main__":
    main()
